#!/usr/bin/env python3
"""
Tests for app/analyze.py — class-based analysis pipeline.

Uses unittest.mock to avoid real subprocess calls.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add app/ to path so we can import analyze
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

import analyze
from analyze import (
    CommandRunner, DependencyValidator,
    RepoCloner, BomtraceBuilder,
    SpdxGenerator, SyftGenerator, DocWriter,
    AnalysisPipeline, load_config, timestamp,
)


# ============================================================
# Utilities
# ============================================================

class TestLoadConfig(unittest.TestCase):
    """Tests for load_config()."""

    def test_loads_real_config(self):
        config = load_config()
        self.assertIn("repos", config)
        self.assertIn("paths", config)
        self.assertIn("omnibor", config)

    def test_loads_custom_path(self):
        import yaml
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            yaml.dump({"test": True}, f)
            tmp = Path(f.name)
        result = load_config(tmp)
        self.assertTrue(result["test"])
        tmp.unlink()


class TestTimestamp(unittest.TestCase):
    """Tests for timestamp()."""

    def test_format(self):
        ts = timestamp()
        self.assertRegex(
            ts, r"\d{4}-\d{2}-\d{2}_\d{4}"
        )


# ============================================================
# CommandRunner
# ============================================================

class TestCommandRunner(unittest.TestCase):
    """Tests for CommandRunner."""

    @patch("analyze.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="ok\n",
        )
        runner = CommandRunner()
        with patch("builtins.print"):
            rc = runner.run(
                "echo hello", description="test"
            )
        self.assertEqual(rc, 0)

    @patch("analyze.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="fail\n",
        )
        runner = CommandRunner()
        with patch("builtins.print"):
            rc = runner.run(
                "false", description="fail test"
            )
        self.assertEqual(rc, 1)

    @patch("analyze.subprocess.run")
    def test_cwd_passed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="",
        )
        runner = CommandRunner()
        with patch("builtins.print"):
            runner.run(
                "ls", cwd="/tmp",
                description="cwd test",
            )
        mock_run.assert_called_once()
        self.assertEqual(
            mock_run.call_args.kwargs.get("cwd")
            or mock_run.call_args[1].get("cwd"),
            "/tmp",
        )

    @patch("analyze.subprocess.run")
    def test_prints_error_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=42, stdout="",
        )
        runner = CommandRunner()
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            runner.run("bad", description="x")
        output = "\n".join(printed)
        self.assertIn("42", output)


# ============================================================
# DependencyValidator
# ============================================================

class TestDependencyValidator(unittest.TestCase):
    """Tests for DependencyValidator."""

    def test_no_apt_deps(self):
        runner = MagicMock()
        v = DependencyValidator(runner)
        ok, missing = v.validate({})
        self.assertTrue(ok)
        self.assertEqual(missing, [])
        runner.run.assert_not_called()

    def test_empty_apt_deps(self):
        runner = MagicMock()
        v = DependencyValidator(runner)
        ok, missing = v.validate({"apt_deps": []})
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_all_installed(self):
        runner = MagicMock()
        runner.run.return_value = 0
        v = DependencyValidator(runner)
        with patch("builtins.print"):
            ok, missing = v.validate(
                {"apt_deps": ["libssl-dev", "zlib1g-dev"]}
            )
        self.assertTrue(ok)
        self.assertEqual(missing, [])
        self.assertEqual(runner.run.call_count, 2)

    def test_some_missing(self):
        runner = MagicMock()
        runner.run.side_effect = [0, 1, 0]
        v = DependencyValidator(runner)
        with patch("builtins.print"):
            ok, missing = v.validate(
                {"apt_deps": [
                    "libssl-dev", "libpsl-dev",
                    "zlib1g-dev",
                ]}
            )
        self.assertFalse(ok)
        self.assertEqual(missing, ["libpsl-dev"])

    def test_all_missing(self):
        runner = MagicMock()
        runner.run.return_value = 1
        v = DependencyValidator(runner)
        with patch("builtins.print"):
            ok, missing = v.validate(
                {"apt_deps": ["a", "b"]}
            )
        self.assertFalse(ok)
        self.assertEqual(missing, ["a", "b"])

    def test_prints_install_hint(self):
        runner = MagicMock()
        runner.run.return_value = 1
        v = DependencyValidator(runner)
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            v.validate({"apt_deps": ["libfoo-dev"]})
        output = "\n".join(printed)
        self.assertIn("apt-get install", output)
        self.assertIn("libfoo-dev", output)


# ============================================================
# RepoCloner
# ============================================================

class TestRepoCloner(unittest.TestCase):
    """Tests for RepoCloner."""

    def test_skips_existing_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_dir = Path(tmpdir) / "myrepo"
            repo_dir.mkdir()
            (repo_dir / "file.txt").touch()

            runner = MagicMock()
            cloner = RepoCloner(runner)
            paths = {"repos_dir": tmpdir}
            cfg = {"url": "x", "branch": "main"}

            with patch("builtins.print"):
                result = cloner.clone(
                    "myrepo", cfg, paths
                )
            self.assertEqual(
                result, str(repo_dir)
            )
            runner.run.assert_not_called()

    def test_clones_new_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            runner.run.return_value = 0
            cloner = RepoCloner(runner)
            paths = {"repos_dir": tmpdir}
            cfg = {
                "url": "https://github.com/x/y.git",
                "branch": "main",
            }

            cloner.clone("newrepo", cfg, paths)
            runner.run.assert_called_once()
            call_args = runner.run.call_args
            self.assertIn("git clone", call_args[0][0])
            self.assertIn("main", call_args[0][0])

    def test_default_branch_master(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            runner.run.return_value = 0
            cloner = RepoCloner(runner)
            paths = {"repos_dir": tmpdir}
            cfg = {"url": "https://github.com/x/y.git"}

            cloner.clone("repo", cfg, paths)
            call_args = runner.run.call_args
            self.assertIn("master", call_args[0][0])


# ============================================================
# BomtraceBuilder
# ============================================================

class TestBomtraceBuilder(unittest.TestCase):
    """Tests for BomtraceBuilder."""

    def _cfg(self):
        return (
            {
                "build_steps": [
                    "autoreconf -fi",
                    "./configure",
                    "make -j4",
                ],
                "clean_cmd": "make clean",
            },
            {"repos_dir": "/repos", "output_dir": "/out"},
            {
                "tracer": "bomtrace3",
                "raw_logfile": "/tmp/log",
                "create_bom_script": "/usr/bin/bom",
            },
        )

    def test_success(self):
        runner = MagicMock()
        runner.run.return_value = 0
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertTrue(result)
        # clean + 2 pre-build + instrumented + ADG = 5
        self.assertEqual(runner.run.call_count, 5)

    def test_success_no_clean_cmd(self):
        runner = MagicMock()
        runner.run.return_value = 0
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()
        del repo_cfg["clean_cmd"]

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertTrue(result)
        # no clean + 2 pre-build + instrumented + ADG = 4
        self.assertEqual(runner.run.call_count, 4)

    def test_prebuild_failure(self):
        runner = MagicMock()
        # clean ok, first pre-build fails
        runner.run.side_effect = [0, 1]
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertFalse(result)

    def test_make_failure(self):
        runner = MagicMock()
        # clean ok, 2 pre-build ok, instrumented fails
        runner.run.side_effect = [0, 0, 0, 1]
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertFalse(result)

    def test_adg_failure(self):
        runner = MagicMock()
        # clean ok, 2 pre-build ok, instrumented ok, ADG fails
        runner.run.side_effect = [0, 0, 0, 0, 1]
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertFalse(result)

    def test_clean_failure_ignored(self):
        runner = MagicMock()
        # clean fails (fresh clone), rest succeeds
        runner.run.side_effect = [1, 0, 0, 0, 0]
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            result = builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        self.assertTrue(result)

    def test_instrumented_cmd_uses_tracer(self):
        runner = MagicMock()
        runner.run.return_value = 0
        builder = BomtraceBuilder(runner)
        repo_cfg, paths, omnibor = self._cfg()

        with patch("builtins.print"):
            builder.build(
                "curl", repo_cfg, paths, omnibor
            )
        # clean(0) + pre-build(1,2) + instrumented(3)
        instrumented_call = runner.run.call_args_list[3]
        self.assertIn(
            "bomtrace3", instrumented_call[0][0]
        )


# ============================================================
# SpdxGenerator
# ============================================================

class TestSpdxGenerator(unittest.TestCase):
    """Tests for SpdxGenerator."""

    def test_generate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            runner.run.return_value = 0
            gen = SpdxGenerator(runner)
            paths = {"output_dir": tmpdir}
            omnibor = {
                "sbom_script": "/usr/bin/sbom",
                "raw_logfile": "/tmp/log",
            }

            with patch("builtins.print"):
                result = gen.generate(
                    "curl", paths, omnibor
                )
            self.assertIn("curl_omnibor_", result)
            self.assertIn(".spdx.json", result)
            runner.run.assert_called_once()

    def test_generate_warns_on_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            runner.run.return_value = 1
            gen = SpdxGenerator(runner)
            paths = {"output_dir": tmpdir}
            omnibor = {
                "sbom_script": "x",
                "raw_logfile": "y",
            }

            printed = []
            with patch(
                "builtins.print",
                side_effect=lambda *a, **kw: (
                    printed.append(
                        " ".join(str(x) for x in a)
                    )
                ),
            ):
                gen.generate("curl", paths, omnibor)
            output = "\n".join(printed)
            self.assertIn("WARN", output)


# ============================================================
# SyftGenerator
# ============================================================

class TestSyftGenerator(unittest.TestCase):
    """Tests for SyftGenerator."""

    def test_generate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            runner.run.return_value = 0
            gen = SyftGenerator(runner)
            paths = {
                "repos_dir": tmpdir,
                "output_dir": tmpdir,
            }

            with patch("builtins.print"):
                result = gen.generate("curl", paths)
            self.assertIn("curl_syft_", result)
            self.assertIn(".spdx.json", result)

    def test_generate_warns_on_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = MagicMock()
            runner.run.return_value = 1
            gen = SyftGenerator(runner)
            paths = {
                "repos_dir": tmpdir,
                "output_dir": tmpdir,
            }

            printed = []
            with patch(
                "builtins.print",
                side_effect=lambda *a, **kw: (
                    printed.append(
                        " ".join(str(x) for x in a)
                    )
                ),
            ):
                gen.generate("curl", paths)
            output = "\n".join(printed)
            self.assertIn("WARN", output)


# ============================================================
# DocWriter
# ============================================================

class TestDocWriter(unittest.TestCase):
    """Tests for DocWriter."""

    def test_write_build_doc_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            cfg = {
                "url": "https://github.com/x/y.git",
                "branch": "main",
                "description": "test repo",
                "build_steps": ["./configure", "make"],
                "output_binaries": ["bin/app"],
            }
            with patch("builtins.print"):
                result = DocWriter.write_build_doc(
                    "myrepo", cfg, paths,
                    True, 42.5,
                )
            self.assertTrue(Path(result).exists())
            content = Path(result).read_text()
            self.assertIn("SUCCESS", content)
            self.assertIn("42.5", content)
            self.assertIn("myrepo", content)
            self.assertIn("bin/app", content)

    def test_write_build_doc_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            cfg = {
                "url": "x",
                "build_steps": ["make"],
            }
            with patch("builtins.print"):
                result = DocWriter.write_build_doc(
                    "repo", cfg, paths,
                    False, 10.0,
                )
            content = Path(result).read_text()
            self.assertIn("FAILED", content)

    def test_write_runtime_doc(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            with patch("builtins.print"):
                result = DocWriter.write_runtime_doc(
                    "myrepo", paths, 55.3,
                )
            self.assertTrue(Path(result).exists())
            content = Path(result).read_text()
            self.assertIn("55.3", content)
            self.assertIn("myrepo", content)

    def test_write_runtime_doc_with_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            with patch("builtins.print"):
                result = DocWriter.write_runtime_doc(
                    "repo", paths, 60.0,
                    baseline_sec=30.0,
                )
            content = Path(result).read_text()
            self.assertIn("100.0%", content)

    def test_write_runtime_doc_no_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {"docs_dir": tmpdir}
            with patch("builtins.print"):
                result = DocWriter.write_runtime_doc(
                    "repo", paths, 60.0,
                    baseline_sec=None,
                )
            content = Path(result).read_text()
            self.assertNotIn("overhead", content)


# ============================================================
# AnalysisPipeline
# ============================================================

class TestAnalysisPipeline(unittest.TestCase):
    """Tests for AnalysisPipeline facade."""

    def test_default_construction(self):
        p = AnalysisPipeline()
        self.assertIsInstance(p.runner, CommandRunner)
        self.assertIsInstance(
            p.validator, DependencyValidator
        )
        self.assertIsInstance(p.cloner, RepoCloner)
        self.assertIsInstance(
            p.builder, BomtraceBuilder
        )
        self.assertIsInstance(
            p.spdx_gen, SpdxGenerator
        )
        self.assertIsInstance(
            p.syft_gen, SyftGenerator
        )
        self.assertIsInstance(p.docs, DocWriter)

    def test_injected_components(self):
        runner = MagicMock()
        p = AnalysisPipeline(runner=runner)
        self.assertIs(p.runner, runner)

    def test_list_repos(self):
        config = {
            "repos": {
                "curl": {
                    "description": "URL lib",
                    "url": "https://github.com/curl/curl.git",
                },
            }
        }
        printed = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **kw: (
                printed.append(
                    " ".join(str(x) for x in a)
                )
            ),
        ):
            AnalysisPipeline.list_repos(config)
        output = "\n".join(printed)
        self.assertIn("curl", output)
        self.assertIn("URL lib", output)


# ============================================================
# main() CLI
# ============================================================

def _mock_pipeline():
    """Create an AnalysisPipeline with all mocked components."""
    runner = MagicMock()
    validator = MagicMock()
    validator.validate.return_value = (True, [])
    cloner = MagicMock()
    builder = MagicMock()
    spdx_gen = MagicMock()
    syft_gen = MagicMock()
    doc_writer = MagicMock()
    return AnalysisPipeline(
        runner=runner,
        validator=validator,
        cloner=cloner,
        builder=builder,
        spdx_gen=spdx_gen,
        syft_gen=syft_gen,
        doc_writer=doc_writer,
    )


class TestMainList(unittest.TestCase):
    """Tests for main() --list mode."""

    @patch("analyze.AnalysisPipeline")
    @patch("sys.argv", ["analyze.py", "--list"])
    def test_list_mode(self, mock_cls):
        p = MagicMock()
        mock_cls.return_value = p
        with patch("builtins.print"):
            analyze.main()
        p.list_repos.assert_called_once()


class TestMainNoRepo(unittest.TestCase):
    """Tests for main() without --repo."""

    @patch("analyze.AnalysisPipeline")
    @patch("sys.argv", ["analyze.py"])
    def test_exits_without_repo(self, mock_cls):
        mock_cls.return_value = _mock_pipeline()
        with patch("builtins.print"):
            with self.assertRaises(
                SystemExit
            ) as cm:
                analyze.main()
            self.assertEqual(cm.exception.code, 1)


class TestMainUnknownRepo(unittest.TestCase):
    """Tests for main() with unknown repo."""

    @patch("analyze.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "nonexistent"],
    )
    def test_exits_unknown_repo(self, mock_cls):
        mock_cls.return_value = _mock_pipeline()
        with patch("builtins.print"):
            with self.assertRaises(
                SystemExit
            ) as cm:
                analyze.main()
            self.assertEqual(cm.exception.code, 1)


class TestMainFullRun(unittest.TestCase):
    """Tests for main() full analysis run."""

    @patch("analyze.time.time")
    @patch("analyze.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "curl"],
    )
    def test_full_run_success(
        self, mock_cls, mock_time
    ):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.builder.build.return_value = True
        mock_time.side_effect = [100.0, 142.5]

        with patch("builtins.print"):
            analyze.main()

        p.cloner.clone.assert_called_once()
        p.syft_gen.generate.assert_called_once()
        p.validator.validate.assert_called_once()
        p.builder.build.assert_called_once()
        p.spdx_gen.generate.assert_called_once()
        p.docs.write_build_doc.assert_called_once()
        p.docs.write_runtime_doc.assert_called_once()

    @patch("analyze.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "curl"],
    )
    def test_validation_failure_exits(
        self, mock_cls
    ):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.validator.validate.return_value = (
            False, ["libpsl-dev"]
        )

        with patch("builtins.print"):
            with self.assertRaises(
                SystemExit
            ) as cm:
                analyze.main()
            self.assertEqual(cm.exception.code, 1)

        p.builder.build.assert_not_called()

    @patch("analyze.time.time")
    @patch("analyze.AnalysisPipeline")
    @patch(
        "sys.argv",
        ["analyze.py", "--repo", "curl"],
    )
    def test_full_run_build_failure(
        self, mock_cls, mock_time
    ):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.builder.build.return_value = False
        mock_time.side_effect = [100.0, 110.0]

        with patch("builtins.print"):
            analyze.main()

        p.spdx_gen.generate.assert_not_called()
        p.docs.write_build_doc.assert_called_once()

    @patch("analyze.time.time")
    @patch("analyze.AnalysisPipeline")
    @patch(
        "sys.argv",
        [
            "analyze.py", "--repo", "curl",
            "--skip-clone",
        ],
    )
    def test_skip_clone(self, mock_cls, mock_time):
        p = _mock_pipeline()
        mock_cls.return_value = p
        p.builder.build.return_value = True
        mock_time.side_effect = [100.0, 110.0]

        with patch("builtins.print"):
            analyze.main()

        p.cloner.clone.assert_not_called()

    @patch("analyze.AnalysisPipeline")
    @patch(
        "sys.argv",
        [
            "analyze.py", "--repo", "curl",
            "--syft-only",
        ],
    )
    def test_syft_only(self, mock_cls):
        p = _mock_pipeline()
        mock_cls.return_value = p

        with patch("builtins.print"):
            analyze.main()

        p.syft_gen.generate.assert_called_once()
        p.builder.build.assert_not_called()
        p.spdx_gen.generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
