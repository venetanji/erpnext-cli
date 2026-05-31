# Contributing to erpnext-cli

Three extension points. Keep it **generic** (no company data in committed code) and
**REST-first** (reach for the container only when REST genuinely can't do it).

## Architecture

```
scripts/
  erpnext_client.py        # the library: config, REST/RPC, exec hatch. Import it.
  erp                      # the CLI: argparse subparsers, one cmd_<name>(args, c) per verb.
  deploy_server_scripts.py # idempotently upserts server_scripts/*.py over REST.
  server_scripts/*.py      # API-type Server Scripts (each has a `# api_method:` header).
  cli-scripts-examples/    # example bench-execute helpers for the bind-mounted dir.
  config.example.json
```

`config.json` lives in `$ERP_HOME` (default `~/.config/erpnext-cli`) — **never committed**
(holds api_secret + deployment paths). Only `config.example.json` is.

## A. Add a CLI subcommand

In `scripts/erp`, write `cmd_<name>(args, c)` (c = `ERPNextClient`) and register it in
`main()` via `add("name", cmd_name, "<positional>", flag={"...argparse..."})`:

```python
def cmd_resubmit(args, c):
    """resubmit a cancelled doc by cancel+amend"""
    _out(c.method("cancel_and_amend_je", name=args.name, dry_run=False))

add("resubmit", cmd_resubmit, "name")
```

Rules: return REST results via `_out`; let `ERPNextError` propagate (main() prints it
cleanly); prefer existing flags; **respect the hard rules** in `references/api.md` (GL is
read-only, POST isn't idempotent, cancel+amend not fixing-JEs).

## B. Add a Server Script (atomic, REST-callable, no container)

Drop a file in `server_scripts/` with a `# api_method: NAME` header, then
`python3 deploy_server_scripts.py`. Honour the sandbox (see `references/server-side.md`):
**no `import`, no filesystem, no `parse_json`** — params arrive pre-parsed in
`frappe.form_dict`; return via `frappe.response["message"]`. Mutating scripts MUST default to
`dry_run:true` and return a preview.

## C. Add a bench-execute helper (server-side python)

For raw SQL / filesystem / bulk loops. Put a flat module with functions in your
`scripts_bind_dir` (host), then `erp exec module.function(args)`. `bench execute`
auto-commits. Keep modules flat (no packages), idempotent, and log progress to a file (not
just stdout). See `cli-scripts-examples/gl_tools.py`.

## Genericization rules

- No company names / account names / GUIDs / absolute home paths in committed code — those
  go in `config.json` (gitignored) or command arguments.
- Examples in docs use placeholders (`SleepHere HK` is illustrative only).
- Date-stamp version-specific behaviour (e.g. the `common_site_config` server-script gate).

## Quality bar

- `python3 -c "import erpnext_client"` imports clean (stdlib only).
- `erp ping` works; new REST verbs exercised against a live instance.
- Server Scripts deployed via `deploy_server_scripts.py` and the `dry_run` path tested.
- No secrets / client identifiers in the diff (`git diff` and look).
