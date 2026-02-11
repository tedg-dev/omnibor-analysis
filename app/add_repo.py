#!/usr/bin/env python3
"""
OmniBOR Analysis — Smart repo discovery and config generation.

Given just a repo name (e.g., "curl", "openssl", "zlib"), this script:
1. Searches GitHub for the canonical repository
2. Inspects the repo contents to detect the build system
3. Identifies configure flags, dependencies, and output binaries
4. Generates a config.yaml entry and optionally writes it
5. Identifies required -dev packages for the Dockerfile

Requires: gh CLI authenticated (https://cli.github.com/)

Usage:
    python3 add_repo.py curl
    python3 add_repo.py openssl --write
    python3 add_repo.py https://github.com/curl/curl --write
    python3 add_repo.py curl --dry-run
"""

import argparse
import base64
import json
import re
import subprocess
import sys
import yaml
from pathlib import Path


# ============================================================
# Build system detection rules
# ============================================================
# Maps file presence to build system type. Checked in priority order.
BUILD_SYSTEM_INDICATORS = [
    ("configure.ac", "autoconf"),
    ("configure.in", "autoconf"),
    ("CMakeLists.txt", "cmake"),
    ("meson.build", "meson"),
    ("Configure", "perl-configure"),
    ("config", "perl-configure"),
    ("auto/configure", "auto-configure"),
    ("configure", "configure-only"),
    ("Makefile", "make-only"),
]

# Common configure flag patterns detected from configure.ac / CMakeLists.txt
# Maps dependency names to their typical --with/--enable flags and apt packages
KNOWN_DEPENDENCIES = {
    "openssl": {
        "configure_flag": "--with-openssl",
        "cmake_flag": "-DCMAKE_USE_OPENSSL=ON",
        "apt_packages": ["libssl-dev"],
    },
    "zlib": {
        "configure_flag": "--with-zlib",
        "cmake_flag": "-DZLIB_LIBRARY=/usr/lib/x86_64-linux-gnu/libz.so",
        "apt_packages": ["zlib1g-dev"],
    },
    "nghttp2": {
        "configure_flag": "--with-nghttp2",
        "cmake_flag": "-DUSE_NGHTTP2=ON",
        "apt_packages": ["libnghttp2-dev"],
    },
    "libssh2": {
        "configure_flag": "--with-libssh2",
        "cmake_flag": "-DCMAKE_USE_LIBSSH2=ON",
        "apt_packages": ["libssh2-1-dev"],
    },
    "brotli": {
        "configure_flag": "--with-brotli",
        "cmake_flag": "-DCURL_BROTLI=ON",
        "apt_packages": ["libbrotli-dev"],
    },
    "pcre": {
        "configure_flag": "--with-pcre",
        "cmake_flag": "",
        "apt_packages": ["libpcre3-dev"],
    },
    "pcre2": {
        "configure_flag": "--with-pcre2",
        "cmake_flag": "",
        "apt_packages": ["libpcre2-dev"],
    },
    "expat": {
        "configure_flag": "--with-expat",
        "cmake_flag": "",
        "apt_packages": ["libexpat1-dev"],
    },
    "libxml2": {
        "configure_flag": "--with-libxml2",
        "cmake_flag": "",
        "apt_packages": ["libxml2-dev"],
    },
    "gnutls": {
        "configure_flag": "--with-gnutls",
        "cmake_flag": "",
        "apt_packages": ["libgnutls28-dev"],
    },
    "libevent": {
        "configure_flag": "",
        "cmake_flag": "",
        "apt_packages": ["libevent-dev"],
    },
    "libffi": {
        "configure_flag": "",
        "cmake_flag": "",
        "apt_packages": ["libffi-dev"],
    },
    "readline": {
        "configure_flag": "--with-readline",
        "cmake_flag": "",
        "apt_packages": ["libreadline-dev"],
    },
    "ncurses": {
        "configure_flag": "--with-ncurses",
        "cmake_flag": "",
        "apt_packages": ["libncurses-dev"],
    },
    "x264": {
        "configure_flag": "--enable-libx264",
        "cmake_flag": "",
        "apt_packages": ["libx264-dev"],
    },
    "x265": {
        "configure_flag": "--enable-libx265",
        "cmake_flag": "",
        "apt_packages": ["libx265-dev"],
    },
    "vpx": {
        "configure_flag": "--enable-libvpx",
        "cmake_flag": "",
        "apt_packages": ["libvpx-dev"],
    },
    "opus": {
        "configure_flag": "--enable-libopus",
        "cmake_flag": "",
        "apt_packages": ["libopus-dev"],
    },
    "lame": {
        "configure_flag": "--enable-libmp3lame",
        "cmake_flag": "",
        "apt_packages": ["libmp3lame-dev"],
    },
    "fdk-aac": {
        "configure_flag": "--enable-libfdk-aac",
        "cmake_flag": "",
        "apt_packages": ["libfdk-aac-dev"],
    },
    "freetype": {
        "configure_flag": "--enable-libfreetype",
        "cmake_flag": "",
        "apt_packages": ["libfreetype6-dev"],
    },
    "fontconfig": {
        "configure_flag": "--enable-libfontconfig",
        "cmake_flag": "",
        "apt_packages": ["libfontconfig1-dev"],
    },
    "fribidi": {
        "configure_flag": "--enable-libfribidi",
        "cmake_flag": "",
        "apt_packages": ["libfribidi-dev"],
    },
    "libass": {
        "configure_flag": "--enable-libass",
        "cmake_flag": "",
        "apt_packages": ["libass-dev"],
    },
    "curl": {
        "configure_flag": "",
        "cmake_flag": "",
        "apt_packages": ["libcurl4-openssl-dev"],
    },
}


def gh_api(endpoint):
    """Call the GitHub API via gh CLI. Returns parsed JSON."""
    result = subprocess.run(
        ["gh", "api", endpoint, "--paginate"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def gh_search_repo(query):
    """Search GitHub for a repo by name. Returns top result."""
    fields = (
        "fullName,description,url,"
        "stargazersCount,defaultBranch,language"
    )
    result = subprocess.run(
        ["gh", "search", "repos", query,
         "--limit", "5", "--json", fields],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[ERROR] gh search failed: {result.stderr.strip()}")
        return None
    try:
        repos = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    if not repos:
        print(f"[ERROR] No repositories found for '{query}'")
        return None

    # Filter for C/C++ repos, prefer exact name matches and highest stars
    c_langs = ("c", "c++", "")
    c_repos = [
        r for r in repos
        if r.get("language", "").lower() in c_langs
    ]
    candidates = c_repos if c_repos else repos

    # Prefer exact name match
    for r in candidates:
        name = r["fullName"].split("/")[-1].lower()
        if name == query.lower():
            return r

    # Fall back to highest stars
    return sorted(
        candidates,
        key=lambda r: r.get("stargazersCount", 0),
        reverse=True
    )[0]


def parse_github_url(url_or_name):
    """Parse a GitHub URL into owner/repo, or return None if it's just a name."""
    patterns = [
        r"github\.com[:/]([^/]+)/([^/.]+)",  # https or ssh
    ]
    for pat in patterns:
        match = re.search(pat, url_or_name)
        if match:
            return (
                f"{match.group(1)}/{match.group(2)}"
            )
    return None


def _repo_info_from_api(data):
    """Convert GitHub API repo response to info dict."""
    return {
        "fullName": data["full_name"],
        "description": data.get("description", ""),
        "url": data["html_url"],
        "stargazersCount": data.get(
            "stargazers_count", 0
        ),
        "defaultBranch": data.get(
            "default_branch", "main"
        ),
        "language": data.get("language", ""),
    }


def get_repo_info(name_or_url):
    """Get repository info from GitHub. Accepts name, owner/repo, or full URL."""
    full_name = parse_github_url(name_or_url)

    if full_name:
        # Direct lookup
        data = gh_api(f"repos/{full_name}")
        if data:
            return _repo_info_from_api(data)
    elif "/" in name_or_url:
        # owner/repo format
        data = gh_api(f"repos/{name_or_url}")
        if data:
            return _repo_info_from_api(data)

    # Search by name
    return gh_search_repo(name_or_url)


def get_repo_tree(full_name, branch):
    """Get the file tree of a repo (top-level + src/)."""
    # Top-level contents
    contents = gh_api(f"repos/{full_name}/contents?ref={branch}")
    if not contents:
        return []

    files = []
    for item in contents:
        files.append(item["name"])

    # Also check src/ if it exists
    src_url = (
        f"repos/{full_name}/contents/src"
        f"?ref={branch}"
    )
    src_contents = gh_api(src_url)
    if src_contents and isinstance(src_contents, list):
        for item in src_contents:
            files.append(f"src/{item['name']}")

    lib_url = (
        f"repos/{full_name}/contents/lib"
        f"?ref={branch}"
    )
    lib_contents = gh_api(lib_url)
    if lib_contents and isinstance(lib_contents, list):
        for item in lib_contents:
            files.append(f"lib/{item['name']}")

    auto_url = (
        f"repos/{full_name}/contents/auto"
        f"?ref={branch}"
    )
    auto_contents = gh_api(auto_url)
    if auto_contents and isinstance(auto_contents, list):
        for item in auto_contents:
            files.append(f"auto/{item['name']}")

    return files


def get_file_content(full_name, path, branch):
    """Fetch a file's content from GitHub."""
    url = (
        f"repos/{full_name}/contents/{path}"
        f"?ref={branch}"
    )
    data = gh_api(url)
    if not data or "content" not in data:
        return None
    try:
        return base64.b64decode(
            data["content"]
        ).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return None


def detect_build_system(files):
    """Detect the build system from the file list."""
    for indicator, system in BUILD_SYSTEM_INDICATORS:
        if indicator in files:
            return system
    return "unknown"


def detect_configure_flags(full_name, branch, build_system, files):
    """Inspect configure.ac or CMakeLists.txt to detect optional dependencies."""
    flags = []
    apt_packages = []

    if build_system == "autoconf" and "configure.ac" in files:
        content = get_file_content(
            full_name, "configure.ac", branch
        )
        if content:
            content_lower = content.lower()
            for dep_name, dep_info in KNOWN_DEPENDENCIES.items():
                if (dep_name.lower() in content_lower
                        and dep_info["configure_flag"]):
                    flags.append(dep_info["configure_flag"])
                    apt_packages.extend(dep_info["apt_packages"])

    elif build_system == "cmake" and "CMakeLists.txt" in files:
        content = get_file_content(
            full_name, "CMakeLists.txt", branch
        )
        if content:
            content_lower = content.lower()
            for dep_name, dep_info in KNOWN_DEPENDENCIES.items():
                if (dep_name.lower() in content_lower
                        and dep_info["cmake_flag"]):
                    flags.append(dep_info["cmake_flag"])
                    apt_packages.extend(dep_info["apt_packages"])

    elif (build_system == "configure-only"
          and "configure" in files):
        content = get_file_content(
            full_name, "configure", branch
        )
        if content:
            content_lower = content.lower()
            for dep_name, dep_info in KNOWN_DEPENDENCIES.items():
                if (dep_name.lower() in content_lower
                        and dep_info["configure_flag"]):
                    flags.append(dep_info["configure_flag"])
                    apt_packages.extend(dep_info["apt_packages"])

    return flags, list(set(apt_packages))


def detect_output_binaries(
    full_name, repo_name, build_system, files
):
    """Guess the output binary paths based on repo structure and build system."""
    binaries = []

    # Check for Makefile.am or Makefile to find bin_PROGRAMS / lib_LTLIBRARIES
    makefiles = ["Makefile.am", "src/Makefile.am"]
    for mf in makefiles:
        if mf in files:
            content = get_file_content(
                full_name, mf, "HEAD"
            )
            if content:
                pat_bin = r'bin_PROGRAMS\s*[+=]\s*(.+)'
                for m in re.findall(pat_bin, content):
                    for prog in m.split():
                        binaries.append(prog.strip())
                pat_lib = (
                    r'lib_LTLIBRARIES\s*[+=]\s*(.+)'
                )
                for m in re.findall(pat_lib, content):
                    for lib in m.split():
                        lib_name = lib.strip().replace(
                            ".la", ".so"
                        )
                        binaries.append(
                            f"lib/.libs/{lib_name}"
                        )

    # Fallback: common patterns
    if not binaries:
        # Check if there's a src/ directory with the repo name
        if any(f.startswith("src/") for f in files):
            binaries.append(f"src/.libs/{repo_name}")
            binaries.append(f"src/{repo_name}")
        else:
            binaries.append(repo_name)

    return binaries


def generate_build_steps(build_system, configure_flags):
    """Generate build_steps based on build system and flags."""
    steps = []

    if build_system == "autoconf":
        steps.append("autoreconf -fi")
        configure_cmd = "./configure"
        if configure_flags:
            flags = " ".join(configure_flags)
            configure_cmd += " " + flags
        steps.append(configure_cmd)
        steps.append("make -j$(nproc)")

    elif build_system == "cmake":
        base = "mkdir -p build && cd build && cmake .."
        if configure_flags:
            flags = " ".join(configure_flags)
            base += " " + flags
        steps.append(base)
        steps.append("make -C build -j$(nproc)")

    elif build_system == "meson":
        steps.append("meson setup build")
        steps.append("ninja -C build")

    elif build_system == "perl-configure":
        steps.append("./config")
        steps.append("make -j$(nproc)")

    elif build_system == "auto-configure":
        steps.append("auto/configure")
        steps.append("make -j$(nproc)")

    elif build_system == "configure-only":
        configure_cmd = "./configure"
        if configure_flags:
            configure_cmd += " " + " ".join(configure_flags)
        steps.append(configure_cmd)
        steps.append("make -j$(nproc)")

    elif build_system == "make-only":
        steps.append("make -j$(nproc)")

    else:
        steps.append(
            "# TODO: determine build steps manually"
        )
        steps.append("make -j$(nproc)")

    return steps


def get_repo_stats(full_name):
    """Get lines of code estimate from GitHub API."""
    data = gh_api(f"repos/{full_name}/languages")
    if not data:
        return ""
    total_bytes = sum(data.values())
    # Rough estimate: 40 bytes per line
    loc_k = total_bytes / 40 / 1000
    top_langs = sorted(
        data.items(), key=lambda x: x[1], reverse=True
    )[:3]
    lang_str = ", ".join(lang for lang, _ in top_langs)
    return f"~{loc_k:.0f}K LoC, {lang_str}"


def generate_config_entry(
    repo_name, repo_info, build_system,
    build_steps, output_binaries, description
):
    """Generate the YAML config entry as a dict."""
    return {
        "url": (
            f"https://github.com/"
            f"{repo_info['fullName']}.git"
        ),
        "branch": repo_info["defaultBranch"],
        "build_steps": build_steps,
        "clean_cmd": "make clean",
        "description": description,
        "output_binaries": output_binaries,
    }


def write_config_entry(repo_name, entry):
    """Append the repo entry to config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if repo_name in config.get("repos", {}):
        print(
            f"[WARN] '{repo_name}' already in "
            "config.yaml — overwriting"
        )

    config["repos"][repo_name] = entry

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(
            config, f,
            default_flow_style=False,
            sort_keys=False, width=120
        )

    print(f"[OK] Written to {config_path}")


def create_output_dirs(repo_name):
    """Create the output directory structure for the repo."""
    base = Path(__file__).parent.parent
    dirs = [
        base / "output" / "omnibor" / repo_name,
        base / "output" / "spdx" / repo_name,
        base / "output" / "binary-scan" / repo_name,
        base / "docs" / repo_name,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  [DIR] {d}")


def main():
    parser = argparse.ArgumentParser(
        description="OmniBOR — Smart repo discovery and config generation"
    )
    parser.add_argument(
        "repo",
        help=(
            "Repo name (e.g., 'curl'), "
            "owner/repo, or full GitHub URL"
        )
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Write the entry to config.yaml"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show generated config without writing"
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  OmniBOR — Add Repository: {args.repo}")
    print(f"{'='*60}\n")

    # Step 1: Find the repo on GitHub
    print("[1/6] Searching GitHub...")
    repo_info = get_repo_info(args.repo)
    if not repo_info:
        print(f"[ERROR] Could not find repository for '{args.repo}'")
        sys.exit(1)

    full_name = repo_info["fullName"]
    branch = repo_info["defaultBranch"]
    repo_name = full_name.split("/")[-1].lower()
    stars = repo_info.get('stargazersCount', '?')
    print(f"  Found: {full_name} ({stars} stars)")
    print(f"  Branch: {branch}")
    lang = repo_info.get('language', 'unknown')
    desc = repo_info.get('description', 'N/A')
    print(f"  Language: {lang}")
    print(f"  Description: {desc}")

    # Step 2: Get file tree
    print("\n[2/6] Inspecting repository contents...")
    files = get_repo_tree(full_name, branch)
    if not files:
        print("[ERROR] Could not read repository file tree")
        sys.exit(1)
    print(
        f"  Found {len(files)} files in "
        "top-level + src/ + lib/"
    )

    # Step 3: Detect build system
    print("\n[3/6] Detecting build system...")
    build_system = detect_build_system(files)
    print(f"  Build system: {build_system}")

    # Step 4: Detect configure flags and dependencies
    print("\n[4/6] Analyzing dependencies...")
    configure_flags, apt_packages = detect_configure_flags(
        full_name, branch, build_system, files
    )
    if configure_flags:
        flags_str = ' '.join(configure_flags)
        print(f"  Configure flags: {flags_str}")
    else:
        print("  No optional dependency flags detected")
    if apt_packages:
        pkgs_str = ', '.join(sorted(apt_packages))
        print(f"  Required apt packages: {pkgs_str}")

    # Step 5: Detect output binaries
    print("\n[5/6] Identifying output binaries...")
    output_binaries = detect_output_binaries(
        full_name, repo_name, build_system, files
    )
    for b in output_binaries:
        print(f"  - {b}")

    # Step 6: Generate config
    print("\n[6/6] Generating config entry...")
    stats = get_repo_stats(full_name)
    desc_parts = []
    if repo_info.get("description"):
        # Truncate long descriptions
        desc = repo_info["description"]
        if len(desc) > 60:
            desc = desc[:57] + "..."
        desc_parts.append(desc)
    if stats:
        desc_parts.append(f"({stats})")
    description = " ".join(desc_parts) if desc_parts else repo_name

    build_steps = generate_build_steps(build_system, configure_flags)
    entry = generate_config_entry(
        repo_name, repo_info, build_system,
        build_steps, output_binaries, description
    )

    # Display the generated YAML
    sep = '=' * 60
    print(f"\n{sep}")
    print(
        f"  Generated config.yaml entry for "
        f"'{repo_name}':"
    )
    print(f"{sep}\n")
    yaml_str = yaml.dump(
        {repo_name: entry},
        default_flow_style=False,
        sort_keys=False, width=120
    )
    print(yaml_str)

    if apt_packages:
        print(f"{sep}")
        print("  Required Dockerfile additions:")
        print(f"{sep}\n")
        # Check which packages are already in the Dockerfile
        dockerfile_path = (
            Path(__file__).parent.parent
            / "docker" / "Dockerfile"
        )
        existing_pkgs = set()
        if dockerfile_path.exists():
            df_content = dockerfile_path.read_text()
            for pkg in apt_packages:
                if pkg in df_content:
                    existing_pkgs.add(pkg)

        new_pkgs = [
            p for p in sorted(apt_packages)
            if p not in existing_pkgs
        ]
        if new_pkgs:
            print(
                "  Add to docker/Dockerfile "
                "apt-get install:"
            )
            for pkg in new_pkgs:
                print(f"    {pkg}")
            installed = (
                ', '.join(sorted(existing_pkgs))
                or 'none'
            )
            print(
                f"\n  Already installed: {installed}"
            )
        else:
            print(
                "  All required packages already "
                "in Dockerfile"
            )

    if args.write:
        print("\n[WRITE] Writing to config.yaml...")
        write_config_entry(repo_name, entry)
        print("\n[WRITE] Creating output dirs...")
        create_output_dirs(repo_name)
        print(
            f"\n[DONE] '{repo_name}' is ready. Run:"
        )
        print(
            f"  python3 app/analyze.py "
            f"--repo {repo_name}"
        )
    else:
        print(
            "\n[DRY-RUN] No changes written. "
            "Use --write to save to config.yaml"
        )


if __name__ == "__main__":
    main()
