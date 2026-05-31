#!/usr/bin/env python3
"""Idempotently deploy the API-type Server Scripts in ./server_scripts/ to the
ERPNext instance over REST (no container). Each file's first `# api_method: NAME`
line names the endpoint (POST /api/method/NAME). Re-running updates the script body.

Requires `server_script_enabled` in the instance's common_site_config.json
(set once: `bench set-config -g server_script_enabled 1` + restart backend).

Usage:  python3 deploy_server_scripts.py [--list]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from erpnext_client import ERPNextClient, ERPNextError  # noqa: E402

SS_DIR = Path(__file__).resolve().parent / "server_scripts"


def parse(p: Path) -> tuple[str, str]:
    text = p.read_text()
    api = None
    for line in text.splitlines():
        if line.strip().startswith("# api_method:"):
            api = line.split(":", 1)[1].strip()
            break
    if not api:
        raise ERPNextError(f"{p.name}: missing `# api_method:` header")
    return api, text


def main():
    c = ERPNextClient()
    for p in sorted(SS_DIR.glob("*.py")):
        api, script = parse(p)
        if c.exists("Server Script", [["name", "=", api]]):
            c.set_value("Server Script", api, {"script": script, "disabled": 0})
            print(f"↻ updated {api}")
        else:
            c.insert({"doctype": "Server Script", "name": api, "script_type": "API",
                      "api_method": api, "disabled": 0, "script": script})
            print(f"+ created {api}")


if __name__ == "__main__":
    try:
        main()
    except ERPNextError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
