---
description: Run on every startup to verify the omnibor-analysis environment is ready
---

# Setup Environment

Run this workflow when opening the omnibor-analysis workspace.

## 0. MANDATORY: Review all project rules

**This step is non-negotiable. Do it before ANY other work.**

Read every file in `.windsurf/rules/` to refresh all project rules:

```bash
for f in .windsurf/rules/*.md; do echo "=== $f ==="; cat "$f"; echo; done
```

After reading, confirm to the user which rules you've loaded and acknowledge
the key constraints (pre-commit gates, single-step git, CHANGELOG updates,
PR-first workflow, no direct commits to main).

**Do not proceed to any task until this step is complete.**

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
