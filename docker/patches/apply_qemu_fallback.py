#!/usr/bin/env python3
"""
Patch bomsh_hook.c and strace.c for QEMU /proc-based fallback.

Under QEMU x86_64 emulation (Apple Silicon Docker), strace cannot decode
syscall registers without mpers support. decode_execve() is never called,
so bomsh_record_command() never runs. However, PTRACE_EVENT_EXEC still
fires (TE_STOP_BEFORE_EXECVE), and the process is still alive at that
point. This patch:

1. Adds /proc helper functions to bomsh_hook.c
2. Adds bomsh_record_command_proc(pid) that creates cmd_data from /proc
3. Adds a call in strace.c at TE_STOP_BEFORE_EXECVE to record the
   command via /proc when decode_execve failed to do so
4. Exports bomsh_record_command_proc in bomsh_hook.h
"""
import sys


def patch_bomsh_hook_c(path):
    """Patch bomsh_hook.c with /proc fallback functions."""
    with open(path) as f:
        code = f.read()

    # --- 1. Insert /proc fallback helpers before bomsh_get_rootdir ---
    anchor = "static char * bomsh_get_rootdir(struct tcb *tcp)"
    if anchor not in code:
        print("ERROR: could not find bomsh_get_rootdir anchor")
        sys.exit(1)

    helpers = r"""
/*
 * QEMU FALLBACK: /proc-based helpers for reading process info.
 * Used when strace cannot decode syscall registers (no mpers).
 */
static char **
bomsh_proc_read_cmdline(pid_t pid, int *out_argc)
{
	char cmdpath[32];
	sprintf(cmdpath, "/proc/%d/cmdline", pid);
	FILE *f = fopen(cmdpath, "r");
	if (!f) { if (out_argc) *out_argc = 0; return NULL; }
	char buf[131072];
	size_t len = fread(buf, 1, sizeof(buf) - 1, f);
	fclose(f);
	if (len == 0) { if (out_argc) *out_argc = 0; return NULL; }
	buf[len] = 0;
	int argc = 0;
	for (size_t i = 0; i < len; i++) { if (buf[i] == 0) argc++; }
	char **argv = (char **)malloc((argc + 1) * sizeof(char *));
	int idx = 0; size_t start = 0;
	for (size_t i = 0; i <= len && idx < argc; i++) {
		if (i == len || buf[i] == 0) {
			argv[idx++] = strdup(buf + start);
			start = i + 1;
		}
	}
	argv[idx] = NULL;
	if (out_argc) *out_argc = idx;
	return argv;
}

/*
 * QEMU FALLBACK: record a command using /proc instead of ptrace regs.
 * Called from strace.c at TE_STOP_BEFORE_EXECVE when the process is
 * still alive but decode_execve() could not read syscall arguments.
 * Returns 1 if command was recorded, 0 otherwise.
 */
int bomsh_record_command_proc(pid_t pid)
{
	if (g_bomsh_config.trace_execve_cmd_only == 1) return 0;

	/* Skip if decode_execve already recorded this command */
	int idx_check = pid % BOMSH_CMDS_SIZE;
	bomsh_cmd_data_t *existing = bomsh_cmds[idx_check];
	while (existing) {
		if (existing->pid == pid) return 0;
		existing = existing->next;
	}

	/* Read argv from /proc/<pid>/cmdline first — we need it early */
	int num_argv = 0;
	char **argv = bomsh_proc_read_cmdline(pid, &num_argv);
	if (!argv || num_argv < 1) return 0;

	/*
	 * Read program path from /proc/<pid>/exe.
	 * Under QEMU/Rosetta on Apple Silicon, /proc/<pid>/exe resolves
	 * to /usr/bin/rosetta-wrapper (a virtual binary). The real program
	 * path is argv[1] from /proc/<pid>/cmdline in that case.
	 *
	 * Detection: if exe_path contains "rosetta", use argv[1] as path.
	 * We skip bomsh_is_watched_program here entirely — the caller
	 * (bomsh_hook_program -> bomsh_process_shell_command) will handle
	 * dispatch based on basename of cmd->path.
	 */
	char link[32];
	static char exe_path[PATH_MAX];
	sprintf(link, "/proc/%d/exe", pid);
	int bytes = readlink(link, exe_path, PATH_MAX - 1);
	if (bytes <= 0) {
		for (int i = 0; i < num_argv; i++) free(argv[i]);
		free(argv);
		return 0;
	}
	exe_path[bytes] = 0;
	char *path = NULL;

	if (strstr(exe_path, "rosetta")) {
		/* Rosetta wrapper detected — real binary is argv[1] */
		if (num_argv >= 2 && argv[1]) {
			path = strdup(argv[1]);
			bomsh_log_printf(3,
				"\n===proc fallback: rosetta wrapper detected, "
				"real path from argv[1]: %s\n", path);
		} else {
			for (int i = 0; i < num_argv; i++) free(argv[i]);
			free(argv);
			return 0;
		}
	} else {
		path = strdup(exe_path);
	}

	/* Now check if this program is one we care about */
	if (!bomsh_is_watched_program(path)) {
		bomsh_log_printf(8,
			"\n===proc fallback: path %s not watched, skip\n", path);
		free(path);
		for (int i = 0; i < num_argv; i++) free(argv[i]);
		free(argv);
		return 0;
	}

	/* Read cwd */
	static char pwd_buf[PATH_MAX];
	sprintf(link, "/proc/%d/cwd", pid);
	bytes = readlink(link, pwd_buf, PATH_MAX - 1);
	if (bytes <= 0) {
		free(path);
		for (int i = 0; i < num_argv; i++) free(argv[i]);
		free(argv);
		return 0;
	}
	pwd_buf[bytes] = 0;
	char *pwd = strdup(pwd_buf);

	/* Read root */
	static char root_buf[PATH_MAX];
	sprintf(link, "/proc/%d/root", pid);
	bytes = readlink(link, root_buf, PATH_MAX - 1);
	if (bytes <= 0) {
		free(path); free(pwd);
		for (int i = 0; i < num_argv; i++) free(argv[i]);
		free(argv);
		return 0;
	}
	root_buf[bytes] = 0;
	char *root = strdup(root_buf);

	bomsh_log_printf(3,
		"\n===proc fallback record pid %d path: %s args: %d\n",
		pid, path, num_argv);

	/* Store in global bomsh_cmds for later retrieval by hook_program */
	bomsh_cmd_data_t *cmd = (bomsh_cmd_data_t *)calloc(
		1, sizeof(bomsh_cmd_data_t));
	cmd->pid = pid;
	cmd->pwd = pwd;
	cmd->root = root;
	cmd->path = path;
	cmd->argv = argv;
	cmd->num_argv = num_argv;
	cmd->tracee_argv = NULL;

	/* Insert into the hash table (same as bomsh_add_cmd but simpler) */
	int index = pid % BOMSH_CMDS_SIZE;
	cmd->next = bomsh_cmds[index];
	bomsh_cmds[index] = cmd;

	return 1;
}

"""
    code = code.replace(anchor, helpers + anchor, 1)
    print("  1. Inserted /proc helpers + bomsh_record_command_proc")

    with open(path, "w") as f:
        f.write(code)
    print("  bomsh_hook.c patched OK")


def patch_bomsh_hook_h(path):
    """Add bomsh_record_command_proc declaration to header."""
    with open(path) as f:
        code = f.read()

    decl = "extern void bomsh_hook_program(int pid, int status);"
    if decl not in code:
        print("ERROR: could not find bomsh_hook_program decl")
        sys.exit(1)

    new_decl = (
        decl + "\n\n"
        "// QEMU fallback: record command from /proc "
        "(process must be alive)\n"
        "extern int bomsh_record_command_proc(pid_t pid);\n"
    )
    code = code.replace(decl, new_decl, 1)

    with open(path, "w") as f:
        f.write(code)
    print("  bomsh_hook.h patched OK")


def patch_strace_c(path):
    """Add bomsh_record_command_proc call at TE_STOP_BEFORE_EXECVE."""
    with open(path) as f:
        code = f.read()

    # Find TE_STOP_BEFORE_EXECVE case
    anchor = "case TE_STOP_BEFORE_EXECVE:"
    if anchor not in code:
        print("ERROR: could not find TE_STOP_BEFORE_EXECVE")
        sys.exit(1)

    # Find the flag clear line right after the case
    flag_clear = (
        "current_tcp->flags &= ~TCB_CHECK_EXEC_SYSCALL;"
    )
    idx = code.find(flag_clear)
    if idx < 0:
        print("ERROR: could not find TCB_CHECK_EXEC_SYSCALL clear")
        sys.exit(1)

    # Find the end of that line
    eol = code.find("\n", idx)

    # Insert our /proc fallback call right after the flag clear
    insertion = """
\t\t/*
\t\t * QEMU FALLBACK: If decode_execve() could not record the
\t\t * command (broken syscall decoding under QEMU), try to
\t\t * record it now from /proc while the process is alive.
\t\t */
\t\tbomsh_record_command_proc(current_tcp->pid);
"""
    code = code[:eol + 1] + insertion + code[eol + 1:]

    with open(path, "w") as f:
        f.write(code)
    print("  strace.c patched OK")


def main():
    if len(sys.argv) != 3:
        print(
            f"Usage: {sys.argv[0]} "
            "<strace-src-dir> <bomsh-hook-dir>"
        )
        print(
            "  e.g.: python3 apply_qemu_fallback.py "
            "./src ./src"
        )
        sys.exit(1)

    src_dir = sys.argv[1]
    hook_dir = sys.argv[2]

    print("Patching bomsh_hook.c...")
    patch_bomsh_hook_c(f"{hook_dir}/bomsh_hook.c")

    print("Patching bomsh_hook.h...")
    patch_bomsh_hook_h(f"{hook_dir}/bomsh_hook.h")

    print("Patching strace.c...")
    patch_strace_c(f"{src_dir}/strace.c")

    print("\nAll patches applied successfully!")


if __name__ == "__main__":
    main()
