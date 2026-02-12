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

Classes:

    - GitHubClient: encapsulates all gh CLI / GitHub API calls
    - BuildSystemDetector: detects build system from file list
    - DependencyAnalyzer: inspects config files for dependency flags
    - BinaryDetector: detects output binaries from Makefiles
    - BuildStepGenerator: generates build commands per build system
    - ConfigGenerator: generates and writes config.yaml entries
    - RepoDiscovery: facade orchestrating the full pipeline
"""

import argparse
import base64
import json
import re
import subprocess
import sys
import yaml
from pathlib import Path

from data_loader import DataLoader


# ============================================================
# GitHub API client
# ============================================================

class GitHubClient:
    """Encapsulates all GitHub API interactions via gh CLI."""

    def api(self, endpoint):
        """Call the GitHub API via gh CLI. Returns parsed JSON."""
        result = subprocess.run(
            ["gh", "api", endpoint, "--paginate"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    def search_repos(self, query):
        """Search GitHub for repos by name. Returns top result."""
        fields = (
            "fullName,description,url,"
            "stargazersCount,defaultBranch,language"
        )
        result = subprocess.run(
            [
                "gh", "search", "repos", query,
                "--limit", "5", "--json", fields,
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(
                "[ERROR] gh search failed: "
                f"{result.stderr.strip()}"
            )
            return None
        try:
            repos = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

        if not repos:
            print(
                "[ERROR] No repositories found "
                f"for '{query}'"
            )
            return None

        c_langs = ("c", "c++", "")
        c_repos = [
            r for r in repos
            if r.get(
                "language", ""
            ).lower() in c_langs
        ]
        candidates = c_repos if c_repos else repos

        for r in candidates:
            name = (
                r["fullName"].split("/")[-1].lower()
            )
            if name == query.lower():
                return r

        return sorted(
            candidates,
            key=lambda r: r.get(
                "stargazersCount", 0
            ),
            reverse=True,
        )[0]

    def get_repo_info(self, name_or_url):
        """Get repository info. Accepts name, owner/repo, or URL."""
        full_name = self.parse_github_url(
            name_or_url
        )

        if full_name:
            data = self.api(f"repos/{full_name}")
            if data:
                return self._normalize(data)
        elif "/" in name_or_url:
            data = self.api(f"repos/{name_or_url}")
            if data:
                return self._normalize(data)

        return self.search_repos(name_or_url)

    def get_file_tree(self, full_name, branch):
        """Get the file tree (top-level + src/ + lib/ + auto/)."""
        contents = self.api(
            f"repos/{full_name}"
            f"/contents?ref={branch}"
        )
        if not contents:
            return []

        files = [item["name"] for item in contents]

        for subdir in ("src", "lib", "auto"):
            url = (
                f"repos/{full_name}"
                f"/contents/{subdir}"
                f"?ref={branch}"
            )
            sub = self.api(url)
            if sub and isinstance(sub, list):
                for item in sub:
                    files.append(
                        f"{subdir}/{item['name']}"
                    )

        return files

    def get_file_content(
        self, full_name, path, branch
    ):
        """Fetch a file's content (base64-decoded)."""
        url = (
            f"repos/{full_name}/contents/{path}"
            f"?ref={branch}"
        )
        data = self.api(url)
        if not data or "content" not in data:
            return None
        try:
            return base64.b64decode(
                data["content"]
            ).decode("utf-8", errors="replace")
        except (ValueError, UnicodeDecodeError):
            return None

    def get_languages(self, full_name):
        """Get language byte counts from GitHub API."""
        return self.api(
            f"repos/{full_name}/languages"
        )

    @staticmethod
    def parse_github_url(url_or_name):
        """Parse a GitHub URL into owner/repo, or return None."""
        match = re.search(
            r"github\.com[:/]([^/]+)/([^/.]+)",
            url_or_name,
        )
        if match:
            return (
                f"{match.group(1)}/{match.group(2)}"
            )
        return None

    @staticmethod
    def _normalize(data):
        """Convert GitHub API repo response to info dict."""
        return {
            "fullName": data["full_name"],
            "description": data.get(
                "description", ""
            ),
            "url": data["html_url"],
            "stargazersCount": data.get(
                "stargazers_count", 0
            ),
            "defaultBranch": data.get(
                "default_branch", "main"
            ),
            "language": data.get("language", ""),
        }


# ============================================================
# Build system detection
# ============================================================

class BuildSystemDetector:
    """Detects the build system from a repository's file list."""

    def __init__(self, indicators=None):
        self.indicators = indicators or []

    def detect(self, files):
        """Return the build system name for the given file list."""
        for indicator, system in self.indicators:
            if indicator in files:
                return system
        return "unknown"


# ============================================================
# Dependency analysis
# ============================================================

class DependencyAnalyzer:
    """Inspects build config files to detect optional dependencies."""

    _CONFIG_FILES = {
        "autoconf": (
            "configure.ac", "configure_flag"
        ),
        "cmake": (
            "CMakeLists.txt", "cmake_flag"
        ),
        "configure-only": (
            "configure", "configure_flag"
        ),
    }

    def __init__(self, known_deps=None, github=None):
        self.known_deps = known_deps or {}
        self.github = github or GitHubClient()

    def analyze(
        self, full_name, branch,
        build_system, files,
    ):
        """Detect configure flags and apt packages.

        Returns (flags, apt_packages) tuple.
        """
        config = self._CONFIG_FILES.get(
            build_system
        )
        if config is None:
            return [], []

        config_file, flag_key = config
        if config_file not in files:
            return [], []

        content = self.github.get_file_content(
            full_name, config_file, branch
        )
        if not content:
            return [], []

        flags = []
        apt_packages = []
        content_lower = content.lower()

        for dep_name, dep_info in (
            self.known_deps.items()
        ):
            flag = dep_info.get(flag_key, "")
            if (
                dep_name.lower() in content_lower
                and flag
            ):
                flags.append(flag)
                apt_packages.extend(
                    dep_info.get("apt_packages", [])
                )

        return flags, list(set(apt_packages))


# ============================================================
# Output binary detection
# ============================================================

class BinaryDetector:
    """Detects output binary paths from Makefiles and repo structure."""

    def __init__(self, github=None):
        self.github = github or GitHubClient()

    def detect(
        self, full_name, repo_name,
        build_system, files,
    ):
        """Guess the output binary paths."""
        binaries = []

        makefiles = [
            "Makefile.am", "src/Makefile.am",
        ]
        for mf in makefiles:
            if mf in files:
                content = (
                    self.github.get_file_content(
                        full_name, mf, "HEAD"
                    )
                )
                if content:
                    binaries.extend(
                        self._parse_makefile(content)
                    )

        if not binaries:
            binaries = self._fallback(
                repo_name, files
            )

        return binaries

    @staticmethod
    def _parse_makefile(content):
        """Extract binaries from Makefile.am content."""
        binaries = []
        pat_bin = r'bin_PROGRAMS\s*[+=]\s*(.+)'
        for m in re.findall(pat_bin, content):
            for prog in m.split():
                binaries.append(prog.strip())

        pat_lib = r'lib_LTLIBRARIES\s*[+=]\s*(.+)'
        for m in re.findall(pat_lib, content):
            for lib in m.split():
                lib_name = lib.strip().replace(
                    ".la", ".so"
                )
                binaries.append(
                    f"lib/.libs/{lib_name}"
                )
        return binaries

    @staticmethod
    def _fallback(repo_name, files):
        """Fallback binary detection from repo structure."""
        if any(f.startswith("src/") for f in files):
            return [
                f"src/.libs/{repo_name}",
                f"src/{repo_name}",
            ]
        return [repo_name]


# ============================================================
# Build step generation
# ============================================================

class BuildStepGenerator:
    """Generates build commands based on build system type."""

    _RECIPES = {
        "autoconf": "_autoconf",
        "cmake": "_cmake",
        "meson": "_meson",
        "perl-configure": "_perl_configure",
        "auto-configure": "_auto_configure",
        "configure-only": "_configure_only",
        "make-only": "_make_only",
    }

    def generate(self, build_system, flags):
        """Return a list of shell commands to build."""
        method_name = self._RECIPES.get(
            build_system
        )
        if method_name:
            method = getattr(self, method_name)
            return method(flags)
        return self._unknown(flags)

    @staticmethod
    def _autoconf(flags):
        steps = ["autoreconf -fi"]
        cmd = "./configure"
        if flags:
            cmd += " " + " ".join(flags)
        steps.append(cmd)
        steps.append("make -j$(nproc)")
        return steps

    @staticmethod
    def _cmake(flags):
        base = (
            "mkdir -p build && cd build && cmake .."
        )
        if flags:
            base += " " + " ".join(flags)
        return [base, "make -C build -j$(nproc)"]

    @staticmethod
    def _meson(_flags):
        return [
            "meson setup build",
            "ninja -C build",
        ]

    @staticmethod
    def _perl_configure(_flags):
        return ["./config", "make -j$(nproc)"]

    @staticmethod
    def _auto_configure(_flags):
        return ["auto/configure", "make -j$(nproc)"]

    @staticmethod
    def _configure_only(flags):
        cmd = "./configure"
        if flags:
            cmd += " " + " ".join(flags)
        return [cmd, "make -j$(nproc)"]

    @staticmethod
    def _make_only(_flags):
        return ["make -j$(nproc)"]

    @staticmethod
    def _unknown(_flags):
        return [
            "# TODO: determine build steps manually",
            "make -j$(nproc)",
        ]


# ============================================================
# Config generation and persistence
# ============================================================

class ConfigGenerator:
    """Generates and writes config.yaml entries."""

    def __init__(self, config_path=None):
        self.config_path = config_path or (
            Path(__file__).parent / "config.yaml"
        )

    def generate_entry(
        self, repo_info, build_steps,
        output_binaries, description,
        apt_deps=None,
    ):
        """Generate the YAML config entry as a dict."""
        entry = {
            "url": (
                "https://github.com/"
                f"{repo_info['fullName']}.git"
            ),
            "branch": repo_info["defaultBranch"],
            "build_steps": build_steps,
            "clean_cmd": "make clean",
            "description": description,
            "output_binaries": output_binaries,
        }
        if apt_deps:
            entry["apt_deps"] = sorted(apt_deps)
        return entry

    def write_entry(self, repo_name, entry):
        """Append the repo entry to config.yaml."""
        with open(
            self.config_path, "r", encoding="utf-8"
        ) as f:
            config = yaml.safe_load(f)

        if repo_name in config.get("repos", {}):
            print(
                f"[WARN] '{repo_name}' already in "
                "config.yaml — overwriting"
            )

        config["repos"][repo_name] = entry

        with open(
            self.config_path, "w", encoding="utf-8"
        ) as f:
            yaml.dump(
                config, f,
                default_flow_style=False,
                sort_keys=False, width=120,
            )

        print(
            f"[OK] Written to {self.config_path}"
        )

    @staticmethod
    def create_output_dirs(repo_name):
        """Create the output directory structure."""
        base = Path(__file__).parent.parent
        dirs = [
            base / "output" / "omnibor" / repo_name,
            base / "output" / "spdx" / repo_name,
            base / "output" / "binary-scan"
            / repo_name,
            base / "docs" / repo_name,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
            print(f"  [DIR] {d}")

    @staticmethod
    def get_repo_stats(full_name, github):
        """Get lines of code estimate from GitHub."""
        data = github.get_languages(full_name)
        if not data:
            return ""
        total_bytes = sum(data.values())
        loc_k = total_bytes / 40 / 1000
        top_langs = sorted(
            data.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        lang_str = ", ".join(
            lang for lang, _ in top_langs
        )
        return f"~{loc_k:.0f}K LoC, {lang_str}"


# ============================================================
# Facade: RepoDiscovery
# ============================================================

class RepoDiscovery:
    """Orchestrates the full repo discovery pipeline.

    Composes GitHubClient, BuildSystemDetector,
    DependencyAnalyzer, BinaryDetector,
    BuildStepGenerator, and ConfigGenerator.
    """

    def __init__(
        self,
        github=None,
        data_loader=None,
        detector=None,
        analyzer=None,
        binary_detector=None,
        step_generator=None,
        config_generator=None,
    ):
        self.github = github or GitHubClient()
        self.data = data_loader or DataLoader()

        indicators = self.data.load_build_systems()
        deps = self.data.load_dependencies()

        self.detector = detector or (
            BuildSystemDetector(indicators)
        )
        self.analyzer = analyzer or (
            DependencyAnalyzer(deps, self.github)
        )
        self.binary_detector = binary_detector or (
            BinaryDetector(self.github)
        )
        self.steps = step_generator or (
            BuildStepGenerator()
        )
        self.config = config_generator or (
            ConfigGenerator()
        )

    @staticmethod
    def build_description(
        repo_info, stats, repo_name
    ):
        """Build a description string from repo info."""
        desc_parts = []
        if repo_info.get("description"):
            desc = repo_info["description"]
            if len(desc) > 60:
                desc = desc[:57] + "..."
            desc_parts.append(desc)
        if stats:
            desc_parts.append(f"({stats})")
        return (
            " ".join(desc_parts)
            if desc_parts
            else repo_name
        )


# ============================================================
# CLI entry point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "OmniBOR — Smart repo discovery "
            "and config generation"
        )
    )
    parser.add_argument(
        "repo",
        help=(
            "Repo name (e.g., 'curl'), "
            "owner/repo, or full GitHub URL"
        ),
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Write the entry to config.yaml",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show generated config without writing",
    )
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(
        f"  OmniBOR — Add Repository: {args.repo}"
    )
    print(f"{'='*60}\n")

    discovery = RepoDiscovery()

    # Step 1: Find repo
    print("[1/6] Searching GitHub...")
    repo_info = discovery.github.get_repo_info(
        args.repo
    )
    if not repo_info:
        print(
            "[ERROR] Could not find repository "
            f"for '{args.repo}'"
        )
        sys.exit(1)

    full_name = repo_info["fullName"]
    branch = repo_info["defaultBranch"]
    repo_name = full_name.split("/")[-1].lower()
    stars = repo_info.get("stargazersCount", "?")
    print(f"  Found: {full_name} ({stars} stars)")
    print(f"  Branch: {branch}")
    lang = repo_info.get("language", "unknown")
    desc = repo_info.get("description", "N/A")
    print(f"  Language: {lang}")
    print(f"  Description: {desc}")

    # Step 2: File tree
    print("\n[2/6] Inspecting repository contents...")
    files = discovery.github.get_file_tree(
        full_name, branch
    )
    if not files:
        print(
            "[ERROR] Could not read repository "
            "file tree"
        )
        sys.exit(1)
    print(
        f"  Found {len(files)} files in "
        "top-level + src/ + lib/"
    )

    # Step 3: Build system
    print("\n[3/6] Detecting build system...")
    build_system = discovery.detector.detect(files)
    print(f"  Build system: {build_system}")

    # Step 4: Dependencies
    print("\n[4/6] Analyzing dependencies...")
    flags, apt_packages = (
        discovery.analyzer.analyze(
            full_name, branch, build_system, files
        )
    )
    if flags:
        flags_str = " ".join(flags)
        print(f"  Configure flags: {flags_str}")
    else:
        print(
            "  No optional dependency flags detected"
        )
    if apt_packages:
        pkgs_str = ", ".join(sorted(apt_packages))
        print(
            f"  Required apt packages: {pkgs_str}"
        )

    # Step 5: Binaries
    print("\n[5/6] Identifying output binaries...")
    binaries = discovery.binary_detector.detect(
        full_name, repo_name, build_system, files
    )
    for b in binaries:
        print(f"  - {b}")

    # Step 6: Config
    print("\n[6/6] Generating config entry...")
    stats = discovery.config.get_repo_stats(
        full_name, discovery.github
    )
    description = discovery.build_description(
        repo_info, stats, repo_name
    )
    build_steps = discovery.steps.generate(
        build_system, flags
    )
    entry = discovery.config.generate_entry(
        repo_info, build_steps,
        binaries, description,
        apt_deps=apt_packages,
    )

    # Display YAML
    sep = "=" * 60
    print(f"\n{sep}")
    print(
        f"  Generated config.yaml entry for "
        f"'{repo_name}':"
    )
    print(f"{sep}\n")
    yaml_str = yaml.dump(
        {repo_name: entry},
        default_flow_style=False,
        sort_keys=False, width=120,
    )
    print(yaml_str)

    if apt_packages:
        print(f"{sep}")
        print("  Required Dockerfile additions:")
        print(f"{sep}\n")
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
                ", ".join(sorted(existing_pkgs))
                or "none"
            )
            print(
                "\n  Already installed: "
                f"{installed}"
            )
        else:
            print(
                "  All required packages already "
                "in Dockerfile"
            )

    if args.write:
        print("\n[WRITE] Writing to config.yaml...")
        discovery.config.write_entry(
            repo_name, entry
        )
        print("\n[WRITE] Creating output dirs...")
        discovery.config.create_output_dirs(
            repo_name
        )
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
