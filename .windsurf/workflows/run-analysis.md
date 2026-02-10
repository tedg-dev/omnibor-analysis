---
description: Run OmniBOR build interception analysis on a target repository
---

# Run Analysis

Instrument a C/C++ build with bomtrace3 and generate OmniBOR ADG + SPDX SBOM.

## Prerequisites

- Docker image must be built (run `/docker-build` workflow first)
- Target repo must be defined in `app/config.yaml`

## 1. List available repos

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --list
```

## 2. Run full analysis (clone + build + SBOM)

For curl:
```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo curl
```

For FFmpeg:
```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo ffmpeg
```

## 3. Re-run without cloning (repo already exists)

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo curl --skip-clone
```

## 4. Generate only a Syft manifest SBOM (no build)

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo curl --syft-only
```

## What happens during analysis

1. **Clone** — shallow clone of the target repo into `repos/<name>/`
2. **Syft baseline** — generates a manifest-based SPDX SBOM for comparison
3. **Pre-build** — runs autoreconf, configure (NOT instrumented)
4. **Instrumented build** — runs `bomtrace3 make` to intercept compiler/linker calls
5. **ADG generation** — `bomsh_create_bom.py` processes the raw logfile into OmniBOR ADG
6. **SPDX generation** — `bomsh_sbom.py` creates SPDX SBOM from ADG data
7. **Docs** — timestamped build log and runtime metrics written to `docs/<repo>/`

## Output locations

| Artifact | Path |
|----------|------|
| OmniBOR ADG | `output/omnibor/<repo>/` |
| SPDX SBOM (OmniBOR) | `output/spdx/<repo>/<repo>_omnibor_<timestamp>.spdx.json` |
| SPDX SBOM (Syft) | `output/spdx/<repo>/<repo>_syft_<timestamp>.spdx.json` |
| Build log | `docs/<repo>/<timestamp>_build.md` |
| Runtime metrics | `docs/runtime/<timestamp>_<repo>_runtime.md` |
