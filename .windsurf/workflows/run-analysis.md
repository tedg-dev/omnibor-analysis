---
description: Run OmniBOR build interception analysis on a target repository
---

# Run Analysis

Instrument a C/C++ build with bomtrace3 on the DigitalOcean droplet and
download results to local Mac.

## Prerequisites

- DigitalOcean droplet must be running (`ssh omnibor-build` must work)
- Docker image must be built on the droplet (run `/docker-build` workflow first)
- Target repo must be defined in `app/config.yaml`
- Latest code must be pushed and pulled on the droplet

## 1. Ensure droplet has latest code

```bash
ssh omnibor-build "cd /root/omnibor-analysis && git pull origin main"
```

## 2. Run full analysis on droplet

For curl:

```bash
ssh omnibor-build "cd /root/omnibor-analysis && docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo curl"
```

For FFmpeg:

```bash
ssh omnibor-build "cd /root/omnibor-analysis && docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo ffmpeg"
```

## 3. Re-run without cloning (repo already exists)

```bash
ssh omnibor-build "cd /root/omnibor-analysis && docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo curl --skip-clone"
```

## 4. Generate only a Syft manifest SBOM (no build)

```bash
ssh omnibor-build "cd /root/omnibor-analysis && docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo curl --syft-only"
```

## 5. Download output to local Mac

After analysis completes, sync the output and docs directories back:

```bash
rsync -avz omnibor-build:/root/omnibor-analysis/output/ output/
rsync -avz omnibor-build:/root/omnibor-analysis/docs/ docs/
```

This downloads:

- `output/binaries/<repo>/<timestamp>/` — compiled binaries (curl, libcurl.so, etc.)
- `output/omnibor/<repo>/` — OmniBOR ADG documents
- `output/spdx/<repo>/` — SPDX SBOMs (OmniBOR + Syft)
- `docs/<repo>/` — build logs
- `docs/runtime/` — runtime metrics

## What happens during analysis

1. **Clone** — shallow clone of the target repo
2. **Syft baseline** — manifest-based SPDX SBOM for comparison
3. **Validate deps** — checks `apt_deps` are installed
4. **Instrumented build** — `bomtrace3 make` intercepts compiler/linker calls
5. **SPDX generation** — `bomsh_sbom.py` creates SPDX SBOM from ADG data
6. **SPDX validation** — JSON Schema + semantic validation of generated SPDX
7. **Binary collection** — copies `output_binaries` to `output/binaries/<repo>/`
8. **Docs** — timestamped build log and runtime metrics

## Output locations (on droplet, mirrored locally after rsync)

| Artifact | Path |
|----------|------|
| Output binaries | `output/binaries/<repo>/<ts>/` |
| OmniBOR ADG | `output/omnibor/<repo>/` |
| SPDX SBOM (OmniBOR) | `output/spdx/<repo>/<repo>_omnibor_<ts>.spdx.json` |
| SPDX SBOM (Syft) | `output/spdx/<repo>/<repo>_syft_<ts>.spdx.json` |
| Build log | `docs/<repo>/<ts>_build.md` |
| Runtime metrics | `docs/runtime/<ts>_<repo>_runtime.md` |
