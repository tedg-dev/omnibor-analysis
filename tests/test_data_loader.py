#!/usr/bin/env python3
"""Tests for app/data_loader.py — external data loading."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add app/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
import data_loader


class TestReadJson(unittest.TestCase):
    """Tests for _read_json."""

    def test_reads_valid_json(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"key": "value"}, f)
            tmp = Path(f.name)
        result = data_loader._read_json(tmp)
        self.assertEqual(result, {"key": "value"})
        tmp.unlink()

    def test_returns_none_for_missing_file(self):
        result = data_loader._read_json(
            Path("/nonexistent/file.json")
        )
        self.assertIsNone(result)

    def test_returns_none_for_invalid_json(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            f.write("not json {{{")
            tmp = Path(f.name)
        result = data_loader._read_json(tmp)
        self.assertIsNone(result)
        tmp.unlink()


class TestWriteJson(unittest.TestCase):
    """Tests for _write_json."""

    def test_writes_json_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            data_loader._write_json(
                path, {"hello": "world"}
            )
            with open(path, "r", encoding="utf-8") as f:
                result = json.load(f)
            self.assertEqual(result, {"hello": "world"})

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "dir" / "test.json"
            data_loader._write_json(path, {"a": 1})
            self.assertTrue(path.exists())
            path.unlink()

    def test_handles_write_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            with patch(
                "builtins.open",
                side_effect=OSError("disk full")
            ):
                # Should not raise, just log warning
                data_loader._write_json(path, {"a": 1})

    def test_atomic_write_cleans_tmp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.json"
            data_loader._write_json(path, [1, 2, 3])
            tmp_path = path.with_suffix(".tmp")
            self.assertFalse(tmp_path.exists())
            self.assertTrue(path.exists())


class TestCacheAgeDays(unittest.TestCase):
    """Tests for _cache_age_days."""

    def test_returns_none_for_no_data(self):
        self.assertIsNone(data_loader._cache_age_days(None))

    def test_returns_none_for_no_timestamp(self):
        self.assertIsNone(
            data_loader._cache_age_days({"_meta": {}})
        )

    def test_returns_none_for_no_meta(self):
        self.assertIsNone(
            data_loader._cache_age_days({"foo": "bar"})
        )

    def test_returns_age_for_valid_timestamp(self):
        yesterday = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
        age = data_loader._cache_age_days(
            {"_meta": {"last_updated": yesterday}}
        )
        self.assertIsNotNone(age)
        self.assertAlmostEqual(age, 1.0, delta=0.1)

    def test_returns_none_for_invalid_timestamp(self):
        age = data_loader._cache_age_days(
            {"_meta": {"last_updated": "not-a-date"}}
        )
        self.assertIsNone(age)


class TestFetchUrl(unittest.TestCase):
    """Tests for _fetch_url."""

    @patch("data_loader.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(
            return_value=False
        )
        mock_urlopen.return_value = mock_resp

        result = data_loader._fetch_url(
            "https://example.com"
        )
        self.assertEqual(result, b'{"ok": true}')

    @patch("data_loader.urllib.request.urlopen")
    def test_network_error_returns_none(
        self, mock_urlopen
    ):
        mock_urlopen.side_effect = (
            data_loader.urllib.error.URLError("fail")
        )
        result = data_loader._fetch_url(
            "https://example.com"
        )
        self.assertIsNone(result)

    @patch("data_loader.urllib.request.urlopen")
    def test_timeout_returns_none(self, mock_urlopen):
        mock_urlopen.side_effect = TimeoutError()
        result = data_loader._fetch_url(
            "https://example.com"
        )
        self.assertIsNone(result)


class TestFetchJson(unittest.TestCase):
    """Tests for _fetch_json."""

    @patch("data_loader._fetch_url")
    def test_valid_json(self, mock_fetch):
        mock_fetch.return_value = b'[{"repo": "test"}]'
        result = data_loader._fetch_json(
            "https://example.com"
        )
        self.assertEqual(result, [{"repo": "test"}])

    @patch("data_loader._fetch_url")
    def test_network_failure(self, mock_fetch):
        mock_fetch.return_value = None
        result = data_loader._fetch_json(
            "https://example.com"
        )
        self.assertIsNone(result)

    @patch("data_loader._fetch_url")
    def test_invalid_json(self, mock_fetch):
        mock_fetch.return_value = b"not json"
        result = data_loader._fetch_json(
            "https://example.com"
        )
        self.assertIsNone(result)


class TestFindDebianDevPackage(unittest.TestCase):
    """Tests for _find_debian_dev_package."""

    def test_finds_dev_from_binnames(self):
        data = [
            {
                "repo": "debian_unstable",
                "binnames": [
                    "openssl", "libssl-dev",
                    "libssl3t64"
                ],
            }
        ]
        result = data_loader._find_debian_dev_package(
            data
        )
        self.assertEqual(result, "libssl-dev")

    def test_finds_dev_from_binname(self):
        data = [
            {
                "repo": "ubuntu_24_04",
                "binname": "libz-dev",
            }
        ]
        result = data_loader._find_debian_dev_package(
            data
        )
        self.assertEqual(result, "libz-dev")

    def test_skips_non_debian_repos(self):
        data = [
            {
                "repo": "freebsd",
                "binnames": ["openssl-dev"],
            },
            {
                "repo": "arch",
                "binname": "openssl-dev",
            },
        ]
        result = data_loader._find_debian_dev_package(
            data
        )
        self.assertIsNone(result)

    def test_returns_none_for_no_dev_package(self):
        data = [
            {
                "repo": "debian_unstable",
                "binnames": ["openssl", "libssl3"],
            }
        ]
        result = data_loader._find_debian_dev_package(
            data
        )
        self.assertIsNone(result)

    def test_returns_none_for_non_list(self):
        result = data_loader._find_debian_dev_package(
            "not a list"
        )
        self.assertIsNone(result)

    def test_returns_none_for_empty_list(self):
        result = data_loader._find_debian_dev_package([])
        self.assertIsNone(result)

    def test_no_binnames_or_binname(self):
        data = [
            {
                "repo": "debian_unstable",
                "visiblename": "openssl",
            }
        ]
        result = data_loader._find_debian_dev_package(
            data
        )
        self.assertIsNone(result)


class TestRefreshDependency(unittest.TestCase):
    """Tests for refresh_dependency."""

    @patch("data_loader._fetch_json")
    def test_updates_apt_packages(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "repo": "debian_unstable",
                "binnames": ["libssl-dev", "libssl3"],
            }
        ]
        dep_info = {
            "apt_packages": ["old-pkg"],
            "repology_project": "openssl",
        }
        result = data_loader.refresh_dependency(
            "openssl", dep_info
        )
        self.assertEqual(
            result["apt_packages"], ["libssl-dev"]
        )

    @patch("data_loader._fetch_json")
    def test_returns_original_on_fetch_failure(
        self, mock_fetch
    ):
        mock_fetch.return_value = None
        dep_info = {"apt_packages": ["old-pkg"]}
        result = data_loader.refresh_dependency(
            "openssl", dep_info
        )
        self.assertIs(result, dep_info)

    @patch("data_loader._fetch_json")
    def test_returns_original_if_no_dev_found(
        self, mock_fetch
    ):
        mock_fetch.return_value = [
            {
                "repo": "debian_unstable",
                "binnames": ["openssl"],
            }
        ]
        dep_info = {"apt_packages": ["old-pkg"]}
        result = data_loader.refresh_dependency(
            "openssl", dep_info
        )
        self.assertIs(result, dep_info)

    @patch("data_loader._fetch_json")
    def test_uses_dep_name_as_fallback_project(
        self, mock_fetch
    ):
        mock_fetch.return_value = None
        dep_info = {"apt_packages": ["x"]}
        data_loader.refresh_dependency(
            "mylib", dep_info
        )
        mock_fetch.assert_called_once_with(
            f"{data_loader.REPOLOGY_API}/mylib",
            timeout=15
        )


class TestRefreshAllDependencies(unittest.TestCase):
    """Tests for refresh_all_dependencies."""

    @patch("data_loader.time.sleep")
    @patch("data_loader.refresh_dependency")
    def test_refreshes_stale_cache(
        self, mock_refresh, mock_sleep
    ):
        mock_refresh.side_effect = lambda n, i: {
            **i, "apt_packages": ["new-pkg"]
        }
        deps_data = {
            "_meta": {"last_updated": None},
            "libraries": {
                "openssl": {
                    "apt_packages": ["old"],
                    "repology_project": "openssl",
                },
            },
        }
        result = data_loader.refresh_all_dependencies(
            deps_data, max_age_days=7
        )
        self.assertIn("last_updated", result["_meta"])
        mock_sleep.assert_called()

    @patch("data_loader.refresh_dependency")
    def test_skips_fresh_cache(self, mock_refresh):
        now = datetime.now(timezone.utc).isoformat()
        deps_data = {
            "_meta": {"last_updated": now},
            "libraries": {
                "openssl": {"apt_packages": ["x"]},
            },
        }
        result = data_loader.refresh_all_dependencies(
            deps_data, max_age_days=7
        )
        mock_refresh.assert_not_called()
        self.assertIs(result, deps_data)

    @patch("data_loader.time.sleep")
    @patch("data_loader.refresh_dependency")
    def test_counts_updates(
        self, mock_refresh, mock_sleep
    ):
        original = {"apt_packages": ["old"]}
        # Return same object = no update
        mock_refresh.return_value = original
        deps_data = {
            "_meta": {},
            "libraries": {"lib": original},
        }
        result = data_loader.refresh_all_dependencies(
            deps_data, max_age_days=0
        )
        self.assertIn("last_updated", result["_meta"])


class TestLoadBuildSystems(unittest.TestCase):
    """Tests for load_build_systems."""

    @patch("data_loader._read_json")
    def test_loads_indicators(self, mock_read):
        mock_read.return_value = {
            "indicators": [
                {"file": "configure.ac", "system": "autoconf"},
                {"file": "CMakeLists.txt", "system": "cmake"},
            ]
        }
        result = data_loader.load_build_systems()
        self.assertEqual(
            result,
            [
                ("configure.ac", "autoconf"),
                ("CMakeLists.txt", "cmake"),
            ]
        )

    @patch("data_loader._read_json")
    def test_returns_empty_on_missing_file(
        self, mock_read
    ):
        mock_read.return_value = None
        result = data_loader.load_build_systems()
        self.assertEqual(result, [])

    @patch("data_loader._read_json")
    def test_skips_malformed_entries(self, mock_read):
        mock_read.return_value = {
            "indicators": [
                {"file": "ok", "system": "autoconf"},
                {"bad": "entry"},
                {"file": "also_ok", "system": "cmake"},
            ]
        }
        result = data_loader.load_build_systems()
        self.assertEqual(len(result), 2)


class TestLoadDependencies(unittest.TestCase):
    """Tests for load_dependencies."""

    @patch("data_loader._read_json")
    def test_loads_libraries(self, mock_read):
        mock_read.return_value = {
            "_meta": {"cache_max_age_days": 7},
            "libraries": {
                "openssl": {
                    "apt_packages": ["libssl-dev"]
                },
            },
        }
        result = data_loader.load_dependencies()
        self.assertIn("openssl", result)

    @patch("data_loader._read_json")
    def test_returns_empty_on_missing_file(
        self, mock_read
    ):
        mock_read.return_value = None
        result = data_loader.load_dependencies()
        self.assertEqual(result, {})

    @patch("data_loader._write_json")
    @patch("data_loader.refresh_all_dependencies")
    @patch("data_loader._read_json")
    def test_refresh_mode(
        self, mock_read, mock_refresh, mock_write
    ):
        mock_read.return_value = {
            "_meta": {"cache_max_age_days": 7},
            "libraries": {"x": {"apt_packages": ["y"]}},
        }
        mock_refresh.return_value = mock_read.return_value
        deps = data_loader.load_dependencies(
            refresh=True
        )
        self.assertIn("x", deps)
        mock_refresh.assert_called_once()
        mock_write.assert_called_once()


class TestLookupDependency(unittest.TestCase):
    """Tests for lookup_dependency."""

    def test_exact_match(self):
        deps = {
            "openssl": {"apt_packages": ["libssl-dev"]}
        }
        result = data_loader.lookup_dependency(
            "openssl", deps
        )
        self.assertEqual(
            result["apt_packages"], ["libssl-dev"]
        )

    def test_case_insensitive_match(self):
        deps = {
            "OpenSSL": {"apt_packages": ["libssl-dev"]}
        }
        result = data_loader.lookup_dependency(
            "openssl", deps
        )
        self.assertEqual(
            result["apt_packages"], ["libssl-dev"]
        )

    @patch("data_loader._write_json")
    @patch("data_loader._read_json")
    @patch("data_loader._fetch_json")
    def test_repology_lookup_on_miss(
        self, mock_fetch, mock_read, mock_write
    ):
        mock_fetch.return_value = [
            {
                "repo": "debian_unstable",
                "binnames": ["libnew-dev"],
            }
        ]
        mock_read.return_value = {
            "libraries": {}
        }
        result = data_loader.lookup_dependency(
            "newlib", {}
        )
        self.assertIsNotNone(result)
        self.assertEqual(
            result["apt_packages"], ["libnew-dev"]
        )
        mock_write.assert_called_once()

    @patch("data_loader._fetch_json")
    def test_returns_none_on_total_miss(
        self, mock_fetch
    ):
        mock_fetch.return_value = None
        result = data_loader.lookup_dependency(
            "unknown", {}
        )
        self.assertIsNone(result)

    @patch("data_loader._fetch_json")
    def test_returns_none_if_no_dev_pkg(
        self, mock_fetch
    ):
        mock_fetch.return_value = [
            {
                "repo": "debian_unstable",
                "binnames": ["nodev"],
            }
        ]
        result = data_loader.lookup_dependency(
            "nodev", {}
        )
        self.assertIsNone(result)

    @patch("data_loader._read_json")
    @patch("data_loader._fetch_json")
    def test_no_persist_if_no_libraries_key(
        self, mock_fetch, mock_read
    ):
        mock_fetch.return_value = [
            {
                "repo": "debian_unstable",
                "binnames": ["libnew-dev"],
            }
        ]
        mock_read.return_value = None
        entry = data_loader.lookup_dependency(
            "newlib", {}
        )
        self.assertIsNotNone(entry)


class TestLoadBuildSystemsIntegration(unittest.TestCase):
    """Integration test using real seed data files."""

    def test_real_seed_data_loads(self):
        result = data_loader.load_build_systems()
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) > 0)
        # Check known entries exist
        files = [f for f, _ in result]
        self.assertIn("configure.ac", files)
        self.assertIn("CMakeLists.txt", files)
        self.assertIn("meson.build", files)

    def test_real_dependencies_load(self):
        result = data_loader.load_dependencies()
        self.assertIsInstance(result, dict)
        self.assertTrue(len(result) > 0)
        self.assertIn("openssl", result)
        self.assertIn(
            "libssl-dev",
            result["openssl"]["apt_packages"]
        )


if __name__ == "__main__":
    unittest.main()
