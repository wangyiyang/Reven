from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_smoke_health_check_needs_no_credentials(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "argv.json"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "record = {'argv': sys.argv, 'environment': dict(os.environ)}\n"
        "pathlib.Path(os.environ['ARGV_RECORD']).write_text(json.dumps(record))\n"
        'print(\'{"service":"reven","status":"ok"}\')\n',
        encoding="utf-8",
    )
    fake_curl.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ARGV_RECORD": str(record),
        "REVEN_BASE_URL": "https://dev.example.test",
        "TMPDIR": str(tmp_path),
    }
    for key in ("REVEN_BASIC_AUTH_USER", "REVEN_BASIC_AUTH_PASSWORD"):
        environment.pop(key, None)

    result = subprocess.run(
        ["bash", "scripts/smoke.sh"],
        cwd=Path(__file__).parents[3],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0
    argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
    assert "--netrc-file" not in argv
    assert "--user" not in argv
