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
"""

import argparse
import os
import subprocess
import sys
import yaml
from datetime import datetime
from pathlib import Path


def load_config():
    """Load config.yaml from the same directory as this script."""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def timestamp():
    """Return current timestamp in configured format."""
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def run_cmd(cmd, cwd=None, description=""):
    """Run a shell command, print output, return exit code."""
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"  CMD: {cmd}")
    print(f"  CWD: {cwd or os.getcwd()}")
    print(f"{'='*60}\n")
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"[ERROR] Command exited with code {result.returncode}")
    return result.returncode


def clone_repo(repo_name, repo_cfg, paths_cfg):
    """Clone the target repository if not already present."""
    repo_dir = Path(paths_cfg["repos_dir"]) / repo_name
    if repo_dir.exists() and any(repo_dir.iterdir()):
        print(f"[INFO] Repository already exists at {repo_dir}, skipping clone.")
        return str(repo_dir)

    url = repo_cfg["url"]
    branch = repo_cfg.get("branch", "master")
    run_cmd(
        f"git clone --depth 1 --branch {branch} {url} {repo_dir}",
        description=f"Cloning {repo_name} ({branch})"
    )
    return str(repo_dir)


def build_with_bomtrace(repo_name, repo_cfg, paths_cfg, omnibor_cfg):
    """Instrument the build with bomtrace3 and generate OmniBOR ADG."""
    repo_dir = Path(paths_cfg["repos_dir"]) / repo_name
    bom_dir = Path(paths_cfg["output_dir"]) / "omnibor" / repo_name
    tracer = omnibor_cfg["tracer"]
    raw_logfile = omnibor_cfg["raw_logfile"]

    # Run pre-build steps (configure, etc.) without instrumentation
    build_steps = repo_cfg["build_steps"]
    for step in build_steps[:-1]:
        rc = run_cmd(step, cwd=str(repo_dir), description=f"Pre-build: {step[:60]}")
        if rc != 0:
            print(f"[ERROR] Pre-build step failed: {step}")
            return False

    # Run the final build step (make) with bomtrace3 instrumentation
    make_cmd = build_steps[-1]
    instrumented_cmd = f"{tracer} {make_cmd}"
    rc = run_cmd(
        instrumented_cmd, cwd=str(repo_dir),
        description=f"Instrumented build: {tracer} {make_cmd[:40]}"
    )
    if rc != 0:
        print(f"[ERROR] Instrumented build failed")
        return False

    # Generate OmniBOR ADG documents
    create_bom = omnibor_cfg["create_bom_script"]
    rc = run_cmd(
        f"{create_bom} -r {raw_logfile} -b {bom_dir}",
        cwd=str(repo_dir),
        description="Generating OmniBOR ADG documents"
    )
    if rc != 0:
        print(f"[ERROR] ADG generation failed")
        return False

    print(f"[OK] OmniBOR ADG documents written to {bom_dir}")
    return True


def generate_spdx(repo_name, paths_cfg, omnibor_cfg):
    """Generate SPDX SBOM from OmniBOR data."""
    bom_dir = Path(paths_cfg["output_dir"]) / "omnibor" / repo_name
    spdx_dir = Path(paths_cfg["output_dir"]) / "spdx" / repo_name
    spdx_dir.mkdir(parents=True, exist_ok=True)

    sbom_script = omnibor_cfg["sbom_script"]
    raw_logfile = omnibor_cfg["raw_logfile"]
    ts = timestamp()
    spdx_file = spdx_dir / f"{repo_name}_omnibor_{ts}.spdx.json"

    rc = run_cmd(
        f"{sbom_script} -r {raw_logfile} -b {bom_dir} -o {spdx_file}",
        description=f"Generating SPDX SBOM: {spdx_file.name}"
    )
    if rc != 0:
        print(f"[WARN] SPDX generation may have failed — check output")
    return str(spdx_file)


def generate_syft_sbom(repo_name, paths_cfg):
    """Generate a baseline manifest SBOM using Syft."""
    repo_dir = Path(paths_cfg["repos_dir"]) / repo_name
    spdx_dir = Path(paths_cfg["output_dir"]) / "spdx" / repo_name
    spdx_dir.mkdir(parents=True, exist_ok=True)

    ts = timestamp()
    spdx_file = spdx_dir / f"{repo_name}_syft_{ts}.spdx.json"

    rc = run_cmd(
        f"syft dir:{repo_dir} -o spdx-json={spdx_file}",
        description=f"Generating Syft manifest SBOM: {spdx_file.name}"
    )
    if rc != 0:
        print(f"[WARN] Syft SBOM generation may have failed")
    return str(spdx_file)


def write_build_doc(repo_name, repo_cfg, paths_cfg, success, duration_sec):
    """Write a timestamped build log to docs/<repo>/."""
    docs_dir = Path(paths_cfg["docs_dir"]) / repo_name
    docs_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp()
    doc_path = docs_dir / f"{ts}_build.md"

    content = f"""# Build Log — {repo_name}

**Date:** {datetime.now().isoformat()}
**Status:** {"SUCCESS" if success else "FAILED"}
**Duration:** {duration_sec:.1f} seconds

## Repository

- **URL:** {repo_cfg['url']}
- **Branch:** {repo_cfg.get('branch', 'master')}
- **Description:** {repo_cfg.get('description', 'N/A')}

## Build Steps

"""
    for i, step in enumerate(repo_cfg["build_steps"], 1):
        content += f"{i}. `{step}`\n"

    content += f"""
## Instrumentation

- **Tracer:** bomtrace3
- **Raw logfile:** /tmp/bomsh_hook_raw_logfile.sha1

## Output Binaries

"""
    for binary in repo_cfg.get("output_binaries", []):
        content += f"- `{binary}`\n"

    with open(doc_path, "w") as f:
        f.write(content)

    print(f"[OK] Build doc written to {doc_path}")
    return str(doc_path)


def write_runtime_doc(repo_name, paths_cfg, duration_sec, baseline_sec=None):
    """Write runtime performance metrics."""
    runtime_dir = Path(paths_cfg["docs_dir"]) / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp()
    doc_path = runtime_dir / f"{ts}_{repo_name}_runtime.md"

    overhead_pct = ""
    if baseline_sec and baseline_sec > 0:
        pct = ((duration_sec - baseline_sec) / baseline_sec) * 100
        overhead_pct = f"\n**Bomtrace3 overhead:** {pct:.1f}%"

    content = f"""# Runtime Metrics — {repo_name}

**Date:** {datetime.now().isoformat()}
**Instrumented build time:** {duration_sec:.1f} seconds
{overhead_pct}

## Notes

- Measured wall-clock time for the instrumented `make` step only
- Baseline (uninstrumented) build time should be recorded separately for comparison
"""

    with open(doc_path, "w") as f:
        f.write(content)

    print(f"[OK] Runtime doc written to {doc_path}")


def list_repos(config):
    """List available repositories from config."""
    print("\nAvailable repositories:\n")
    for name, cfg in config["repos"].items():
        print(f"  {name:12s}  {cfg.get('description', 'No description')}")
        print(f"               {cfg['url']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="OmniBOR Analysis — Build interception and SBOM generation"
    )
    parser.add_argument("--repo", help="Repository name from config.yaml")
    parser.add_argument("--skip-clone", action="store_true",
                        help="Skip cloning (repo already exists)")
    parser.add_argument("--list", action="store_true",
                        help="List available repositories")
    parser.add_argument("--syft-only", action="store_true",
                        help="Only generate Syft manifest SBOM (no build)")
    args = parser.parse_args()

    config = load_config()

    if args.list:
        list_repos(config)
        return

    if not args.repo:
        print("[ERROR] --repo is required. Use --list to see options.")
        sys.exit(1)

    if args.repo not in config["repos"]:
        print(f"[ERROR] Unknown repo '{args.repo}'. Use --list to see options.")
        sys.exit(1)

    repo_cfg = config["repos"][args.repo]
    paths_cfg = config["paths"]
    omnibor_cfg = config["omnibor"]

    print(f"\n{'#'*60}")
    print(f"  OmniBOR Analysis: {args.repo}")
    print(f"  {repo_cfg.get('description', '')}")
    print(f"{'#'*60}\n")

    # Step 1: Clone
    if not args.skip_clone:
        clone_repo(args.repo, repo_cfg, paths_cfg)

    # Step 2: Syft baseline SBOM
    generate_syft_sbom(args.repo, paths_cfg)

    if args.syft_only:
        print("\n[DONE] Syft-only mode — skipping instrumented build.")
        return

    # Step 3: Instrumented build
    import time
    start = time.time()
    success = build_with_bomtrace(args.repo, repo_cfg, paths_cfg, omnibor_cfg)
    duration = time.time() - start

    # Step 4: Generate SPDX from OmniBOR
    if success:
        generate_spdx(args.repo, paths_cfg, omnibor_cfg)

    # Step 5: Write docs
    write_build_doc(args.repo, repo_cfg, paths_cfg, success, duration)
    write_runtime_doc(args.repo, paths_cfg, duration)

    status = "COMPLETE" if success else "FAILED"
    print(f"\n{'#'*60}")
    print(f"  Analysis {status}: {args.repo}")
    print(f"  Duration: {duration:.1f}s")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
