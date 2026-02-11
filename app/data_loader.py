#!/usr/bin/env python3
"""
External data loader for build system indicators and dependency metadata.

Implements a fetch → cache → fallback pattern:
1. Try to load from local cached JSON files (app/data/)
2. If cache is stale, refresh from external sources:
   - Repology API for dependency → apt package mapping
   - GitHub Linguist for build system file indicators
3. If network is unavailable, use cached data (never fail)

Cache files are JSON in app/data/ with _meta.last_updated timestamps.
"""

import json
import logging
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
BUILD_SYSTEMS_FILE = DATA_DIR / "build_systems.json"
DEPENDENCIES_FILE = DATA_DIR / "dependencies.json"

REPOLOGY_API = "https://repology.org/api/v1/project"
REPOLOGY_DEBIAN_REPOS = (
    "debian_unstable", "debian_13", "debian_14",
    "ubuntu_24_04", "ubuntu_22_04",
)
REPOLOGY_USER_AGENT = (
    "omnibor-analysis/0.1 "
    "(https://github.com/tedg-dev/omnibor-analysis)"
)

LINGUIST_URL = (
    "https://raw.githubusercontent.com/"
    "github-linguist/linguist/main/"
    "lib/linguist/languages.yml"
)


def _read_json(path):
    """Read and parse a JSON file. Returns None on failure."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None


def _write_json(path, data):
    """Write data to a JSON file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=False)
            fh.write("\n")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("Failed to write %s: %s", path, exc)
        if tmp.exists():
            tmp.unlink()


def _cache_age_days(data):
    """Return the age of cached data in days, or None if no timestamp."""
    meta = data.get("_meta", {}) if data else {}
    ts = meta.get("last_updated")
    if not ts:
        return None
    try:
        updated = datetime.fromisoformat(ts)
        now = datetime.now(timezone.utc)
        return (now - updated).total_seconds() / 86400
    except (ValueError, TypeError):
        return None


def _fetch_url(url, timeout=10):
    """Fetch a URL with proper user-agent. Returns bytes or None."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": REPOLOGY_USER_AGENT}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        logger.info(
            "Network fetch failed for %s: %s", url, exc
        )
        return None


def _fetch_json(url, timeout=10):
    """Fetch and parse JSON from a URL. Returns None on failure."""
    raw = _fetch_url(url, timeout=timeout)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "Invalid JSON from %s: %s", url, exc
        )
        return None


# ============================================================
# Repology-based dependency resolution
# ============================================================

def _find_debian_dev_package(repology_data):
    """Extract the -dev package name from Repology project data.

    Filters for Debian/Ubuntu repos and looks for binary package
    names ending in -dev.
    """
    if not isinstance(repology_data, list):
        return None

    for entry in repology_data:
        repo = entry.get("repo", "")
        if not any(
            repo.startswith(r) for r in REPOLOGY_DEBIAN_REPOS
        ):
            continue

        # Check binnames (array) first, then binname (string)
        binnames = entry.get("binnames", [])
        if not binnames:
            bn = entry.get("binname")
            if bn:
                binnames = [bn]

        for name in binnames:
            if name.endswith("-dev"):
                return name

    return None


def refresh_dependency(dep_name, dep_info):
    """Refresh a single dependency's apt package via Repology.

    Returns updated dep_info dict, or original if refresh fails.
    """
    project = dep_info.get("repology_project", dep_name)
    url = f"{REPOLOGY_API}/{project}"
    data = _fetch_json(url, timeout=15)
    if data is None:
        return dep_info

    dev_pkg = _find_debian_dev_package(data)
    if dev_pkg:
        updated = dict(dep_info)
        updated["apt_packages"] = [dev_pkg]
        return updated

    return dep_info


def refresh_all_dependencies(deps_data, max_age_days=7):
    """Refresh dependency data from Repology if cache is stale.

    Respects Repology rate limits (1 req/sec max).
    Returns updated data dict.
    """
    age = _cache_age_days(deps_data)
    if age is not None and age < max_age_days:
        logger.info(
            "Dependencies cache is %.1f days old "
            "(max %d), skipping refresh",
            age, max_age_days
        )
        return deps_data

    logger.info("Refreshing dependencies from Repology...")
    libraries = deps_data.get("libraries", {})
    updated_count = 0

    for dep_name, dep_info in libraries.items():
        new_info = refresh_dependency(dep_name, dep_info)
        if new_info is not dep_info:
            libraries[dep_name] = new_info
            updated_count += 1
        # Respect Repology rate limit: 1 req/sec
        time.sleep(1.1)

    deps_data["libraries"] = libraries
    deps_data.setdefault("_meta", {})["last_updated"] = (
        datetime.now(timezone.utc).isoformat()
    )

    logger.info(
        "Refreshed %d/%d dependencies",
        updated_count, len(libraries)
    )
    return deps_data


# ============================================================
# Public API
# ============================================================

def load_build_systems(refresh=False):
    """Load build system indicators.

    Returns list of (filename, system_type) tuples in priority order.
    """
    data = _read_json(BUILD_SYSTEMS_FILE)
    if data is None:
        logger.error(
            "No build_systems.json found — "
            "using empty indicator list"
        )
        return []

    indicators = data.get("indicators", [])
    return [
        (entry["file"], entry["system"])
        for entry in indicators
        if "file" in entry and "system" in entry
    ]


def load_dependencies(refresh=False):
    """Load dependency metadata.

    If refresh=True and cache is stale, fetches from Repology.
    Returns dict mapping dep_name → dep_info.
    """
    data = _read_json(DEPENDENCIES_FILE)
    if data is None:
        logger.error(
            "No dependencies.json found — "
            "using empty dependency map"
        )
        return {}

    max_age = data.get(
        "_meta", {}
    ).get("cache_max_age_days", 7)

    if refresh:
        data = refresh_all_dependencies(data, max_age)
        _write_json(DEPENDENCIES_FILE, data)

    return data.get("libraries", {})


def lookup_dependency(dep_name, deps=None):
    """Look up a single dependency by name.

    If not in the local cache, tries Repology on-demand and
    caches the result for future use.
    """
    if deps is None:
        deps = load_dependencies()

    # Exact match
    if dep_name in deps:
        return deps[dep_name]

    # Case-insensitive match
    for key, val in deps.items():
        if key.lower() == dep_name.lower():
            return val

    # On-demand Repology lookup for unknown dependencies
    logger.info(
        "Dependency '%s' not in cache, "
        "querying Repology...", dep_name
    )
    url = f"{REPOLOGY_API}/{dep_name}"
    repology_data = _fetch_json(url, timeout=15)
    if repology_data is None:
        return None

    dev_pkg = _find_debian_dev_package(repology_data)
    if dev_pkg is None:
        return None

    # Build a new entry and persist it
    new_entry = {
        "pkg_config": dep_name,
        "configure_flag": f"--with-{dep_name}",
        "cmake_flag": "",
        "apt_packages": [dev_pkg],
        "repology_project": dep_name,
    }

    # Persist to cache
    full_data = _read_json(DEPENDENCIES_FILE)
    if full_data and "libraries" in full_data:
        full_data["libraries"][dep_name] = new_entry
        _write_json(DEPENDENCIES_FILE, full_data)

    return new_entry
