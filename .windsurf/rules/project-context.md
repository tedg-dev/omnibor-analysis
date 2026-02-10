---
description: Project context and architecture for omnibor-analysis
---

# Project: OmniBOR Analysis

This project instruments C/C++ open-source builds with OmniBOR/Bomsh (build interception)
to generate SPDX SBOMs, then compares those against SBOMs from proprietary binary scanning
tools (e.g., BDBA) to evaluate accuracy, completeness, and consistency.

## Architecture

- **docker/** — Linux container environment (Ubuntu 22.04) with gcc, clang, bomtrace3, syft
- **repos/** — Cloned target repositories (gitignored, not tracked)
- **output/** — Raw machine-readable artifacts (ADG, SPDX JSON, binary scan results)
- **docs/** — Timestamped human-readable markdown results, per-repo and cross-repo
- **app/** — Orchestration scripts (analyze.py, compare.py) and config.yaml

## Key Technologies

- **Bomsh/Bomtrace3** — strace-based build interception from omnibor/bomsh (Linux only)
- **OmniBOR** — Artifact Dependency Graph (ADG) standard (omnibor.io)
- **SPDX** — SBOM format (v2.3 supported by bomsh)
- **Syft** — Manifest-based SBOM generation (baseline comparison)
- **Docker** — Required because bomtrace uses strace (not available on macOS)

## Target Repositories

| Repo | URL | Size | Build System |
|------|-----|------|-------------|
| curl | https://github.com/curl/curl | ~170K LoC | autoconf/make |
| FFmpeg | https://github.com/FFmpeg/FFmpeg | ~1.2M LoC | autoconf/make |

## File Naming Convention

All docs use: `YYYY-MM-DD_HHMM_<type>.md`
Types: build, omnibor, spdx, binary-scan, comparison, runtime

## Important Constraints

- All builds and bomtrace instrumentation run inside the Docker container, never on macOS host
- The Docker container requires `SYS_PTRACE` capability and `seccomp:unconfined` for strace
- repos/ and output/ are gitignored — only docs/, app/, and docker/ are tracked
- config.yaml is the single source of truth for repo URLs, build commands, and paths
