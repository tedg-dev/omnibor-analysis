---
description: Run on every startup to verify the omnibor-analysis environment is ready
---

# Setup Environment

Run this workflow when opening the omnibor-analysis workspace.

## 1. Verify Docker is running

```bash
docker info --format '{{.ServerVersion}}' 2>/dev/null || echo "Docker is NOT running"
```

## 2. Check if the omnibor-analysis image exists

```bash
docker images omnibor-analysis --format "{{.Repository}}:{{.Tag}} ({{.Size}}, created {{.CreatedSince}})"
```

If no image exists, build it:

```bash
docker-compose -f docker/docker-compose.yml build
```

## 3. Verify key project files

```bash
ls -la app/config.yaml app/analyze.py app/compare.py docker/Dockerfile docker/docker-compose.yml
```

## 4. Check which repos are cloned

```bash
ls -d repos/*/ 2>/dev/null || echo "No repos cloned yet"
```

## 5. Check for existing output artifacts

```bash
find output/ -name "*.spdx.json" -o -name "*.sha1" 2>/dev/null | head -20 || echo "No output artifacts yet"
```

## 6. Check for existing docs/reports

```bash
find docs/ -name "*.md" -not -name ".gitkeep" 2>/dev/null | sort | tail -10 || echo "No reports yet"
```
