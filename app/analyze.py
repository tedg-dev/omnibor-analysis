#!/usr/bin/env python3
"""
OmniBOR Analysis — Main orchestration script.

Clones a target repository, instruments the build with bomtrace3,
generates OmniBOR ADG documents and SPDX SBOMs, and produces
timestamped markdown reports.

Usage:

    python3 analyze.py --repo curl
    python3 analyze.py --repo ffmpeg
    python3 analyze.py --repo curl --skip-clone
    python3 analyze.py --list

Classes:

    - CommandRunner: wraps subprocess execution with logging
    - RepoCloner: handles git clone logic
    - BomtraceBuilder: instrumented build with bomtrace3
    - SpdxGenerator: generates SPDX SBOM from OmniBOR data
    - SyftGenerator: generates baseline manifest SBOM via Syft
    - DocWriter: writes build logs and runtime metrics
    - AnalysisPipeline: facade orchestrating the full workflow
"""

import argparse
import os
import subprocess
import sys
import time
import yaml
from datetime import datetime
from pathlib import Path


# ============================================================
# Utilities
# ============================================================

def load_config(config_path=None):
    """Load config.yaml from the given path or script directory."""
    if config_path is None:
        config_path = (
            Path(__file__).parent / "config.yaml"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def timestamp():
    """Return current timestamp in configured format."""
    return datetime.now().strftime("%Y-%m-%d_%H%M")


# ============================================================
# Command execution
# ============================================================

class CommandRunner:
    """Wraps subprocess execution with logging."""

    def run(self, cmd, cwd=None, description=""):
        """Run a shell command, print output, return exit code."""
        print(f"\n{'='*60}")
        print(f"  {description}")
        print(f"  CMD: {cmd}")
        print(f"  CWD: {cwd or os.getcwd()}")
        print(f"{'='*60}\n")
        result = subprocess.run(
            cmd, shell=True, cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(
                "[ERROR] Command exited with "
                f"code {result.returncode}"
            )
        return result.returncode


# ============================================================
# Repository cloning
# ============================================================

class RepoCloner:
    """Handles git clone logic."""

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def clone(self, repo_name, repo_cfg, paths_cfg):
        """Clone the target repository if not already present."""
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        if repo_dir.exists() and any(
            repo_dir.iterdir()
        ):
            print(
                "[INFO] Repository already exists "
                f"at {repo_dir}, skipping clone."
            )
            return str(repo_dir)

        url = repo_cfg["url"]
        branch = repo_cfg.get("branch", "master")
        self.runner.run(
            f"git clone --depth 1 "
            f"--branch {branch} {url} {repo_dir}",
            description=(
                f"Cloning {repo_name} ({branch})"
            ),
        )
        return str(repo_dir)


# ============================================================
# Bomtrace3 instrumented build
# ============================================================

class BomtraceBuilder:
    """Instruments the build with bomtrace3 and generates OmniBOR ADG."""

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def build(
        self, repo_name, repo_cfg,
        paths_cfg, omnibor_cfg,
    ):
        """Run pre-build steps, instrumented build, and ADG generation.

        Returns True on success, False on failure.
        """
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "omnibor" / repo_name
        )
        tracer = omnibor_cfg["tracer"]
        raw_logfile = omnibor_cfg["raw_logfile"]

        # Pre-build steps (configure, etc.)
        build_steps = repo_cfg["build_steps"]
        for step in build_steps[:-1]:
            rc = self.runner.run(
                step, cwd=str(repo_dir),
                description=(
                    f"Pre-build: {step[:60]}"
                ),
            )
            if rc != 0:
                print(
                    "[ERROR] Pre-build step "
                    f"failed: {step}"
                )
                return False

        # Final build step with bomtrace3
        make_cmd = build_steps[-1]
        instrumented = f"{tracer} {make_cmd}"
        rc = self.runner.run(
            instrumented, cwd=str(repo_dir),
            description=(
                f"Instrumented build: "
                f"{tracer} {make_cmd[:40]}"
            ),
        )
        if rc != 0:
            print("[ERROR] Instrumented build failed")
            return False

        # Generate OmniBOR ADG documents
        create_bom = omnibor_cfg["create_bom_script"]
        rc = self.runner.run(
            f"{create_bom} -r {raw_logfile} "
            f"-b {bom_dir}",
            cwd=str(repo_dir),
            description=(
                "Generating OmniBOR ADG documents"
            ),
        )
        if rc != 0:
            print("[ERROR] ADG generation failed")
            return False

        print(
            "[OK] OmniBOR ADG documents "
            f"written to {bom_dir}"
        )
        return True


# ============================================================
# SPDX generation
# ============================================================

class SpdxGenerator:
    """Generates SPDX SBOM from OmniBOR data."""

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def generate(
        self, repo_name, paths_cfg, omnibor_cfg
    ):
        """Generate SPDX SBOM. Returns output file path."""
        bom_dir = (
            Path(paths_cfg["output_dir"])
            / "omnibor" / repo_name
        )
        spdx_dir = (
            Path(paths_cfg["output_dir"])
            / "spdx" / repo_name
        )
        spdx_dir.mkdir(parents=True, exist_ok=True)

        sbom_script = omnibor_cfg["sbom_script"]
        raw_logfile = omnibor_cfg["raw_logfile"]
        ts = timestamp()
        spdx_file = (
            spdx_dir
            / f"{repo_name}_omnibor_{ts}.spdx.json"
        )

        rc = self.runner.run(
            f"{sbom_script} -r {raw_logfile} "
            f"-b {bom_dir} -o {spdx_file}",
            description=(
                "Generating SPDX SBOM: "
                f"{spdx_file.name}"
            ),
        )
        if rc != 0:
            print(
                "[WARN] SPDX generation may have "
                "failed — check output"
            )
        return str(spdx_file)


# ============================================================
# Syft baseline SBOM
# ============================================================

class SyftGenerator:
    """Generates a baseline manifest SBOM using Syft."""

    def __init__(self, runner=None):
        self.runner = runner or CommandRunner()

    def generate(self, repo_name, paths_cfg):
        """Generate Syft SBOM. Returns output file path."""
        repo_dir = (
            Path(paths_cfg["repos_dir"]) / repo_name
        )
        spdx_dir = (
            Path(paths_cfg["output_dir"])
            / "spdx" / repo_name
        )
        spdx_dir.mkdir(parents=True, exist_ok=True)

        ts = timestamp()
        spdx_file = (
            spdx_dir
            / f"{repo_name}_syft_{ts}.spdx.json"
        )

        rc = self.runner.run(
            f"syft dir:{repo_dir} "
            f"-o spdx-json={spdx_file}",
            description=(
                "Generating Syft manifest SBOM: "
                f"{spdx_file.name}"
            ),
        )
        if rc != 0:
            print(
                "[WARN] Syft SBOM generation "
                "may have failed"
            )
        return str(spdx_file)


# ============================================================
# Documentation writer
# ============================================================

class DocWriter:
    """Writes build logs and runtime metrics."""

    @staticmethod
    def write_build_doc(
        repo_name, repo_cfg,
        paths_cfg, success, duration_sec,
    ):
        """Write a timestamped build log to docs/<repo>/."""
        docs_dir = (
            Path(paths_cfg["docs_dir"]) / repo_name
        )
        docs_dir.mkdir(parents=True, exist_ok=True)
        ts = timestamp()
        doc_path = docs_dir / f"{ts}_build.md"

        status = "SUCCESS" if success else "FAILED"
        content = (
            f"# Build Log — {repo_name}\n\n"
            f"**Date:** {datetime.now().isoformat()}\n"
            f"**Status:** {status}\n"
            f"**Duration:** {duration_sec:.1f}"
            " seconds\n\n"
            "## Repository\n\n"
            f"- **URL:** {repo_cfg['url']}\n"
            f"- **Branch:** "
            f"{repo_cfg.get('branch', 'master')}\n"
            f"- **Description:** "
            f"{repo_cfg.get('description', 'N/A')}"
            "\n\n"
            "## Build Steps\n\n"
        )
        for i, step in enumerate(
            repo_cfg["build_steps"], 1
        ):
            content += f"{i}. `{step}`\n"

        content += (
            "\n## Instrumentation\n\n"
            "- **Tracer:** bomtrace3\n"
            "- **Raw logfile:** "
            "/tmp/bomsh_hook_raw_logfile.sha1\n\n"
            "## Output Binaries\n\n"
        )
        for binary in repo_cfg.get(
            "output_binaries", []
        ):
            content += f"- `{binary}`\n"

        with open(
            doc_path, "w", encoding="utf-8"
        ) as f:
            f.write(content)

        print(f"[OK] Build doc written to {doc_path}")
        return str(doc_path)

    @staticmethod
    def write_runtime_doc(
        repo_name, paths_cfg,
        duration_sec, baseline_sec=None,
    ):
        """Write runtime performance metrics."""
        runtime_dir = (
            Path(paths_cfg["docs_dir"]) / "runtime"
        )
        runtime_dir.mkdir(
            parents=True, exist_ok=True
        )
        ts = timestamp()
        doc_path = (
            runtime_dir
            / f"{ts}_{repo_name}_runtime.md"
        )

        overhead_pct = ""
        if baseline_sec and baseline_sec > 0:
            pct = (
                (duration_sec - baseline_sec)
                / baseline_sec * 100
            )
            overhead_pct = (
                f"\n**Bomtrace3 overhead:** "
                f"{pct:.1f}%"
            )

        content = (
            f"# Runtime Metrics — {repo_name}\n\n"
            f"**Date:** "
            f"{datetime.now().isoformat()}\n"
            f"**Instrumented build time:** "
            f"{duration_sec:.1f} seconds\n"
            f"{overhead_pct}\n\n"
            "## Notes\n\n"
            "- Measured wall-clock time for the "
            "instrumented `make` step only\n"
            "- Baseline (uninstrumented) build time "
            "should be recorded separately "
            "for comparison\n"
        )

        with open(
            doc_path, "w", encoding="utf-8"
        ) as f:
            f.write(content)

        print(
            f"[OK] Runtime doc written to {doc_path}"
        )
        return str(doc_path)


# ============================================================
# Facade: AnalysisPipeline
# ============================================================

class AnalysisPipeline:
    """Orchestrates the full OmniBOR analysis workflow.

    Composes CommandRunner, RepoCloner, BomtraceBuilder,
    SpdxGenerator, SyftGenerator, and DocWriter.
    """

    def __init__(
        self,
        runner=None,
        cloner=None,
        builder=None,
        spdx_gen=None,
        syft_gen=None,
        doc_writer=None,
    ):
        self.runner = runner or CommandRunner()
        self.cloner = cloner or RepoCloner(
            self.runner
        )
        self.builder = builder or BomtraceBuilder(
            self.runner
        )
        self.spdx_gen = spdx_gen or SpdxGenerator(
            self.runner
        )
        self.syft_gen = syft_gen or SyftGenerator(
            self.runner
        )
        self.docs = doc_writer or DocWriter()

    @staticmethod
    def list_repos(config):
        """List available repositories from config."""
        print("\nAvailable repositories:\n")
        for name, cfg in config["repos"].items():
            desc = cfg.get(
                "description", "No description"
            )
            print(f"  {name:12s}  {desc}")
            print(f"               {cfg['url']}")
            print()


# ============================================================
# CLI entry point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "OmniBOR Analysis — Build interception "
            "and SBOM generation"
        )
    )
    parser.add_argument(
        "--repo",
        help="Repository name from config.yaml",
    )
    parser.add_argument(
        "--skip-clone", action="store_true",
        help="Skip cloning (repo already exists)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List available repositories",
    )
    parser.add_argument(
        "--syft-only", action="store_true",
        help=(
            "Only generate Syft manifest SBOM "
            "(no build)"
        ),
    )
    args = parser.parse_args()

    config = load_config()
    pipeline = AnalysisPipeline()

    if args.list:
        pipeline.list_repos(config)
        return

    if not args.repo:
        print(
            "[ERROR] --repo is required. "
            "Use --list to see options."
        )
        sys.exit(1)

    if args.repo not in config["repos"]:
        print(
            f"[ERROR] Unknown repo '{args.repo}'. "
            "Use --list to see options."
        )
        sys.exit(1)

    repo_cfg = config["repos"][args.repo]
    paths_cfg = config["paths"]
    omnibor_cfg = config["omnibor"]

    print(f"\n{'#'*60}")
    print(f"  OmniBOR Analysis: {args.repo}")
    desc = repo_cfg.get("description", "")
    print(f"  {desc}")
    print(f"{'#'*60}\n")

    # Step 1: Clone
    if not args.skip_clone:
        pipeline.cloner.clone(
            args.repo, repo_cfg, paths_cfg
        )

    # Step 2: Syft baseline SBOM
    pipeline.syft_gen.generate(
        args.repo, paths_cfg
    )

    if args.syft_only:
        print(
            "\n[DONE] Syft-only mode — "
            "skipping instrumented build."
        )
        return

    # Step 3: Instrumented build
    start = time.time()
    success = pipeline.builder.build(
        args.repo, repo_cfg,
        paths_cfg, omnibor_cfg,
    )
    duration = time.time() - start

    # Step 4: Generate SPDX from OmniBOR
    if success:
        pipeline.spdx_gen.generate(
            args.repo, paths_cfg, omnibor_cfg
        )

    # Step 5: Write docs
    pipeline.docs.write_build_doc(
        args.repo, repo_cfg, paths_cfg,
        success, duration,
    )
    pipeline.docs.write_runtime_doc(
        args.repo, paths_cfg, duration
    )

    status = "COMPLETE" if success else "FAILED"
    print(f"\n{'#'*60}")
    print(f"  Analysis {status}: {args.repo}")
    print(f"  Duration: {duration:.1f}s")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
