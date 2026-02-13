"""Tests for spdx_from_adg module."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, str(Path(__file__).parent.parent / "app")
)

from spdx_from_adg import (
    AdgParser,
    AdgSpdxGenerator,
    ComponentResolver,
    SpdxEmitter,
)


class TestAdgParser(unittest.TestCase):
    """Tests for AdgParser."""

    def _setup_bom_dir(self, td):
        meta = (
            Path(td) / "bom" / "metadata" / "bomsh"
        )
        meta.mkdir(parents=True)
        return meta

    def test_classify_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "aaa": {
                    "file_path": (
                        "/usr/lib/x86_64/libssl.so"
                    ),
                },
                "bbb": {
                    "file_path": (
                        "/usr/include/openssl/ssl.h"
                    ),
                },
                "ccc": {
                    "file_path": (
                        "/repos/curl/src/main.c"
                    ),
                },
                "ddd": {
                    "file_path": (
                        "/repos/curl/src/main.o"
                    ),
                    "build_cmd": "gcc -c main.c",
                },
                "eee": {
                    "file_path": (
                        "/usr/lib/x86_64/crtbeginS.o"
                    ),
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )

            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse()

            self.assertEqual(
                len(result["system_lib"]), 1
            )
            self.assertEqual(
                len(result["system_header"]), 1
            )
            self.assertEqual(
                len(result["project_source"]), 1
            )
            self.assertEqual(
                len(result["build_intermediate"]), 1
            )
            self.assertEqual(
                len(result["crt_object"]), 1
            )
            # build_cmd preserved
            self.assertIn(
                "build_cmd",
                result["build_intermediate"][0],
            )

    def test_load_doc_mapping(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            mapping = {"abc123": "doc456"}
            (
                meta / "bomsh_omnibor_doc_mapping"
            ).write_text(json.dumps(mapping))

            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.load_doc_mapping()
            self.assertEqual(
                result["abc123"], "doc456"
            )

    def test_load_doc_mapping_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup_bom_dir(td)
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.load_doc_mapping()
            self.assertEqual(result, {})

    def test_load_raw_logfile_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            sha = "a" * 40
            (
                meta / "bomsh_hook_raw_logfile"
            ).write_text(
                f"outfile: {sha} path: /repo/curl\n"
                "some other line\n"
            )

            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.load_raw_logfile_hashes()
            self.assertEqual(result["/repo/curl"], sha)
            self.assertEqual(len(result), 1)

    def test_load_raw_logfile_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self._setup_bom_dir(td)
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.load_raw_logfile_hashes()
            self.assertEqual(result, {})

    def test_classify_empty_filepath(self):
        """Entries with empty file_path are skipped."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "aaa": {"file_path": ""},
                "bbb": {},
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse()
            total = sum(
                len(v) for v in result.values()
            )
            self.assertEqual(total, 0)

    def test_classify_static_lib(self):
        """Static .a files under /usr/lib are system_lib."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "aaa": {
                    "file_path": (
                        "/usr/lib/x86_64/libfoo.a"
                    ),
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse()
            self.assertEqual(
                len(result["system_lib"]), 1
            )

    def test_classify_other_system_file(self):
        """Files outside /usr/lib, /usr/include, repos."""
        with tempfile.TemporaryDirectory() as td:
            meta = self._setup_bom_dir(td)
            treedb = {
                "aaa": {
                    "file_path": "/opt/custom/lib.h",
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            parser = AdgParser(
                str(Path(td) / "bom"), "/repos"
            )
            result = parser.parse()
            self.assertEqual(
                len(result["system_header"]), 1
            )


class TestComponentResolver(unittest.TestCase):
    """Tests for ComponentResolver."""

    def _write_metadata(self, td, metadata):
        path = Path(td) / "component_metadata.json"
        path.write_text(json.dumps(metadata))
        return str(path)

    def _base_metadata(self):
        return {
            "distro": "Ubuntu 22.04.5 LTS",
            "gcc_version": "gcc (Ubuntu 11.4.0) 11.4.0",
            "curl_version": "8.19.0-DEV",
            "pkg_metadata": {
                "libssl3": {
                    "Package": "libssl3",
                    "Version": "3.0.2-0ubuntu1.21",
                    "Source": "openssl",
                    "Maintainer": "Ubuntu Developers",
                    "Homepage": "https://www.openssl.org/",
                    "Architecture": "amd64",
                },
                "zlib1g-dev": {
                    "Package": "zlib1g-dev",
                    "Version": "1:1.2.11.dfsg-2ubuntu9.2",
                    "Source": "zlib",
                    "Maintainer": "Ubuntu Developers",
                    "Homepage": "http://zlib.net/",
                    "Architecture": "amd64",
                },
            },
            "file_to_pkg": {
                "/usr/lib/libssl.so": "libssl3",
                "/usr/lib/libcrypto.so": "libssl3",
                "/usr/include/zlib.h": "zlib1g-dev",
            },
            "unresolved_files": [],
        }

    def test_resolve_components(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path)

            artifacts = [
                {"sha1": "a1", "file_path": "/usr/lib/libssl.so"},
                {"sha1": "a2", "file_path": "/usr/lib/libcrypto.so"},
                {"sha1": "a3", "file_path": "/usr/include/zlib.h"},
            ]
            components = (
                resolver.resolve_system_components(
                    artifacts
                )
            )
            self.assertEqual(len(components), 2)
            names = [c["name"] for c in components]
            self.assertIn("openssl", names)
            self.assertIn("zlib", names)

    def test_purl_format(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path)

            artifacts = [
                {"sha1": "a1", "file_path": "/usr/lib/libssl.so"},
            ]
            components = (
                resolver.resolve_system_components(
                    artifacts
                )
            )
            purl = components[0]["purl"]
            self.assertIn("pkg:deb/ubuntu/", purl)
            self.assertIn("distro=ubuntu-22.04", purl)
            self.assertIn("arch=amd64", purl)

    def test_cpe_format(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path)

            artifacts = [
                {"sha1": "a1", "file_path": "/usr/lib/libssl.so"},
            ]
            components = (
                resolver.resolve_system_components(
                    artifacts
                )
            )
            cpe = components[0]["cpe23"]
            self.assertTrue(
                cpe.startswith("cpe:2.3:a:")
            )
            self.assertIn("openssl", cpe)
            self.assertIn("3.0.2", cpe)

    def test_clean_version(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path)

            # Epoch removal
            self.assertEqual(
                resolver._clean_version(
                    "1:1.2.11.dfsg-2ubuntu9.2"
                ),
                "1.2.11",
            )
            # dfsg removal
            self.assertEqual(
                resolver._clean_version(
                    "1.4.8+dfsg-3build1"
                ),
                "1.4.8",
            )
            # Simple version
            self.assertEqual(
                resolver._clean_version("3.0.2-0ubuntu1.21"),
                "3.0.2",
            )

    def test_distro_codename(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path)
            self.assertEqual(
                resolver.distro_codename,
                "ubuntu-22.04",
            )

    def test_unresolved_artifacts_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            meta = self._base_metadata()
            path = self._write_metadata(td, meta)
            resolver = ComponentResolver(path)

            artifacts = [
                {"sha1": "x", "file_path": "/unknown/path"},
            ]
            components = (
                resolver.resolve_system_components(
                    artifacts
                )
            )
            self.assertEqual(len(components), 0)


class TestSpdxEmitter(unittest.TestCase):
    """Tests for SpdxEmitter."""

    def test_emit_basic_structure(self):
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            bomtrace_version="6.11",
            bomsh_version="0.0.1-abc",
        )
        doc = emitter.emit(
            components=[],
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
        )
        self.assertEqual(
            doc["spdxVersion"], "SPDX-2.3"
        )
        self.assertEqual(
            doc["dataLicense"], "CC0-1.0"
        )
        self.assertIn(
            "omnibor.io",
            doc["documentNamespace"],
        )
        self.assertEqual(
            doc["SPDXID"], "SPDXRef-DOCUMENT"
        )
        # Root package + gcc = 2
        self.assertEqual(len(doc["packages"]), 2)
        # DESCRIBES + BUILD_TOOL_OF = 2
        self.assertEqual(
            len(doc["relationships"]), 2
        )

    def test_emit_with_components(self):
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
        )
        components = [{
            "name": "openssl",
            "version": "3.0.2",
            "supplier": "Ubuntu Developers",
            "homepage": "https://www.openssl.org/",
            "dpkg_packages": ["libssl3"],
            "architecture": "amd64",
            "purl": "pkg:deb/ubuntu/libssl3@3.0.2",
            "cpe23": "cpe:2.3:a:openssl:openssl:3.0.2:*:*:*:*:*:*:*",
            "files": ["/usr/lib/libssl.so"],
        }]
        doc = emitter.emit(
            components=components,
            project_files=[],
            doc_mapping={},
            logfile_hashes={},
        )
        # Root + openssl + gcc = 3
        self.assertEqual(len(doc["packages"]), 3)
        ssl_pkg = doc["packages"][1]
        self.assertEqual(ssl_pkg["name"], "openssl")
        ref_types = [
            r["referenceType"]
            for r in ssl_pkg["externalRefs"]
        ]
        self.assertIn("purl", ref_types)
        self.assertIn("cpe23Type", ref_types)

    def test_emit_with_omnibor_ref(self):
        sha = "a" * 40
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
        )
        doc = emitter.emit(
            components=[],
            project_files=[],
            doc_mapping={sha: "omnibor_doc_123"},
            logfile_hashes={
                "/repo/src/.libs/curl": sha,
            },
        )
        root = doc["packages"][0]
        gitoid_refs = [
            r for r in root["externalRefs"]
            if "gitoid" in r.get(
                "referenceLocator", ""
            )
        ]
        self.assertEqual(len(gitoid_refs), 1)
        self.assertIn(
            "omnibor_doc_123",
            gitoid_refs[0]["referenceLocator"],
        )

    def test_emit_with_source_files(self):
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
        )
        project_files = [
            {"sha1": "abc", "file_path": "/repos/curl/src/main.c"},
            {"sha1": "def", "file_path": "/repos/curl/src/util.h"},
            {"sha1": "ghi", "file_path": "/repos/curl/Makefile"},
        ]
        doc = emitter.emit(
            components=[],
            project_files=project_files,
            doc_mapping={},
            logfile_hashes={},
        )
        # .c and .h included, Makefile excluded
        self.assertEqual(len(doc["files"]), 2)
        fnames = [
            f["fileName"] for f in doc["files"]
        ]
        self.assertTrue(
            any("main.c" in f for f in fnames)
        )

    def test_creators(self):
        emitter = SpdxEmitter(
            repo_name="curl",
            repo_version="8.19.0",
            distro="Ubuntu 22.04",
            gcc_version="gcc 11.4.0",
            bomtrace_version="6.11-dirty",
            bomsh_version="0.0.1-abc",
        )
        doc = emitter.emit(
            components=[], project_files=[],
            doc_mapping={}, logfile_hashes={},
        )
        creators = doc["creationInfo"]["creators"]
        self.assertIn(
            "Tool: bomtrace3-6.11-dirty", creators
        )
        self.assertIn(
            "Tool: bomsh-0.0.1-abc", creators
        )
        self.assertTrue(
            any("omnibor-analysis" in c for c in creators)
        )


class TestComponentResolverEdgeCases(
    unittest.TestCase
):
    """Edge-case tests for ComponentResolver."""

    def test_non_ubuntu_distro_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            meta = {
                "distro": "Debian GNU/Linux 12",
                "gcc_version": "gcc 12",
                "curl_version": "8.0",
                "pkg_metadata": {},
                "file_to_pkg": {},
                "unresolved_files": [],
            }
            path = Path(td) / "meta.json"
            path.write_text(json.dumps(meta))
            resolver = ComponentResolver(str(path))
            self.assertEqual(
                resolver.distro_codename, "linux"
            )


class TestAdgSpdxGenerator(unittest.TestCase):
    """Tests for AdgSpdxGenerator facade."""

    def _setup_full(self, td):
        """Create a complete test environment."""
        bom = Path(td) / "bom"
        meta = bom / "metadata" / "bomsh"
        meta.mkdir(parents=True)

        sha = "a" * 40
        treedb = {
            sha: {
                "file_path": "/repos/curl/src/main.c",
            },
            "b" * 40: {
                "file_path": "/usr/lib/libssl.so",
            },
        }
        (meta / "bomsh_omnibor_treedb").write_text(
            json.dumps(treedb)
        )
        (meta / "bomsh_omnibor_doc_mapping").write_text(
            json.dumps({sha: "omnibor_doc"})
        )
        (meta / "bomsh_hook_raw_logfile").write_text(
            f"outfile: {sha} path: /repos/curl\n"
        )

        comp_meta = {
            "distro": "Ubuntu 22.04",
            "gcc_version": "gcc 11.4.0",
            "curl_version": "8.19.0",
            "pkg_metadata": {
                "libssl3": {
                    "Package": "libssl3",
                    "Version": "3.0.2",
                    "Source": "openssl",
                    "Maintainer": "Ubuntu",
                    "Homepage": "https://openssl.org",
                    "Architecture": "amd64",
                },
            },
            "file_to_pkg": {
                "/usr/lib/libssl.so": "libssl3",
            },
            "unresolved_files": [],
        }
        (bom / "metadata" / "component_metadata.json").write_text(
            json.dumps(comp_meta)
        )

        return str(bom)

    def test_generate_success(self):
        with tempfile.TemporaryDirectory() as td:
            bom_dir = self._setup_full(td)
            out = str(
                Path(td) / "out" / "curl.spdx.json"
            )

            gen = AdgSpdxGenerator(
                bom_dir=bom_dir,
                repos_dir="/repos",
                repo_name="curl",
                bomtrace_version="6.11",
                bomsh_version="0.0.1",
            )
            with patch("builtins.print"):
                result = gen.generate(out)

            self.assertIsNotNone(result)
            doc = json.loads(Path(out).read_text())
            self.assertEqual(
                doc["spdxVersion"], "SPDX-2.3"
            )
            # Root + openssl + gcc = 3
            self.assertEqual(
                len(doc["packages"]), 3
            )

    def test_generate_missing_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            bom = Path(td) / "bom"
            meta = bom / "metadata" / "bomsh"
            meta.mkdir(parents=True)
            treedb = {
                "aaa": {
                    "file_path": "/repos/curl/x.c"
                },
            }
            (
                meta / "bomsh_omnibor_treedb"
            ).write_text(json.dumps(treedb))
            (
                meta / "bomsh_omnibor_doc_mapping"
            ).write_text("{}")
            out = str(
                Path(td) / "out" / "curl.spdx.json"
            )

            gen = AdgSpdxGenerator(
                bom_dir=str(bom),
                repos_dir="/repos",
                repo_name="curl",
            )
            with patch("builtins.print"):
                result = gen.generate(out)

            self.assertIsNone(result)


class TestCli(unittest.TestCase):
    """Tests for CLI main() function."""

    def test_main_success(self):
        from spdx_from_adg import main
        with tempfile.TemporaryDirectory() as td:
            # Reuse full setup from generator test
            bom = Path(td) / "bom"
            meta = bom / "metadata" / "bomsh"
            meta.mkdir(parents=True)
            sha = "a" * 40
            treedb = {
                sha: {
                    "file_path": "/repos/curl/src/x.c",
                },
            }
            (meta / "bomsh_omnibor_treedb").write_text(
                json.dumps(treedb)
            )
            (
                meta / "bomsh_omnibor_doc_mapping"
            ).write_text(json.dumps({}))
            comp_meta = {
                "distro": "Ubuntu 22.04",
                "gcc_version": "gcc 11.4.0",
                "curl_version": "8.19.0",
                "pkg_metadata": {},
                "file_to_pkg": {},
                "unresolved_files": [],
            }
            (
                bom / "metadata"
                / "component_metadata.json"
            ).write_text(json.dumps(comp_meta))

            out = str(
                Path(td) / "out" / "curl.spdx.json"
            )
            args = [
                "--bom-dir", str(bom),
                "--repos-dir", "/repos",
                "--repo-name", "curl",
                "--output", out,
                "--bomtrace-version", "6.11",
                "--bomsh-version", "0.0.1",
            ]
            with patch(
                "sys.argv",
                ["spdx_from_adg.py"] + args,
            ), patch("builtins.print"):
                main()

            self.assertTrue(Path(out).exists())

    def test_main_failure(self):
        from spdx_from_adg import main
        with tempfile.TemporaryDirectory() as td:
            bom = Path(td) / "bom"
            meta = bom / "metadata" / "bomsh"
            meta.mkdir(parents=True)
            (
                meta / "bomsh_omnibor_treedb"
            ).write_text(json.dumps({}))
            (
                meta / "bomsh_omnibor_doc_mapping"
            ).write_text(json.dumps({}))
            # No component_metadata.json
            out = str(
                Path(td) / "out" / "curl.spdx.json"
            )
            args = [
                "--bom-dir", str(bom),
                "--repos-dir", "/repos",
                "--repo-name", "curl",
                "--output", out,
            ]
            with patch(
                "sys.argv",
                ["spdx_from_adg.py"] + args,
            ), patch("builtins.print"):
                with self.assertRaises(SystemExit):
                    main()


if __name__ == "__main__":
    unittest.main()
