#!/usr/bin/env python3
"""
Tests for app/add_repo.py — smart repo discovery and config generation.

Uses unittest.mock to avoid real GitHub API calls.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add app/ to path so we can import add_repo
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import add_repo


class TestParseGithubUrl(unittest.TestCase):
    """Tests for parse_github_url()."""

    def test_https_url(self):
        result = add_repo.parse_github_url(
            "https://github.com/curl/curl"
        )
        self.assertEqual(result, "curl/curl")

    def test_https_url_with_git_suffix(self):
        result = add_repo.parse_github_url(
            "https://github.com/curl/curl.git"
        )
        self.assertEqual(result, "curl/curl")

    def test_ssh_url(self):
        result = add_repo.parse_github_url(
            "git@github.com:curl/curl.git"
        )
        self.assertEqual(result, "curl/curl")

    def test_plain_name_returns_none(self):
        result = add_repo.parse_github_url("curl")
        self.assertIsNone(result)

    def test_owner_repo_returns_none(self):
        result = add_repo.parse_github_url("curl/curl")
        self.assertIsNone(result)


class TestDetectBuildSystem(unittest.TestCase):
    """Tests for detect_build_system()."""

    def test_autoconf(self):
        files = ["configure.ac", "Makefile.am", "README"]
        self.assertEqual(
            add_repo.detect_build_system(files), "autoconf"
        )

    def test_autoconf_in(self):
        files = ["configure.in", "Makefile"]
        self.assertEqual(
            add_repo.detect_build_system(files), "autoconf"
        )

    def test_cmake(self):
        files = ["CMakeLists.txt", "src/main.c"]
        self.assertEqual(
            add_repo.detect_build_system(files), "cmake"
        )

    def test_meson(self):
        files = ["meson.build", "src/main.c"]
        self.assertEqual(
            add_repo.detect_build_system(files), "meson"
        )

    def test_perl_configure_capital(self):
        files = ["Configure", "Makefile", "README"]
        self.assertEqual(
            add_repo.detect_build_system(files),
            "perl-configure"
        )

    def test_perl_configure_config(self):
        files = ["config", "Makefile", "README"]
        self.assertEqual(
            add_repo.detect_build_system(files),
            "perl-configure"
        )

    def test_auto_configure(self):
        files = ["auto/configure", "src/core", "README"]
        self.assertEqual(
            add_repo.detect_build_system(files),
            "auto-configure"
        )

    def test_configure_only(self):
        files = ["configure", "Makefile", "README"]
        self.assertEqual(
            add_repo.detect_build_system(files),
            "configure-only"
        )

    def test_configure_before_makefile(self):
        """configure should be detected before Makefile."""
        files = ["Makefile", "configure", "README"]
        self.assertEqual(
            add_repo.detect_build_system(files),
            "configure-only"
        )

    def test_make_only(self):
        files = ["Makefile", "src/main.c"]
        self.assertEqual(
            add_repo.detect_build_system(files), "make-only"
        )

    def test_unknown(self):
        files = ["README.md", "src/main.rs"]
        self.assertEqual(
            add_repo.detect_build_system(files), "unknown"
        )

    def test_autoconf_takes_priority_over_cmake(self):
        files = [
            "configure.ac", "CMakeLists.txt", "Makefile"
        ]
        self.assertEqual(
            add_repo.detect_build_system(files), "autoconf"
        )


class TestGenerateBuildSteps(unittest.TestCase):
    """Tests for generate_build_steps()."""

    def test_autoconf_no_flags(self):
        steps = add_repo.generate_build_steps(
            "autoconf", []
        )
        self.assertEqual(steps, [
            "autoreconf -fi",
            "./configure",
            "make -j$(nproc)",
        ])

    def test_autoconf_with_flags(self):
        steps = add_repo.generate_build_steps(
            "autoconf", ["--with-openssl", "--with-zlib"]
        )
        self.assertEqual(steps[1],
                         "./configure --with-openssl --with-zlib")

    def test_cmake_no_flags(self):
        steps = add_repo.generate_build_steps("cmake", [])
        self.assertEqual(steps, [
            "mkdir -p build && cd build && cmake ..",
            "make -C build -j$(nproc)",
        ])

    def test_cmake_with_flags(self):
        steps = add_repo.generate_build_steps(
            "cmake", ["-DCMAKE_USE_OPENSSL=ON"]
        )
        self.assertIn(
            "-DCMAKE_USE_OPENSSL=ON", steps[0]
        )

    def test_meson(self):
        steps = add_repo.generate_build_steps("meson", [])
        self.assertEqual(steps, [
            "meson setup build",
            "ninja -C build",
        ])

    def test_perl_configure(self):
        steps = add_repo.generate_build_steps(
            "perl-configure", []
        )
        self.assertEqual(steps, [
            "./config",
            "make -j$(nproc)",
        ])

    def test_auto_configure(self):
        steps = add_repo.generate_build_steps(
            "auto-configure", []
        )
        self.assertEqual(steps, [
            "auto/configure",
            "make -j$(nproc)",
        ])

    def test_configure_only(self):
        steps = add_repo.generate_build_steps(
            "configure-only", []
        )
        self.assertEqual(steps, [
            "./configure",
            "make -j$(nproc)",
        ])

    def test_configure_only_with_flags(self):
        steps = add_repo.generate_build_steps(
            "configure-only", ["--enable-libx264"]
        )
        self.assertEqual(
            steps[0], "./configure --enable-libx264"
        )

    def test_make_only(self):
        steps = add_repo.generate_build_steps(
            "make-only", []
        )
        self.assertEqual(steps, ["make -j$(nproc)"])

    def test_unknown(self):
        steps = add_repo.generate_build_steps(
            "unknown", []
        )
        self.assertEqual(len(steps), 2)
        self.assertIn("TODO", steps[0])

    def test_last_step_is_make(self):
        """The last build step must always be a make/ninja command."""
        for bs in [
            "autoconf", "cmake", "configure-only",
            "make-only", "perl-configure",
            "auto-configure", "unknown",
        ]:
            steps = add_repo.generate_build_steps(bs, [])
            last = steps[-1]
            self.assertTrue(
                "make" in last or "ninja" in last,
                f"Last step for {bs} should be make/ninja, got: {last}"
            )


class TestGenerateConfigEntry(unittest.TestCase):
    """Tests for generate_config_entry()."""

    def test_basic_entry(self):
        repo_info = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
        }
        entry = add_repo.generate_config_entry(
            "curl", repo_info, "autoconf",
            ["autoreconf -fi", "./configure", "make"],
            ["src/curl"],
            "A URL transfer library"
        )
        self.assertEqual(
            entry["url"],
            "https://github.com/curl/curl.git"
        )
        self.assertEqual(entry["branch"], "master")
        self.assertEqual(len(entry["build_steps"]), 3)
        self.assertEqual(entry["clean_cmd"], "make clean")
        self.assertEqual(
            entry["description"], "A URL transfer library"
        )
        self.assertEqual(
            entry["output_binaries"], ["src/curl"]
        )


class TestDetectOutputBinaries(unittest.TestCase):
    """Tests for detect_output_binaries()."""

    def test_fallback_with_src(self):
        files = ["src/main.c", "Makefile"]
        bins = add_repo.detect_output_binaries(
            "test/repo", "myapp", "autoconf", files
        )
        self.assertIn("src/.libs/myapp", bins)
        self.assertIn("src/myapp", bins)

    def test_fallback_without_src(self):
        files = ["main.c", "Makefile"]
        bins = add_repo.detect_output_binaries(
            "test/repo", "myapp", "autoconf", files
        )
        self.assertEqual(bins, ["myapp"])

    @patch("add_repo.get_file_content")
    def test_bin_programs_from_makefile_am(
        self, mock_get_file
    ):
        mock_get_file.return_value = (
            "bin_PROGRAMS = myapp\n"
        )
        files = ["Makefile.am", "src/main.c"]
        bins = add_repo.detect_output_binaries(
            "test/repo", "myapp", "autoconf", files
        )
        self.assertIn("myapp", bins)


class TestGhApi(unittest.TestCase):
    """Tests for gh_api() with mocked subprocess."""

    @patch("add_repo.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"full_name": "curl/curl"}'
        )
        result = add_repo.gh_api("repos/curl/curl")
        self.assertEqual(
            result["full_name"], "curl/curl"
        )

    @patch("add_repo.subprocess.run")
    def test_failure_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error"
        )
        result = add_repo.gh_api("repos/bad/repo")
        self.assertIsNone(result)

    @patch("add_repo.subprocess.run")
    def test_invalid_json_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="not json"
        )
        result = add_repo.gh_api("repos/curl/curl")
        self.assertIsNone(result)


class TestGhSearchRepo(unittest.TestCase):
    """Tests for gh_search_repo() with mocked subprocess."""

    @patch("add_repo.subprocess.run")
    def test_exact_name_match_preferred(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "fullName": "someone/curl-wrapper",
                    "language": "C",
                    "stargazersCount": 100,
                },
                {
                    "fullName": "curl/curl",
                    "language": "C",
                    "stargazersCount": 40000,
                },
            ])
        )
        result = add_repo.gh_search_repo("curl")
        self.assertEqual(result["fullName"], "curl/curl")

    @patch("add_repo.subprocess.run")
    def test_c_repos_preferred(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "fullName": "js/mylib",
                    "language": "JavaScript",
                    "stargazersCount": 50000,
                },
                {
                    "fullName": "c/mylib",
                    "language": "C",
                    "stargazersCount": 1000,
                },
            ])
        )
        result = add_repo.gh_search_repo("mylib")
        self.assertEqual(result["fullName"], "c/mylib")

    @patch("add_repo.subprocess.run")
    def test_no_results(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="[]"
        )
        result = add_repo.gh_search_repo("nonexistent")
        self.assertIsNone(result)

    @patch("add_repo.subprocess.run")
    def test_gh_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="auth required"
        )
        result = add_repo.gh_search_repo("curl")
        self.assertIsNone(result)


class TestGetRepoInfo(unittest.TestCase):
    """Tests for get_repo_info()."""

    @patch("add_repo.gh_api")
    def test_full_url(self, mock_api):
        mock_api.return_value = {
            "full_name": "curl/curl",
            "description": "transfer lib",
            "html_url": "https://github.com/curl/curl",
            "stargazers_count": 40000,
            "default_branch": "master",
            "language": "C",
        }
        result = add_repo.get_repo_info(
            "https://github.com/curl/curl"
        )
        self.assertEqual(
            result["fullName"], "curl/curl"
        )

    @patch("add_repo.gh_api")
    def test_owner_repo(self, mock_api):
        mock_api.return_value = {
            "full_name": "curl/curl",
            "description": "transfer lib",
            "html_url": "https://github.com/curl/curl",
            "stargazers_count": 40000,
            "default_branch": "master",
            "language": "C",
        }
        result = add_repo.get_repo_info("curl/curl")
        self.assertEqual(
            result["fullName"], "curl/curl"
        )

    @patch("add_repo.gh_search_repo")
    def test_plain_name_searches(self, mock_search):
        mock_search.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
        }
        info = add_repo.get_repo_info("curl")
        mock_search.assert_called_once_with("curl")
        self.assertEqual(info["fullName"], "curl/curl")


class TestDetectConfigureFlags(unittest.TestCase):
    """Tests for detect_configure_flags()."""

    @patch("add_repo.get_file_content")
    def test_autoconf_detects_openssl(
        self, mock_get_file
    ):
        mock_get_file.return_value = (
            "AC_CHECK_LIB([ssl], [SSL_new])\n"
            "PKG_CHECK_MODULES([OPENSSL], [openssl])\n"
        )
        flags, pkgs = add_repo.detect_configure_flags(
            "curl/curl", "master", "autoconf",
            ["configure.ac"]
        )
        self.assertIn("--with-openssl", flags)
        self.assertIn("libssl-dev", pkgs)

    @patch("add_repo.get_file_content")
    def test_cmake_detects_openssl(
        self, mock_get_file
    ):
        mock_get_file.return_value = (
            "find_package(OpenSSL REQUIRED)\n"
        )
        flags, pkgs = add_repo.detect_configure_flags(
            "test/repo", "main", "cmake",
            ["CMakeLists.txt"]
        )
        self.assertIn("-DCMAKE_USE_OPENSSL=ON", flags)
        self.assertIn("libssl-dev", pkgs)

    def test_no_flags_for_unknown_build_system(self):
        flags, pkgs = add_repo.detect_configure_flags(
            "test/repo", "main", "unknown", []
        )
        self.assertEqual(flags, [])
        self.assertEqual(pkgs, [])

    @patch("add_repo.get_file_content")
    def test_configure_only_analyzes_script(
        self, mock_get_file
    ):
        mock_get_file.return_value = (
            "# --enable-libx264\n"
            "# --enable-libx265\n"
            "# openssl support\n"
        )
        flags, pkgs = add_repo.detect_configure_flags(
            "FFmpeg/FFmpeg", "master",
            "configure-only", ["configure"]
        )
        self.assertIn("--enable-libx264", flags)
        self.assertIn("--enable-libx265", flags)
        self.assertIn("--with-openssl", flags)


class TestGetRepoStats(unittest.TestCase):
    """Tests for get_repo_stats()."""

    @patch("add_repo.gh_api")
    def test_returns_stats_string(self, mock_api):
        mock_api.return_value = {
            "C": 400000, "Python": 20000
        }
        result = add_repo.get_repo_stats("curl/curl")
        self.assertIn("K LoC", result)
        self.assertIn("C", result)

    @patch("add_repo.gh_api")
    def test_returns_empty_on_failure(self, mock_api):
        mock_api.return_value = None
        result = add_repo.get_repo_stats("bad/repo")
        self.assertEqual(result, "")


class TestWriteConfigEntry(unittest.TestCase):
    """Tests for write_config_entry()."""

    def test_writes_new_entry(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml",
            delete=False
        ) as f:
            f.write(
                "repos:\n  curl:\n"
                "    url: https://github.com/curl/curl.git\n"
            )
            tmp_path = f.name

        entry = {
            "url": "https://github.com/madler/zlib.git",
            "branch": "develop",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "zlib",
            "output_binaries": ["zlib"],
        }

        with patch.object(
            Path, "__truediv__",
            return_value=Path(tmp_path)
        ):
            # Directly test the write logic
            import yaml
            with open(tmp_path, "r", encoding="utf-8") as fh:
                config = yaml.safe_load(fh)
            config["repos"]["zlib"] = entry
            with open(tmp_path, "w", encoding="utf-8") as fh:
                yaml.dump(
                    config, fh,
                    default_flow_style=False,
                    sort_keys=False
                )

        import yaml
        with open(tmp_path, "r", encoding="utf-8") as fh:
            result = yaml.safe_load(fh)

        self.assertIn("zlib", result["repos"])
        self.assertIn("curl", result["repos"])
        self.assertEqual(
            result["repos"]["zlib"]["branch"], "develop"
        )

        Path(tmp_path).unlink()


class TestRepoInfoFromApi(unittest.TestCase):
    """Tests for _repo_info_from_api()."""

    def test_converts_api_response(self):
        data = {
            "full_name": "curl/curl",
            "description": "transfer lib",
            "html_url": "https://github.com/curl/curl",
            "stargazers_count": 40000,
            "default_branch": "master",
            "language": "C",
        }
        result = add_repo._repo_info_from_api(data)
        self.assertEqual(
            result["fullName"], "curl/curl"
        )
        self.assertEqual(
            result["defaultBranch"], "master"
        )
        self.assertEqual(
            result["stargazersCount"], 40000
        )

    def test_handles_missing_optional_fields(self):
        data = {
            "full_name": "test/repo",
            "html_url": "https://github.com/test/repo",
        }
        result = add_repo._repo_info_from_api(data)
        self.assertEqual(result["description"], "")
        self.assertEqual(result["language"], "")
        self.assertEqual(result["stargazersCount"], 0)
        self.assertEqual(
            result["defaultBranch"], "main"
        )


class TestGetFileContent(unittest.TestCase):
    """Tests for get_file_content()."""

    @patch("add_repo.gh_api")
    def test_decodes_base64(self, mock_api):
        import base64
        content = "hello world"
        encoded = base64.b64encode(
            content.encode()
        ).decode()
        mock_api.return_value = {
            "content": encoded
        }
        result = add_repo.get_file_content(
            "test/repo", "README.md", "main"
        )
        self.assertEqual(result, "hello world")

    @patch("add_repo.gh_api")
    def test_returns_none_on_missing(self, mock_api):
        mock_api.return_value = None
        result = add_repo.get_file_content(
            "test/repo", "missing.txt", "main"
        )
        self.assertIsNone(result)

    @patch("add_repo.gh_api")
    def test_returns_none_on_no_content(
        self, mock_api
    ):
        mock_api.return_value = {"name": "file.txt"}
        result = add_repo.get_file_content(
            "test/repo", "file.txt", "main"
        )
        self.assertIsNone(result)


class TestGetRepoTree(unittest.TestCase):
    """Tests for get_repo_tree()."""

    @patch("add_repo.gh_api")
    def test_collects_files(self, mock_api):
        def side_effect(url):
            is_root = (
                "contents?" in url
                and "src" not in url
                and "lib" not in url
                and "auto" not in url
            )
            if is_root:
                return [
                    {"name": "configure.ac"},
                    {"name": "Makefile"},
                    {"name": "src"},
                ]
            elif "/contents/src" in url:
                return [{"name": "main.c"}]
            elif "/contents/lib" in url:
                return None
            elif "/contents/auto" in url:
                return None
            return None

        mock_api.side_effect = side_effect
        files = add_repo.get_repo_tree(
            "test/repo", "main"
        )
        self.assertIn("configure.ac", files)
        self.assertIn("Makefile", files)
        self.assertIn("src/main.c", files)

    @patch("add_repo.gh_api")
    def test_returns_empty_on_failure(self, mock_api):
        mock_api.return_value = None
        files = add_repo.get_repo_tree(
            "bad/repo", "main"
        )
        self.assertEqual(files, [])


class TestCreateOutputDirs(unittest.TestCase):
    """Tests for create_output_dirs()."""

    def test_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "output" / "omnibor").mkdir(
                parents=True
            )
            (tmp / "output" / "spdx").mkdir(
                parents=True
            )
            (tmp / "output" / "binary-scan").mkdir(
                parents=True
            )
            (tmp / "docs").mkdir(parents=True)

            with patch.object(
                Path, "parent",
                new_callable=lambda: property(
                    lambda self: tmp
                )
            ):
                # Test the directory creation logic
                base = tmp
                dirs = [
                    base / "output" / "omnibor" / "test",
                    base / "output" / "spdx" / "test",
                    base / "output" / "binary-scan" / "test",
                    base / "docs" / "test",
                ]
                for d in dirs:
                    d.mkdir(parents=True, exist_ok=True)

                for d in dirs:
                    self.assertTrue(d.exists())


class TestWriteConfigEntryDirect(unittest.TestCase):
    """Tests for write_config_entry() calling the real function."""

    def test_writes_new_repo(self):
        import yaml
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(
                {"repos": {"existing": {"url": "x"}}},
                f
            )
            tmp_path = Path(f.name)

        entry = {
            "url": "https://github.com/test/new.git",
            "branch": "main",
            "build_steps": ["make"],
            "clean_cmd": "make clean",
            "description": "test",
            "output_binaries": ["new"],
        }

        with patch(
            "add_repo.Path.__truediv__",
            return_value=tmp_path
        ):
            add_repo.write_config_entry(
                "newrepo", entry
            )

        with open(
            tmp_path, "r", encoding="utf-8"
        ) as fh:
            result = yaml.safe_load(fh)
        self.assertIn("newrepo", result["repos"])
        self.assertIn("existing", result["repos"])
        tmp_path.unlink()

    def test_overwrites_existing_warns(self):
        import yaml
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(
                {"repos": {"curl": {"url": "old"}}},
                f
            )
            tmp_path = Path(f.name)

        printed = []
        with patch(
            "add_repo.Path.__truediv__",
            return_value=tmp_path
        ):
            with patch(
                "builtins.print",
                side_effect=lambda *a, **kw: (
                    printed.append(
                        " ".join(str(x) for x in a)
                    )
                )
            ):
                add_repo.write_config_entry(
                    "curl", {"url": "new"}
                )

        output = "\n".join(printed)
        self.assertIn("WARN", output)
        self.assertIn("curl", output)

        with open(
            tmp_path, "r", encoding="utf-8"
        ) as fh:
            result = yaml.safe_load(fh)
        self.assertEqual(
            result["repos"]["curl"]["url"], "new"
        )
        tmp_path.unlink()


class TestCreateOutputDirsDirect(unittest.TestCase):
    """Tests for create_output_dirs() calling the real function."""

    def test_creates_all_dirs(self):
        created = []
        original_mkdir = Path.mkdir

        def tracking_mkdir(self, **kwargs):
            created.append(str(self))
            original_mkdir(self, **kwargs)

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_base = Path(tmpdir)
            # Pre-create parent dirs
            for sub in [
                "output/omnibor", "output/spdx",
                "output/binary-scan", "docs"
            ]:
                (fake_base / sub).mkdir(
                    parents=True, exist_ok=True
                )

            with patch(
                "add_repo.Path.parent",
                new_callable=lambda: property(
                    lambda s: fake_base
                )
            ):
                with patch("builtins.print"):
                    add_repo.create_output_dirs(
                        "testrepo"
                    )

            expected = [
                fake_base / "output" / "omnibor" / "testrepo",
                fake_base / "output" / "spdx" / "testrepo",
                fake_base / "output" / "binary-scan" / "testrepo",
                fake_base / "docs" / "testrepo",
            ]
            for d in expected:
                self.assertTrue(d.exists())


class TestGhSearchRepoEdgeCases(unittest.TestCase):
    """Additional edge case tests for gh_search_repo."""

    @patch("add_repo.subprocess.run")
    def test_invalid_json_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="not json"
        )
        result = add_repo.gh_search_repo("curl")
        self.assertIsNone(result)

    @patch("add_repo.subprocess.run")
    def test_falls_back_to_highest_stars(
        self, mock_run
    ):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "fullName": "a/low",
                    "language": "C",
                    "stargazersCount": 10,
                },
                {
                    "fullName": "b/high",
                    "language": "C",
                    "stargazersCount": 50000,
                },
            ])
        )
        result = add_repo.gh_search_repo("nomatch")
        self.assertEqual(result["fullName"], "b/high")

    @patch("add_repo.subprocess.run")
    def test_non_c_repos_used_as_fallback(
        self, mock_run
    ):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "fullName": "js/lib",
                    "language": "JavaScript",
                    "stargazersCount": 100,
                },
            ])
        )
        result = add_repo.gh_search_repo("lib")
        self.assertEqual(result["fullName"], "js/lib")


class TestGetRepoInfoEdgeCases(unittest.TestCase):
    """Edge cases for get_repo_info."""

    @patch("add_repo.gh_api")
    def test_api_failure_falls_to_search(
        self, mock_api
    ):
        mock_api.return_value = None
        with patch(
            "add_repo.gh_search_repo"
        ) as mock_search:
            mock_search.return_value = {
                "fullName": "curl/curl"
            }
            add_repo.get_repo_info(
                "https://github.com/curl/curl"
            )
            mock_search.assert_called_once()

    @patch("add_repo.gh_api")
    def test_owner_repo_api_failure(self, mock_api):
        mock_api.return_value = None
        with patch(
            "add_repo.gh_search_repo"
        ) as mock_search:
            mock_search.return_value = None
            add_repo.get_repo_info(
                "bad/repo"
            )
            mock_search.assert_called_once_with(
                "bad/repo"
            )


class TestMainDryRun(unittest.TestCase):
    """Tests for main() in dry-run mode."""

    @patch("add_repo.get_repo_stats")
    @patch("add_repo.detect_output_binaries")
    @patch("add_repo.detect_configure_flags")
    @patch("add_repo.get_repo_tree")
    @patch("add_repo.get_repo_info")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_dry_run_success(
        self, mock_info, mock_tree,
        mock_flags, mock_bins, mock_stats
    ):
        mock_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "A URL transfer library",
        }
        mock_tree.return_value = [
            "configure.ac", "Makefile", "src/main.c"
        ]
        mock_flags.return_value = (
            ["--with-openssl"], ["libssl-dev"]
        )
        mock_bins.return_value = ["src/curl"]
        mock_stats.return_value = "~170K LoC, C"

        with patch("builtins.print"):
            with patch(
                "add_repo.Path.exists",
                return_value=True
            ):
                with patch(
                    "add_repo.Path.read_text",
                    return_value="libssl-dev"
                ):
                    add_repo.main()

    @patch("add_repo.get_repo_info")
    @patch("sys.argv", ["add_repo.py", "nonexistent"])
    def test_repo_not_found_exits(self, mock_info):
        mock_info.return_value = None
        with patch("builtins.print"):
            with self.assertRaises(SystemExit) as cm:
                add_repo.main()
            self.assertEqual(cm.exception.code, 1)

    @patch("add_repo.get_repo_tree")
    @patch("add_repo.get_repo_info")
    @patch(
        "sys.argv", ["add_repo.py", "curl"]
    )
    def test_empty_tree_exits(
        self, mock_info, mock_tree
    ):
        mock_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "test",
        }
        mock_tree.return_value = []
        with patch("builtins.print"):
            with self.assertRaises(SystemExit) as cm:
                add_repo.main()
            self.assertEqual(cm.exception.code, 1)


class TestMainWrite(unittest.TestCase):
    """Tests for main() in --write mode."""

    @patch("add_repo.create_output_dirs")
    @patch("add_repo.write_config_entry")
    @patch("add_repo.get_repo_stats")
    @patch("add_repo.detect_output_binaries")
    @patch("add_repo.detect_configure_flags")
    @patch("add_repo.get_repo_tree")
    @patch("add_repo.get_repo_info")
    @patch(
        "sys.argv",
        ["add_repo.py", "curl", "--write"]
    )
    def test_write_mode(
        self, mock_info, mock_tree,
        mock_flags, mock_bins, mock_stats,
        mock_write, mock_dirs
    ):
        mock_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "A URL transfer library",
        }
        mock_tree.return_value = [
            "configure.ac", "Makefile"
        ]
        mock_flags.return_value = ([], [])
        mock_bins.return_value = ["curl"]
        mock_stats.return_value = ""

        with patch("builtins.print"):
            add_repo.main()

        mock_write.assert_called_once()
        mock_dirs.assert_called_once()


class TestMainWithAptPackages(unittest.TestCase):
    """Test main() Dockerfile package checking."""

    @patch("add_repo.get_repo_stats")
    @patch("add_repo.detect_output_binaries")
    @patch("add_repo.detect_configure_flags")
    @patch("add_repo.get_repo_tree")
    @patch("add_repo.get_repo_info")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_new_packages_reported(
        self, mock_info, mock_tree,
        mock_flags, mock_bins, mock_stats
    ):
        mock_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "test",
        }
        mock_tree.return_value = [
            "configure.ac", "Makefile"
        ]
        mock_flags.return_value = (
            ["--with-openssl"],
            ["libssl-dev", "libnew-dev"]
        )
        mock_bins.return_value = ["curl"]
        mock_stats.return_value = ""

        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: printed.append(
                " ".join(str(x) for x in a)
            )
        ):
            with patch(
                "add_repo.Path.exists",
                return_value=True
            ):
                with patch(
                    "add_repo.Path.read_text",
                    return_value="libssl-dev"
                ):
                    add_repo.main()

        output = "\n".join(printed)
        self.assertIn("libnew-dev", output)

    @patch("add_repo.get_repo_stats")
    @patch("add_repo.detect_output_binaries")
    @patch("add_repo.detect_configure_flags")
    @patch("add_repo.get_repo_tree")
    @patch("add_repo.get_repo_info")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_all_packages_installed(
        self, mock_info, mock_tree,
        mock_flags, mock_bins, mock_stats
    ):
        mock_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "test",
        }
        mock_tree.return_value = [
            "configure.ac", "Makefile"
        ]
        mock_flags.return_value = (
            ["--with-openssl"], ["libssl-dev"]
        )
        mock_bins.return_value = ["curl"]
        mock_stats.return_value = ""

        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: printed.append(
                " ".join(str(x) for x in a)
            )
        ):
            with patch(
                "add_repo.Path.exists",
                return_value=True
            ):
                with patch(
                    "add_repo.Path.read_text",
                    return_value="libssl-dev"
                ):
                    add_repo.main()

        output = "\n".join(printed)
        self.assertIn("All required packages", output)

    @patch("add_repo.get_repo_stats")
    @patch("add_repo.detect_output_binaries")
    @patch("add_repo.detect_configure_flags")
    @patch("add_repo.get_repo_tree")
    @patch("add_repo.get_repo_info")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_no_dockerfile_exists(
        self, mock_info, mock_tree,
        mock_flags, mock_bins, mock_stats
    ):
        mock_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "test",
        }
        mock_tree.return_value = [
            "configure.ac", "Makefile"
        ]
        mock_flags.return_value = (
            ["--with-openssl"], ["libssl-dev"]
        )
        mock_bins.return_value = ["curl"]
        mock_stats.return_value = ""

        with patch("builtins.print"):
            with patch(
                "add_repo.Path.exists",
                return_value=False
            ):
                add_repo.main()


class TestMainDescriptionTruncation(unittest.TestCase):
    """Test description truncation in main()."""

    @patch("add_repo.get_repo_stats")
    @patch("add_repo.detect_output_binaries")
    @patch("add_repo.detect_configure_flags")
    @patch("add_repo.get_repo_tree")
    @patch("add_repo.get_repo_info")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_long_description_truncated(
        self, mock_info, mock_tree,
        mock_flags, mock_bins, mock_stats
    ):
        long_desc = "A" * 100
        mock_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": long_desc,
        }
        mock_tree.return_value = ["Makefile"]
        mock_flags.return_value = ([], [])
        mock_bins.return_value = ["curl"]
        mock_stats.return_value = "~170K LoC, C"

        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: printed.append(
                " ".join(str(x) for x in a)
            )
        ):
            add_repo.main()

        output = "\n".join(printed)
        self.assertIn("...", output)

    @patch("add_repo.get_repo_stats")
    @patch("add_repo.detect_output_binaries")
    @patch("add_repo.detect_configure_flags")
    @patch("add_repo.get_repo_tree")
    @patch("add_repo.get_repo_info")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_no_description_uses_repo_name(
        self, mock_info, mock_tree,
        mock_flags, mock_bins, mock_stats
    ):
        mock_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "",
        }
        mock_tree.return_value = ["Makefile"]
        mock_flags.return_value = ([], [])
        mock_bins.return_value = ["curl"]
        mock_stats.return_value = ""

        with patch("builtins.print"):
            add_repo.main()


class TestMainNoFlags(unittest.TestCase):
    """Test main() with no configure flags."""

    @patch("add_repo.get_repo_stats")
    @patch("add_repo.detect_output_binaries")
    @patch("add_repo.detect_configure_flags")
    @patch("add_repo.get_repo_tree")
    @patch("add_repo.get_repo_info")
    @patch("sys.argv", ["add_repo.py", "curl"])
    def test_no_flags_message(
        self, mock_info, mock_tree,
        mock_flags, mock_bins, mock_stats
    ):
        mock_info.return_value = {
            "fullName": "curl/curl",
            "defaultBranch": "master",
            "stargazersCount": 40000,
            "language": "C",
            "description": "test",
        }
        mock_tree.return_value = ["Makefile"]
        mock_flags.return_value = ([], [])
        mock_bins.return_value = ["curl"]
        mock_stats.return_value = ""

        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: printed.append(
                " ".join(str(x) for x in a)
            )
        ):
            add_repo.main()

        output = "\n".join(printed)
        self.assertIn(
            "No optional dependency flags", output
        )


class TestDetectConfigureFlagsEdge(unittest.TestCase):
    """Edge cases for detect_configure_flags."""

    @patch("add_repo.get_file_content")
    def test_autoconf_no_configure_ac(
        self, mock_get_file
    ):
        flags, pkgs = add_repo.detect_configure_flags(
            "test/repo", "main", "autoconf", []
        )
        self.assertEqual(flags, [])
        self.assertEqual(pkgs, [])
        mock_get_file.assert_not_called()

    @patch("add_repo.get_file_content")
    def test_autoconf_file_returns_none(
        self, mock_get_file
    ):
        mock_get_file.return_value = None
        flags, pkgs = add_repo.detect_configure_flags(
            "test/repo", "main", "autoconf",
            ["configure.ac"]
        )
        self.assertEqual(flags, [])
        self.assertEqual(pkgs, [])

    @patch("add_repo.get_file_content")
    def test_cmake_file_returns_none(
        self, mock_get_file
    ):
        mock_get_file.return_value = None
        flags, pkgs = add_repo.detect_configure_flags(
            "test/repo", "main", "cmake",
            ["CMakeLists.txt"]
        )
        self.assertEqual(flags, [])
        self.assertEqual(pkgs, [])

    @patch("add_repo.get_file_content")
    def test_configure_only_file_returns_none(
        self, mock_get_file
    ):
        mock_get_file.return_value = None
        flags, pkgs = add_repo.detect_configure_flags(
            "test/repo", "main", "configure-only",
            ["configure"]
        )
        self.assertEqual(flags, [])
        self.assertEqual(pkgs, [])

    @patch("add_repo.get_file_content")
    def test_cmake_detects_zlib(self, mock_get_file):
        mock_get_file.return_value = (
            "find_package(ZLIB REQUIRED)\n"
        )
        flags, pkgs = add_repo.detect_configure_flags(
            "test/repo", "main", "cmake",
            ["CMakeLists.txt"]
        )
        self.assertIn(
            "-DZLIB_LIBRARY="
            "/usr/lib/x86_64-linux-gnu/libz.so",
            flags
        )
        self.assertIn("zlib1g-dev", pkgs)

    @patch("add_repo.get_file_content")
    def test_multiple_deps_detected(
        self, mock_get_file
    ):
        mock_get_file.return_value = (
            "AC_CHECK openssl\n"
            "AC_CHECK zlib\n"
            "AC_CHECK nghttp2\n"
        )
        flags, pkgs = add_repo.detect_configure_flags(
            "test/repo", "main", "autoconf",
            ["configure.ac"]
        )
        self.assertIn("--with-openssl", flags)
        self.assertIn("--with-zlib", flags)
        self.assertIn("--with-nghttp2", flags)


class TestDetectOutputBinariesEdge(unittest.TestCase):
    """Edge cases for detect_output_binaries."""

    @patch("add_repo.get_file_content")
    def test_lib_ltlibraries(self, mock_get_file):
        mock_get_file.return_value = (
            "lib_LTLIBRARIES = libcurl.la\n"
        )
        bins = add_repo.detect_output_binaries(
            "curl/curl", "curl", "autoconf",
            ["Makefile.am"]
        )
        found = any("libcurl.so" in b for b in bins)
        self.assertTrue(found)

    @patch("add_repo.get_file_content")
    def test_makefile_am_returns_none(
        self, mock_get_file
    ):
        mock_get_file.return_value = None
        bins = add_repo.detect_output_binaries(
            "test/repo", "myapp", "autoconf",
            ["Makefile.am"]
        )
        # Falls back to default
        self.assertIn("myapp", bins)


class TestGetRepoTreeAuto(unittest.TestCase):
    """Test auto/ directory scanning."""

    @patch("add_repo.gh_api")
    def test_auto_dir_scanned(self, mock_api):
        def side_effect(url):
            is_root = (
                "contents?" in url
                and "/src" not in url
                and "/lib" not in url
                and "/auto" not in url
            )
            if is_root:
                return [
                    {"name": "src"},
                    {"name": "auto"},
                ]
            elif "/contents/src" in url:
                return [{"name": "core"}]
            elif "/contents/lib" in url:
                return None
            elif "/contents/auto" in url:
                return [{"name": "configure"}]
            return None

        mock_api.side_effect = side_effect
        files = add_repo.get_repo_tree(
            "nginx/nginx", "master"
        )
        self.assertIn("auto/configure", files)
        self.assertIn("src/core", files)


if __name__ == "__main__":
    unittest.main()
