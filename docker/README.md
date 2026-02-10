# Docker Environment

Linux container for OmniBOR build interception.

## What's Inside

- Ubuntu 22.04 base
- gcc, clang, make, cmake, autoconf, libtool
- bomtrace3 (compiled from omnibor/bomsh)
- Python 3 + bomsh scripts
- Syft (manifest SBOM generation)
- Build dependencies for target repos (OpenSSL-dev, zlib-dev, etc.)

## Usage

```bash
docker-compose build
docker-compose run --rm omnibor-env bash
```

The `repos/` and `output/` directories are mounted as volumes so artifacts persist on the host.
