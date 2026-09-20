"""Record Trellis 0.6.15 template origins against a separately downloaded source archive."""

import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

PREFIX = "packages/cli/src/templates/"


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def generated_source(local: str) -> str:
    if local.endswith("/SKILL.md"):
        name = local.split("/")[-2].removeprefix("trellis-")
        folder = "commands" if name in {"start", "continue", "finish-work"} else "skills"
        if name in {"implement", "check"} and local.startswith(".kimi-code/"):
            return PREFIX + f"trellis/agents/{name}.md"
        return PREFIX + f"common/{folder}/{name}.md"
    if "/commands/" in local or "/prompts/" in local:
        name = Path(local).name.removeprefix("trellis-")
        return PREFIX + f"common/commands/{name}"
    if "/agents/" in local:
        platform = local.split("/")[0][1:].replace("kimi-code", "kimi")
        return PREFIX + f"{platform}/agents/{Path(local).name}"
    return PREFIX + local.removeprefix(".")


def inventory(archive_path: Path) -> list[str]:
    with tarfile.open(archive_path) as archive:
        upstream = {
            member.name.split("/", 1)[1]: archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        }
    hashes = json.loads(Path(".trellis/.template-hashes.json").read_text())["hashes"]
    rows = ["local_path\tupstream_path\tupstream_sha256\tinstalled_sha256\tcurrent_sha256\tstatus\tlast_commit_date"]
    for local, installed_hash in sorted(hashes.items()):
        content = Path(local).read_bytes()
        current_hash = digest(content)
        exact = sorted(p for p, data in upstream.items() if p.startswith(PREFIX) and data == content)
        source = exact[0] if exact else generated_source(local)
        if source not in upstream:
            raise RuntimeError(f"No verified upstream path for {local}: {source}")
        status = "verbatim" if exact else "generated-adaptation"
        if installed_hash != current_hash:
            status = "locally-modified"
        date = subprocess.check_output(["git", "log", "-1", "--format=%cs", "--", local], text=True).strip()
        rows.append("\t".join([local, source, digest(upstream[source]), installed_hash, current_hash, status, date]))
    return rows


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: trellis-provenance.py /path/to/Trellis-v0.6.15.tar.gz (run at repository root)")
    rows = inventory(Path(sys.argv[1]))
    Path("licenses/trellis/FILES.tsv").write_text("\n".join(rows) + "\n")
    print(f"Recorded {len(rows) - 1} Trellis template paths")
