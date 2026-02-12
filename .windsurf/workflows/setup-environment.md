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

## 1. Verify SSH access to DigitalOcean build droplet

All bomtrace3 instrumented builds run on a remote DigitalOcean droplet
(native x86_64 Linux). Local Docker is NOT needed.

```bash
ssh omnibor-build "uname -m && docker --version" 2>/dev/null || echo "Droplet is NOT reachable — it may be powered off"
```

If the droplet is powered off, remind the user to start it from the
DigitalOcean dashboard (cloud.digitalocean.com → Droplets → omnibor-build → Power On).

SSH config is in `~/.ssh/config` under host `omnibor-build` (IP: 137.184.178.186).

## 2. Verify key project files

```bash
ls -la app/config.yaml app/analyze.py app/compare.py docker/Dockerfile docker/docker-compose.yml
```

## 3. Check which repos are cloned (on droplet)

```bash
ssh omnibor-build "ls -d /root/omnibor-analysis/repos/*/ 2>/dev/null || echo 'No repos cloned yet'"
```

## 4. Check for existing output artifacts (on droplet)

```bash
ssh omnibor-build "find /root/omnibor-analysis/output/ -name '*.spdx.json' -o -name '*.sha1' 2>/dev/null | head -20 || echo 'No output artifacts yet'"
```

## 5. Check for existing docs/reports (local)

```bash
find docs/ -name "*.md" -not -name ".gitkeep" 2>/dev/null | sort | tail -10 || echo "No reports yet"
```
