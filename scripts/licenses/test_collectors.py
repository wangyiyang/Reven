"""Regression tests for preserving nested notices and explicit unknown license evidence."""

import email.message
import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("collect_runtime", SCRIPTS / "collect-runtime.py")
assert SPEC and SPEC.loader
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def javascript_fixture(project: Path) -> dict[str, Path]:
    (project / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    store = project / "node_modules/.pnpm"
    roots = {}
    for name in ("has-notices", "no-notices", "dev-tool", "retired-package"):
        root = store / f"{name}@1.0.0/node_modules" / name
        root.mkdir(parents=True)
        package = {"name": name, "version": "1.0.0"}
        if name == "dev-tool":
            package.update(license="MIT", repository="https://example.invalid/dev-tool")
        (root / "package.json").write_text(json.dumps(package, indent=2) + "\n")
        (root / "dist.js").write_text("throw new Error('package code must not be copied');\n")
        roots[name] = root
    (roots["has-notices"] / "LICENSE").write_bytes(b"Keep original license text\r\n")
    notice = roots["has-notices"] / "embedded/NOTICE"
    notice.parent.mkdir()
    notice.write_bytes(b"Keep embedded component attribution\r\n")
    (roots["dev-tool"] / "LICENSE").write_bytes(b"Development tool attribution\n")
    tree = [
        {
            "dependencies": {
                "has-notices": {
                    "path": str(roots["has-notices"]),
                    "dependencies": {"no-notices": {"path": str(roots["no-notices"])}},
                }
            },
            "devDependencies": {"dev-tool": {"path": str(roots["dev-tool"])}},
        }
    ]
    fixture = project / "dependency-tree.json"
    fixture.write_text(json.dumps(tree))
    executable = project / "pnpm"
    executable.write_text(f"#!/bin/sh\ncat {shlex.quote(str(fixture))}\n")
    executable.chmod(0o755)
    return roots


def collect_javascript(project: Path, output: Path) -> dict:
    subprocess.run(
        ["node", str(SCRIPTS / "collect-js.mjs"), str(project), str(output)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{project}{os.pathsep}{os.environ['PATH']}"},
    )
    return json.loads((output / "inventory.json").read_text())


class LicenseCollectionTest(unittest.TestCase):
    def test_supplemental_text_is_version_matched_and_checksum_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "LICENSE"
            original.write_text("Verified upstream license")
            entry = {
                "name": "example",
                "version": "1.0.0",
                "source": "https://example.invalid/v1/LICENSE",
                "review": "LICENSE CONFLICT: retain unresolved upstream terms",
                "evidence": [{"path": "LICENSE", "sha256": "incorrect"}],
            }
            manifest = root / "inventory.json"
            manifest.write_text(json.dumps({"packages": [entry]}))
            record = {"name": "example", "version": "1.0.0", "evidence": []}
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                RUNTIME.apply_supplemental([record], root, root / "output")
            entry["evidence"][0]["sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
            manifest.write_text(json.dumps({"packages": [entry]}))
            other = {"name": "example", "version": "2.0.0", "evidence": []}
            RUNTIME.apply_supplemental([record, other], root, root / "output")
            self.assertEqual(other["evidence"], [])
            self.assertEqual(len(record["evidence"]), 1)
            self.assertIn("LICENSE CONFLICT", record["review"])
            copied = root / "output" / record["evidence"][0]["path"]
            self.assertEqual(copied.read_bytes(), original.read_bytes())

    def test_javascript_preserves_nested_notices_and_marks_missing_text(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            roots = javascript_fixture(project)
            output = project / "output"
            records = {p["name"]: p for p in collect_javascript(project, output)["packages"]}
            self.assertEqual(records["has-notices"]["license"], "UNKNOWN")
            self.assertEqual(len(records["has-notices"]["evidence"]), 2)
            for evidence in records["has-notices"]["evidence"]:
                relative = Path(evidence["path"]).relative_to("packages/has-notices@1.0.0")
                original = (roots["has-notices"] / relative).read_bytes()
                self.assertEqual((output / evidence["path"]).read_bytes(), original)
                self.assertEqual(evidence["sha256"], hashlib.sha256(original).hexdigest())
            self.assertIn("MISSING LICENSE TEXT", records["no-notices"]["review"])
            self.assertNotIn("retired-package", records)

    def test_javascript_records_manifest_hash_without_packaging_manifests_or_code(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            roots = javascript_fixture(project)
            output = project / "output"
            inventory = collect_javascript(project, output)
            records = {package["name"]: package for package in inventory["packages"]}
            self.assertEqual(set(records), {"has-notices", "no-notices", "dev-tool"})
            for name, record in records.items():
                raw = (roots[name] / "package.json").read_bytes()
                self.assertEqual(record["manifest_sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(record["version"], "1.0.0")
                self.assertIn("evidence", record)
            self.assertEqual(records["dev-tool"]["license"], "MIT")
            self.assertEqual(records["dev-tool"]["source"], "https://example.invalid/dev-tool")
            self.assertTrue(records["dev-tool"]["evidence"])
            self.assertEqual(
                inventory["lockfile"]["sha256"], hashlib.sha256((project / "pnpm-lock.yaml").read_bytes()).hexdigest()
            )
            self.assertEqual(list(output.rglob("package.json")), [])
            self.assertEqual(list(output.rglob("dist.js")), [])

    def test_javascript_only_removes_its_identical_legacy_package_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            roots = javascript_fixture(project)
            output = project / "output"
            legacy = output / "packages/has-notices@1.0.0/package.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes((roots["has-notices"] / "package.json").read_bytes())
            unrelated = output / "package.json"
            unrelated.write_bytes(b"unrelated user file\n")
            collect_javascript(project, output)
            self.assertFalse(legacy.exists())
            self.assertEqual(unrelated.read_bytes(), b"unrelated user file\n")

    def test_javascript_does_not_remove_an_unrecognized_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            javascript_fixture(project)
            output = project / "output"
            legacy = output / "packages/has-notices@1.0.0/package.json"
            legacy.parent.mkdir(parents=True)
            original = b"unrecognized contents\n"
            legacy.write_bytes(original)
            with self.assertRaises(subprocess.CalledProcessError) as error:
                collect_javascript(project, output)
            self.assertIn("Unrecognized legacy package manifest", error.exception.stderr)
            self.assertEqual(legacy.read_bytes(), original)

    def test_python_retains_distinct_nested_license_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [Path("example.dist-info/licenses/one/LICENSE"), Path("example.dist-info/licenses/two/LICENSE")]
            for index, path in enumerate(paths):
                (root / path).parent.mkdir(parents=True)
                (root / path).write_text(f"Component {index} attribution")
            (root / "LICENSE.txt").write_text("Python license fixture")

            class Distribution:
                metadata = email.message.Message()
                metadata["Name"] = "example"
                version = "1.0.0"
                files = paths

                def locate_file(self, path):
                    return root / path

            with patch.object(RUNTIME.importlib.metadata, "distributions", return_value=[Distribution()]):
                with patch.object(RUNTIME.sysconfig, "get_path", return_value=str(root)):
                    records = RUNTIME.collect_python(root / "output")
            evidence = records[0]["evidence"]
            self.assertEqual(len(evidence), 2)
            self.assertNotEqual(evidence[0]["path"], evidence[1]["path"])
            self.assertNotEqual(evidence[0]["sha256"], evidence[1]["sha256"])


if __name__ == "__main__":
    unittest.main()
