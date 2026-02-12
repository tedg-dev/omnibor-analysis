---
description: Rules for Docker container usage in this project
---

# Docker Rules

- **All builds run on the DigitalOcean droplet** (`omnibor-build`, 137.184.178.186)
- **Local Docker is NOT needed** — the droplet runs native x86_64 Linux with Docker
- **Bomtrace3 requires Linux strace** — it will not work on macOS
- The container must have `SYS_PTRACE` capability and `seccomp:unconfined` security option
- SSH alias: `ssh omnibor-build` (configured in `~/.ssh/config`)
- To enter the container on the droplet:

  ```bash
  ssh omnibor-build "cd /root/omnibor-analysis && docker-compose -f docker/docker-compose.yml run --rm omnibor-env bash"
  ```

- To rebuild the image on the droplet:

  ```bash
  ssh omnibor-build "cd /root/omnibor-analysis && docker-compose -f docker/docker-compose.yml build"
  ```

# Volume Mounts (on droplet)

The following directories are mounted into the container:

| Host Path (droplet) | Container Path | Purpose |
|----------------------|---------------|---------|
| `repos/` | `/workspace/repos` | Cloned source repositories |
| `output/` | `/workspace/output` | Generated ADG, SPDX, binary scan artifacts |
| `app/` | `/workspace/app` | Orchestration scripts and config |
| `docs/` | `/workspace/docs` | Timestamped markdown reports |

# Dockerfile Maintenance

- When adding a new target repo, add its build dependencies to the Dockerfile
- Bomtrace2 and bomtrace3 are compiled from source (patched strace) during image build
- The bomsh scripts and binaries are at `/opt/bomsh/` inside the container
- Syft is installed at `/usr/local/bin/syft`
- After changing the Dockerfile locally, push to GitHub, pull on the droplet, then rebuild
