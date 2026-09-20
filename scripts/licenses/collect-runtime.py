"""Collect installed runtime license evidence without assuming metadata proves compliance."""

import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

NOTICE_NAME = re.compile(r"^(?:MIT[-_])?(licen[cs]e|copying|copyright|notice|authors|ofl)([._-]|$)", re.I)


def declared_license(metadata) -> str:
    explicit = metadata.get("License-Expression") or metadata.get("License")
    if explicit:
        return explicit
    classifiers = {"MIT License": "MIT", "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0"}
    for label, expression in classifiers.items():
        if f"License :: OSI Approved :: {label}" in metadata.get_all("Classifier", []):
            return expression
    return "UNKNOWN"


def copy_evidence(paths: list[tuple[Path, str]], destination: Path) -> list[dict[str, str]]:
    evidence = []
    for source, relative in sorted(paths):
        if not source.is_file():
            continue
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"Unsafe license evidence path: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        evidence.append({"path": relative, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    return evidence


def collect_python(output: Path) -> list[dict]:
    records = []
    for dist in importlib.metadata.distributions():
        name, version = dist.metadata["Name"], dist.version
        paths = []
        for file in dist.files or []:
            if NOTICE_NAME.match(file.name) or "licenses" in file.parts:
                paths.append((Path(dist.locate_file(file)), f"{name}@{version}/{file}"))
        # Include the metadata as evidence of declared license and upstream source.
        metadata = next((file for file in dist.files or [] if file.name == "METADATA"), None)
        if metadata:
            paths.append((Path(dist.locate_file(metadata)), f"{name}@{version}/METADATA"))
        evidence = copy_evidence(paths, output)
        has_license = any(not entry["path"].endswith("/METADATA") for entry in evidence)
        records.append(
            {
                "name": name,
                "version": version,
                "license": declared_license(dist.metadata),
                "classifiers": dist.metadata.get_all("Classifier", []),
                "source": dist.metadata.get_all("Project-URL", []) or dist.metadata.get("Home-page", "UNKNOWN"),
                "evidence": evidence,
                "review": (
                    "human review required; embedded binary components need separate verification"
                    if has_license
                    else "MISSING LICENSE TEXT; review required"
                ),
            }
        )
    license_path = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
    if not license_path.is_file():
        raise RuntimeError("Python runtime LICENSE.txt is missing")
    copy_evidence([(license_path, "python-runtime/LICENSE.txt")], output)
    return records


def collect_ruby(output: Path) -> list[dict]:
    command = [
        "ruby",
        "-rbundler/setup",
        "-rjson",
        "-e",
        """
specs = (Bundler.load.specs.to_a + [Gem::Specification.find_by_name('bundler')]).uniq
puts JSON.generate(specs.map { |s| { name: s.name, version: s.version.to_s,
  platform: s.platform.to_s, license: s.licenses, source: s.homepage, root: s.full_gem_path } })
""",
    ]
    records = json.loads(subprocess.check_output(command, text=True))
    for record in records:
        root = Path(record.pop("root"))
        prefix = f"{record['name']}@{record['version']}"
        paths = [(p, f"{prefix}/{p.relative_to(root)}") for p in root.rglob("*") if NOTICE_NAME.match(p.name)]
        record["evidence"] = copy_evidence(paths, output)
        record["review"] = "human review required" if paths else "MISSING LICENSE TEXT; review required"
    return records


def collect_system(output: Path) -> list[dict]:
    fmt = "${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\\n"
    packages = subprocess.check_output(["dpkg-query", "-W", f"-f={fmt}"], text=True)
    records = []
    for line in packages.splitlines():
        name, version, source, source_version = line.split("\t")
        copyright_path = Path("/usr/share/doc") / name.split(":")[0] / "copyright"
        records.append(
            {
                "name": name,
                "version": version,
                "source_package": source,
                "source_version": source_version,
                "license": "See retained Debian copyright file",
                "evidence": copy_evidence([(copyright_path, f"{name}/copyright")], output),
                "review": (
                    "corresponding-source obligations require review before binary redistribution"
                    if copyright_path.is_file()
                    else "MISSING LICENSE TEXT; review required"
                ),
            }
        )
    return records


def apply_supplemental(records: list[dict], directory: Path, output: Path) -> None:
    manifest = json.loads((directory / "inventory.json").read_text())
    packages = {(record["name"], record["version"]): record for record in records}
    for entry in manifest["packages"]:
        record = packages.get((entry["name"], entry["version"]))
        if record is None:
            continue
        for file in entry["evidence"]:
            source = directory / file["path"]
            if not source.resolve().is_relative_to(directory.resolve()):
                raise ValueError("Unsafe supplemental license path")
            if hashlib.sha256(source.read_bytes()).hexdigest() != file["sha256"]:
                raise ValueError(f"Supplemental license checksum mismatch: {entry['name']}")
            evidence = copy_evidence([(source, f"supplemental/{file['path']}")], output)
            record["evidence"].extend({**item, "source": entry["source"]} for item in evidence)
        record["review"] = entry.get("review", "supplemental original text collected; human review required")


def main() -> None:
    if len(sys.argv) not in {3, 4} or sys.argv[1] not in {"python", "ruby", "system"}:
        raise SystemExit("usage: collect-runtime.py {python|ruby|system} OUTPUT [SUPPLEMENTAL]")
    scope, output = sys.argv[1], Path(sys.argv[2])
    output.mkdir(parents=True, exist_ok=True)
    collectors = {"python": collect_python, "ruby": collect_ruby, "system": collect_system}
    records = collectors[scope](output)
    if len(sys.argv) == 4:
        apply_supplemental(records, Path(sys.argv[3]), output)
    if not records:
        raise RuntimeError(f"no installed {scope} packages found")
    inventory = {"scope": scope, "platform": platform.platform(), "packages": records}
    (output / "inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    print(f"Collected {len(records)} {scope} runtime package notices")


if __name__ == "__main__":
    main()
