# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Add `requirements.txt` and `requirements-dev.txt` as single source of truth for Python dependencies
- Dockerfile now `COPY`s and installs from `requirements.txt` instead of ad-hoc `pip install` commands
- Docker build context changed to project root so Dockerfile can access `requirements.txt`
- Fixes `ModuleNotFoundError: No module named 'yaml'` when running app scripts inside the container
- Pin strace to v6.11 for stable bomtrace2/bomtrace3 patch application
- Force `linux/amd64` platform in docker-compose (bomtrace3 requires x86 `sys/reg.h`)
- Use `make -j1` for bomtrace3 to avoid `printers.h` parallel build race condition
- Suppress GCC `stringop-overflow` warning in bomsh_hook.c (upstream bomsh bug)
- Use `--enable-mpers=check` to match bomsh project's own build configuration

### Added

- Per-repo `apt_deps` field in `config.yaml` — explicitly lists required `-dev` packages for each target repo's build
- `DependencyValidator` class in `analyze.py` — checks all `apt_deps` are installed (via `dpkg-query`) before starting an instrumented build; prints actionable install hints on failure
- `ConfigGenerator.generate_entry()` now includes discovered `apt_deps` in generated config entries
- Explicit `apt_deps` for `curl` (10 packages) and `ffmpeg` (13 packages) in `config.yaml`
- `app/add_repo.py` — smart repo discovery script that auto-generates `config.yaml` entries from just a repo name using GitHub API (`gh` CLI)
  - Detects build systems: autoconf, cmake, meson, perl-configure (OpenSSL), auto-configure (nginx), configure-only (FFmpeg), make-only
  - Analyzes `configure.ac` / `CMakeLists.txt` / `configure` for dependency flags
  - Cross-checks required apt packages against the Dockerfile
  - Supports dry-run (default) and `--write` mode
- `app/data_loader.py` — external data loader with fetch/cache/fallback pattern
  - Build system indicators loaded from `app/data/build_systems.json` (sourced from GitHub Linguist)
  - Dependency metadata loaded from `app/data/dependencies.json` (sourced from Repology API)
  - On-demand Repology lookups for unknown dependencies with automatic cache persistence
  - Respects Repology rate limits (1 req/sec) and never fails on network errors
- `docs/summary/workflow-guide.md` — consolidated user guide for all workflows
- Mandatory rules-review step (Step 0) in `/setup-environment` workflow
- Comprehensive Docker build documentation in `docker/README.md` (troubleshooting table, architecture notes, version pin rationale)
- Detailed inline build notes in `docker/Dockerfile`
- `.windsurf/rules/build-documentation.md` — rule to update docs after build changes
- `.windsurf/rules/pre-commit.md` — pre-commit quality gates (tests, coverage, single-step git)
- `.windsurf/workflows/merge-pr.md` — streamlined PR merge workflow

### Changed

- `/add-repo` workflow now uses `app/add_repo.py` for automated config generation instead of manual editing
- `BUILD_SYSTEM_INDICATORS` and `KNOWN_DEPENDENCIES` replaced with external JSON data files loaded via `data_loader.py` (no more hardcoded static lists)
- Refactored `app/add_repo.py` from procedural to class-based architecture using design patterns:

  - `GitHubClient` — encapsulates all gh CLI / GitHub API interactions
  - `BuildSystemDetector` — detects build system from file list (Strategy pattern via indicator list)
  - `DependencyAnalyzer` — inspects config files for dependency flags
  - `BinaryDetector` — detects output binaries from Makefiles
  - `BuildStepGenerator` — generates build commands per build system (Strategy pattern via recipe dispatch)
  - `ConfigGenerator` — generates and writes config.yaml entries
  - `RepoDiscovery` — facade orchestrating the full pipeline (Facade pattern)

- Refactored `app/data_loader.py` from procedural to class-based architecture:

  - `HttpClient` — minimal HTTP transport with user-agent
  - `JsonCache` — atomic JSON read/write with age tracking
  - `RepologyResolver` — resolves library names to Debian -dev packages (Strategy pattern)
  - `DataLoader` — main facade composing the above
  - Module-level convenience functions preserved for backward compatibility

- Refactored `app/analyze.py` from procedural to class-based architecture:

  - `CommandRunner` — wraps subprocess execution with logging
  - `RepoCloner` — handles git clone logic
  - `BomtraceBuilder` — instrumented build with bomtrace3 and ADG generation
  - `SpdxGenerator` — generates SPDX SBOM from OmniBOR data
  - `SyftGenerator` — generates baseline manifest SBOM via Syft
  - `DocWriter` — writes build logs and runtime metrics
  - `AnalysisPipeline` — facade orchestrating the full workflow (Facade pattern)

- Refactored `app/compare.py` from procedural to class-based architecture:

  - `SpdxLoader` — loads and parses SPDX JSON files
  - `PackageExtractor` — extracts and normalizes package data
  - `SbomComparator` — compares two SPDX package sets
  - `ReportGenerator` — generates markdown comparison reports
  - `ComparisonPipeline` — facade orchestrating the full workflow (Facade pattern)

- Rewrote all tests to use class-based API (207 tests, 99% coverage)

## [0.1.0] - 2026-02-10

### Added

- Initial project structure
- Docker-based OmniBOR build interception environment (bomtrace3, syft)
- `app/analyze.py` — build interception and SPDX SBOM generation
- `app/compare.py` — SBOM comparison between OmniBOR and binary scan results
- Windsurf rules and workflows for project governance
- GitHub issue and PR templates
- Project documentation (README, CONTRIBUTING, LICENSE)
