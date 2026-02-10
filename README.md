# OmniBOR Analysis

> SBOM accuracy and consistency comparison using [OmniBOR](https://omnibor.io/) build interception vs. proprietary binary scanning.

[![License](https://img.shields.io/badge/license-TBD-lightgrey.svg)](#license)

## Table of Contents

- [Overview](#overview)
- [Background](#background)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Target Repositories](#target-repositories)
- [Output and Reports](#output-and-reports)
- [Contributing](#contributing)
- [License](#license)

## Overview

This project instruments C/C++ open-source builds with [OmniBOR/Bomsh](https://github.com/omnibor/bomsh) to generate SPDX SBOMs via **build interception**, then compares those SBOMs against SBOMs produced by proprietary binary scanning tools (e.g., BDBA) to evaluate:

- **Accuracy** — Are the detected components correct?
- **Completeness** — Are all components found?
- **Consistency** — Do both methods agree on versions and identifiers?

## Background

### What is Build Interception?

Build interception hooks into the compiler and linker during a software build to observe exactly which source files are compiled into which output artifacts. [OmniBOR's Bomtrace3](https://github.com/omnibor/bomsh) uses `strace` to intercept these calls and produce an **Artifact Dependency Graph (ADG)** — a cryptographically verifiable record of what was built from what.

### Why Compare Against Binary Scanning?

Binary scanning tools analyze compiled binaries using signature databases to identify known open-source components. By comparing build interception SBOMs against binary scan SBOMs, we can understand the strengths and blind spots of each approach and determine the most effective strategy for comprehensive SBOM generation.

## Project Structure

```
omnibor-analysis/
├── docker/                 Docker environment (Linux + gcc + bomtrace3)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── README.md
├── repos/                  Cloned target repositories (not tracked in git)
├── output/                 Raw SBOM and ADG artifacts (not tracked in git)
│   ├── omnibor/            ADG documents from bomsh
│   ├── spdx/               SPDX SBOMs (OmniBOR + Syft)
│   └── binary-scan/        SBOMs from proprietary binary scanner
├── docs/                   Timestamped results and reports
│   ├── <repo>/             Per-repo build logs, SBOM summaries, comparisons
│   ├── runtime/            Build time and performance metrics
│   └── summary/            Cross-repo findings and methodology
├── app/                    Orchestration scripts and configuration
│   ├── analyze.py          Clone, build, instrument, generate SBOMs
│   ├── compare.py          Diff OmniBOR SPDX vs binary-scan SPDX
│   ├── config.yaml         Repo definitions, build commands, paths
│   └── templates/          Report templates
├── .github/                GitHub templates and CI configuration
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── ISSUE_TEMPLATE/
├── CONTRIBUTING.md         Contribution guidelines
├── LICENSE                 License file
└── README.md               This file
```

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Docker Desktop** | Latest | Required — bomtrace3 runs on Linux only (uses strace) |
| **Python** | 3.11+ | For orchestration scripts |
| **Git** | 2.x+ | For cloning target repositories |
| **Binary scanner** | — | Optional — BDBA or equivalent for comparison SBOMs |

> **Note:** All C/C++ compilation and OmniBOR instrumentation happens inside the Docker container. You do **not** need gcc, clang, or any build tools installed on your host machine.

## Getting Started

### 1. Clone this repository

```bash
git clone https://github.com/tedg-cisco/omnibor-analysis.git
cd omnibor-analysis
```

### 2. Build the Docker environment

```bash
docker-compose -f docker/docker-compose.yml build
```

This builds an Ubuntu 22.04 container with:
- gcc, clang, make, cmake, autoconf
- bomtrace2 and bomtrace3 (compiled from [omnibor/bomsh](https://github.com/omnibor/bomsh))
- [Syft](https://github.com/anchore/syft) for manifest-based SBOM generation
- All build dependencies for target repositories (curl, FFmpeg)

First build takes **10-20 minutes** (compiles bomtrace from patched strace source). Subsequent builds use Docker layer cache.

### 3. Verify the environment

```bash
# Check bomtrace3
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bomtrace3 --version

# Check syft
docker-compose -f docker/docker-compose.yml run --rm omnibor-env syft version
```

## Usage

### Run analysis on a target repository

```bash
# List available repos
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --list

# Full analysis: clone → build → instrument → generate SBOMs → write docs
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo curl

# Re-run without cloning (repo already exists)
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo curl --skip-clone

# Syft-only mode (manifest SBOM, no build instrumentation)
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/analyze.py --repo curl --syft-only
```

### Compare SBOMs

After running analysis and placing a binary scanner SPDX file in `output/binary-scan/<repo>/`:

```bash
# Auto-detect latest files
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/compare.py --repo curl

# Or specify files explicitly
docker-compose -f docker/docker-compose.yml run --rm omnibor-env \
  python3 /workspace/app/compare.py --repo curl \
    --omnibor-file /workspace/output/spdx/curl/curl_omnibor_2026-02-10_1430.spdx.json \
    --binary-file /workspace/output/binary-scan/curl/bdba_export.spdx.json
```

### Interactive container access

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env bash
```

## Target Repositories

| Repo | Size | Dependencies | Build System | Purpose |
|------|------|-------------|-------------|---------|
| [curl](https://github.com/curl/curl) | ~170K LoC | OpenSSL, zlib, nghttp2, libssh2, brotli, zstd, c-ares, libidn2 | autoconf/make | Controlled medium-size comparison |
| [FFmpeg](https://github.com/FFmpeg/FFmpeg) | ~1.2M LoC | libx264, libx265, libvpx, libopus, OpenSSL, zlib, 20+ more | autoconf/make | Large-scale dependency-rich comparison |

To add a new target repository, see [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-new-target-repository).

## Output and Reports

### Artifacts (not tracked in git)

| Path | Contents |
|------|----------|
| `output/omnibor/<repo>/` | OmniBOR Artifact Dependency Graph (ADG) documents |
| `output/spdx/<repo>/` | SPDX SBOM files (from OmniBOR and Syft) |
| `output/binary-scan/<repo>/` | SPDX SBOM files from proprietary binary scanner |

### Reports (tracked in git)

| Path | Contents |
|------|----------|
| `docs/<repo>/<timestamp>_build.md` | Build log, environment snapshot |
| `docs/<repo>/<timestamp>_comparison.md` | Side-by-side SBOM comparison |
| `docs/runtime/<timestamp>_<repo>_runtime.md` | Build time and bomtrace3 overhead metrics |
| `docs/summary/` | Cross-repo findings and methodology |

**Naming convention:** `YYYY-MM-DD_HHMM_<type>.md`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:
- Branch naming and PR workflow
- Adding new target repositories
- Code style and testing
- Commit message conventions

## License

TBD — License to be determined.

---

*Built with [OmniBOR/Bomsh](https://github.com/omnibor/bomsh) | [omnibor.io](https://omnibor.io)*
