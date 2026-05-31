# erpnext-cli

A **REST-first swiss-army CLI + Python client** for a running ERPNext/Frappe instance,
built for bookkeeping / audit-reconstruction automation. Packaged as a
[Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills) but runs standalone
from any shell.

## Why

The token-auth REST/RPC API does ~90% of automation work — reads, single-doc CRUD,
submit/cancel, whitelisted/factory methods, reports, file-attach-as-URL — with **no
`docker exec` and no file copy**, each call its own auto-committed transaction. The
old `docker compose cp + exec + cat` ceremony (~4× the characters of a REST call, and the
source of stale-file bugs) is reserved for genuine server-side python, and even that loses
the `docker cp` via a bind-mounted scripts dir. Atomic multi-step operations (the
cancel→amend chain) become a single REST call through an API-type **Server Script**.

## Skills

| Skill | Covers |
|---|---|
| [`erpnext-cli`](skills/erpnext-cli/SKILL.md) | The CLI verbs, the REST/RPC surface (filters, reports, hard rules), and server-side execution (the `exec` bench hatch, the bind-mount, Server Scripts, and the operational gotchas). |

### Layout

```
skills/erpnext-cli/
├── SKILL.md
├── CONTRIBUTING.md
├── references/
│   ├── api.md            # REST/RPC surface, filters, reports, hard rules
│   └── server-side.md    # exec hatch, bind-mount, Server Scripts, gotchas
└── scripts/
    ├── erpnext_client.py        # the library
    ├── erp                      # the CLI
    ├── deploy_server_scripts.py # idempotent Server Script deploy
    ├── server_scripts/*.py      # API-type Server Scripts (gl_balance, cancel_and_amend_je, …)
    ├── cli-scripts-examples/    # bench-execute helpers for the bind-mounted dir
    └── config.example.json
```

## Install

```bash
git clone https://github.com/venetanji/erpnext-cli.git ~/.claude/skills-source/erpnext-cli
ln -s ~/.claude/skills-source/erpnext-cli/skills/erpnext-cli ~/.claude/skills/erpnext-cli
ln -s ~/.claude/skills/erpnext-cli/scripts/erp ~/.local/bin/erp     # optional: on PATH
mkdir -p ~/.config/erpnext-cli
cp skills/erpnext-cli/scripts/config.example.json ~/.config/erpnext-cli/config.json
# edit base_url, api_key/secret, site, compose_*, bind paths
erp ping
```

The `exec`/Server-Script paths need a one-time bind-mount + `server_script_enabled`
(see `references/server-side.md`). REST works without them.

## Scope & versioning

- Targets Frappe/ERPNext v14–v16 (built against v16). Read-oriented + controlled writes for
  reconstruction; not a replacement for the desk UI.
- **No client-specific data** in committed code — it all lives in the gitignored config.

## License

MIT (to be added).
