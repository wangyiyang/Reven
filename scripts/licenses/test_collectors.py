"""Regression tests for preserving nested notices and explicit unknown license evidence."""

import email.message
import hashlib
import importlib.util
import json
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


class LicenseCollectionTest(unittest.TestCase):
    def test_ruby_keeps_prefixed_license_filenames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "MIT-LICENSE.txt").write_text("Original gem license and attribution")
            package = {"name": "example", "version": "1.0.0", "root": str(root)}
            with patch.object(RUNTIME.subprocess, "check_output", return_value=json.dumps([package])):
                records = RUNTIME.collect_ruby(root / "output")
            self.assertEqual(len(records[0]["evidence"]), 1)
            copied = root / "output" / records[0]["evidence"][0]["path"]
            self.assertEqual(copied.read_text(), "Original gem license and attribution")

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
            (project / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
            store = project / "node_modules/.pnpm"
            for name in ["has-notices", "no-notices"]:
                root = store / f"{name}@1.0.0/node_modules" / name
                root.mkdir(parents=True)
                (root / "package.json").write_text(json.dumps({"name": name, "version": "1.0.0"}))
            notice = store / "has-notices@1.0.0/node_modules/has-notices/embedded/NOTICE"
            notice.parent.mkdir()
            notice.write_text("Keep embedded component attribution\n")
            output = project / "output"
            subprocess.run(["node", str(SCRIPTS / "collect-js.mjs"), str(project), str(output)], check=True)
            records = {p["name"]: p for p in json.loads((output / "inventory.json").read_text())["packages"]}
            self.assertEqual(records["has-notices"]["license"], "UNKNOWN")
            copied = output / records["has-notices"]["evidence"][0]["path"]
            self.assertEqual(copied.read_text(), notice.read_text())
            self.assertIn("MISSING LICENSE TEXT", records["no-notices"]["review"])

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
