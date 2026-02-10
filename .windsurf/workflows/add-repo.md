---
description: Add a new target repository for OmniBOR analysis
---

# Add a New Target Repository

Steps to add a new C/C++ repository for build interception analysis.

## 1. Add the repo to config.yaml

Edit `app/config.yaml` and add a new entry under `repos:`:

```yaml
repos:
  newrepo:
    url: https://github.com/org/newrepo.git
    branch: main
    build_steps:
      - autoreconf -fi          # or cmake .. or ./configure
      - ./configure --with-xxx
      - make -j$(nproc)
    clean_cmd: make clean
    description: "Short description of the project"
    output_binaries:
      - path/to/binary
      - path/to/libfoo.so
```

**Important:** The last entry in `build_steps` must be the `make` command — this is the
step that gets wrapped with `bomtrace3`.

## 2. Add build dependencies to the Dockerfile

Edit `docker/Dockerfile` and add any required `-dev` packages:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfoo-dev \
    libbar-dev
```

## 3. Rebuild the Docker image

```bash
docker-compose -f docker/docker-compose.yml build
```

## 4. Create output directories

```bash
mkdir -p output/omnibor/newrepo output/spdx/newrepo output/binary-scan/newrepo docs/newrepo
```

## 5. Run analysis

```bash
docker-compose -f docker/docker-compose.yml run --rm omnibor-env python3 /workspace/app/analyze.py --repo newrepo
```

## Tips

- Test the build manually inside the container first before running analyze.py
- Use `docker-compose run --rm omnibor-env bash` to enter the container and experiment
- If the project uses cmake instead of autoconf, the build_steps would be:
  ```yaml
  build_steps:
    - mkdir -p build && cd build && cmake ..
    - make -C build -j$(nproc)
  ```
