---
description: Rules for OmniBOR/Bomsh build interception workflow
---

# OmniBOR / Bomsh Rules

## Terminology

- **Build Interception** — instrumenting the compiler/linker to observe what is actually compiled
- **Bomtrace3** — the preferred tracer (20% overhead vs 2-5x for bomtrace2)
- **ADG** — Artifact Dependency Graph (OmniBOR's output format)
- **Build Metadata Extraction** (Yocto SBOM, Maven plugins) is NOT true build interception;
  it is essentially manifest scanning enhanced with build-system context

## Workflow Sequence

1. Clone target repo into `repos/<name>/`
2. Run pre-build steps (autoreconf, configure) WITHOUT bomtrace instrumentation
3. Run the final `make` step WITH bomtrace3: `bomtrace3 make -j$(nproc)`
4. Run `bomsh_create_bom.py` to generate ADG from raw logfile
5. Run `bomsh_sbom.py` to generate SPDX SBOM from ADG
6. Optionally run `syft` for a manifest-based baseline SBOM

## Key Paths Inside Container

| Path | Purpose |
|------|---------|
| `/opt/bomsh/bin/bomtrace3` | Bomtrace3 binary |
| `/opt/bomsh/scripts/` | Bomsh Python scripts |
| `/tmp/bomsh_hook_raw_logfile.sha1` | Raw build log (default location) |
| `/tmp/bomsh_createbom_jsonfile` | Generated hash-tree database |

## Important Notes

- Only the final `make` step should be instrumented — configure/autoreconf are not builds
- bomsh_hook2.py must be in /tmp/ for bomtrace2 (already copied in Dockerfile)
- bomtrace3 does NOT need bomsh_hook2.py — it has the functionality built in as C code
- ADG output defaults to `${PWD}/.omnibor` but we redirect to `output/omnibor/<repo>/` via `-b` flag
- SPDX v2.3 is the supported version
