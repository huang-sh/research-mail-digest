#!/usr/bin/env python3
"""Check whether agently-cli is installed and authorized."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


def run_command(command: list[str], timeout: int = 15) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": 124,
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": "command timed out",
        }


def parse_me(stdout: str) -> dict[str, Any]:
    start = stdout.find("{")
    if start == -1:
        return {}
    try:
        return json.loads(stdout[start:])
    except json.JSONDecodeError:
        return {}


def main() -> int:
    agently_path = shutil.which("agently-cli")
    status: dict[str, Any] = {
        "installed": bool(agently_path),
        "authorized": False,
        "ready": False,
        "agently_cli_path": agently_path,
        "email": None,
        "next_step": None,
    }

    if not agently_path:
        status["next_step"] = "install_cli"
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 1

    me_result = run_command(["agently-cli", "+me"])
    status["me_returncode"] = me_result["returncode"]
    if me_result["returncode"] == 0:
        payload = parse_me(me_result["stdout"])
        aliases = payload.get("data", {}).get("aliases", []) if payload.get("ok") else []
        primary = next((alias for alias in aliases if alias.get("is_primary")), aliases[0] if aliases else {})
        status.update(
            {
                "authorized": bool(payload.get("ok")),
                "ready": bool(payload.get("ok")),
                "email": primary.get("email"),
                "next_step": None,
            }
        )
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0

    status["next_step"] = "authorize"
    status["error"] = {
        "stdout": me_result["stdout"],
        "stderr": me_result["stderr"],
    }
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
