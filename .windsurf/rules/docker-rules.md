---
description: Rules for Docker container usage in this project
---

# Docker Rules

- **All builds run inside the Docker container** — never compile C/C++ on the macOS host
- **Bomtrace3 requires Linux strace** — it will not work on macOS
- The container must have `SYS_PTRACE` capability and `seccomp:unconfined` security option
- Use `docker-compose run --rm omnibor-env bash` to enter the container interactively
- Use `docker-compose build` from the `docker/` directory to rebuild the image

# Volume Mounts

The following host directories are mounted into the container:

| Host Path | Container Path | Purpose |
|-----------|---------------|---------|
| `repos/` | `/workspace/repos` | Cloned source repositories |
| `output/` | `/workspace/output` | Generated ADG, SPDX, binary scan artifacts |
| `app/` | `/workspace/app` | Orchestration scripts and config |
| `docs/` | `/workspace/docs` | Timestamped markdown reports |

# Dockerfile Maintenance

- When adding a new target repo, add its build dependencies to the Dockerfile
- Bomtrace2 and bomtrace3 are compiled from source (patched strace) during image build
- The bomsh scripts and binaries are at `/opt/bomsh/` inside the container
- Syft is installed at `/usr/local/bin/syft`
