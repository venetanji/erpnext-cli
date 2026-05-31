# Server-side execution — when REST isn't enough

REST covers ~90% of work. The remainder needs server context: `frappe.db.sql` aggregates,
filesystem/`import`, fine-grained transactions, and atomic multi-step operations. Two
mechanisms, both avoiding the old `docker cp` ceremony.

## A. Server Scripts (API type) — atomic multi-step over REST, no container

A Python snippet stored in the instance, callable as `POST /api/method/<api_method>` with
token auth. The **whole call is one transaction** → true atomicity (the canonical
cancel→amend chain, JE+PE+reconcile, etc.). No container, no app deploy.

### One-time enablement (the gotcha)

The gate is **`common_site_config.json`**, NOT per-site config. `bench set-config` without
`-g` writes the wrong file and the web workers keep refusing with *"Server Scripts are
disabled"* even though `frappe.conf` shows it set:

```bash
$EB bench set-config -g server_script_enabled 1          # -g = common_site_config.json
# then RECREATE the backend so gunicorn workers reload config, and the FRONTEND too:
docker compose -p <proj> -f pwd.yml up -d --force-recreate --no-deps backend frontend
```

### Deploying

Scripts live in `scripts/server_scripts/*.py`, each with a `# api_method: NAME` header.
`python3 scripts/deploy_server_scripts.py` idempotently upserts them over REST.

### Sandbox limits (RestrictedPython)

- **No `import`, no filesystem.** `frappe.parse_json` is **not** available either.
- Params arrive in `frappe.form_dict` **already parsed** from the JSON POST body (a list
  stays a list, a bool stays a bool) — don't try to parse them.
- Return data via `frappe.response["message"] = ...`.
- Available: `frappe.db.sql`, `frappe.db.get_value/set_value`, `frappe.get_doc`,
  `frappe.new_doc`, `frappe.copy_doc`, `frappe.get_list/get_all`, `delete_doc`, `rename_doc`,
  `msgprint`, `enqueue`, and doc methods (`.insert()/.submit()/.cancel()/.save()`).

### Shipped scripts

| api_method | What | Mutates? |
|---|---|---|
| `gl_balance` | net Dr-Cr balance + count for an account (SQL aggregate) | no |
| `account_ledger` | GL lines for an account in a date range, running balance | no |
| `cancel_and_amend_je` | atomic cancel→copy→apply changes→submit (sets `set_posting_time`, `amended_from`) | yes — **`dry_run` default true** |
| `reset_bank_txn_recon` | post-TDR: reset a Bank Transaction to Unreconciled | yes — **`dry_run` default true** |

Mutating scripts default to `dry_run:true` (return a preview). Pass `"dry_run":false` to act.

```bash
erp method gl_balance --json '{"account":"Bank - HSBC HKD Current 189-838 - SH"}'
erp method cancel_and_amend_je --json '{"name":"ACC-JV-2026-00001","changes":[{"idx":1,"account":"Rent - SH"}],"dry_run":true}'
```

## B. The `exec` hatch — bench execute / console, via the bind-mount

For raw SQL bulk, `import csv`/`pandas`, multi-savepoint transactions, or anything the
sandbox forbids. Code lives in the **bind-mounted** scripts dir (host
`scripts_bind_dir` ↔ container `scripts_container_dir`, on `PYTHONPATH`) — edit on the host,
run instantly, **no `docker cp`** and so no stale-file class of bug.

```bash
erp exec gl_tools.balance("Bank - HSBC HKD Current 189-838 - SH")   # bench execute, AUTO-COMMIT
erp exec --console adhoc_fix.py                                      # bench console (self-commit)
```

- **`erp exec module.function`** → `bench execute '__import__("module").function(...)'`.
  `bench execute` does `frappe.init` + **auto-commits** on success / rolls back on error.
  (Bare `bench execute module.func` fails for non-app modules — the `__import__` form is the
  working way to reach a PYTHONPATH module; the client builds it for you. Module = a flat
  `.py` in the bind dir.)
- **`erp exec --console file.py`** → pipes the file into `bench console` via **stdin**.
  `console` does **NOT** auto-commit — the script must call `frappe.db.commit()` itself, and
  IPython silently buffers `print` / drops trailing writes (write results to a file or use
  `bench execute` instead).
- **Avoid bare `env/bin/python script.py` with `frappe.init(site=...)`** — it needs an
  explicit absolute `sites_path` and still trips on a logging-path quirk. `bench execute` is
  the correct primitive; it sets all of that up.

### One-time bind-mount (in `pwd.yml`, backend service)

```yaml
    volumes:
      - sites:/home/frappe/frappe-bench/sites
      - logs:/home/frappe/frappe-bench/logs
      - /host/erpnext/cli-scripts:/home/frappe/frappe-bench/cli-scripts:ro   # add
    environment:
      ...
      PYTHONPATH: /home/frappe/frappe-bench/cli-scripts                       # add
```
Then `docker compose -p <proj> -f pwd.yml up -d --no-deps backend`. uid 1000 matches host↔
container, so `:ro` files are readable without chmod.

## ⚠️ Operational gotchas (learned the hard way)

1. **Recreating `backend` breaks the `frontend` nginx upstream → 502.** The frontend caches
   the backend's container IP. After any `up -d --force-recreate backend`, also
   `restart frontend` (or recreate both together). A plain `restart backend` for config
   reload has the same effect — bounce the frontend after.
2. **`server_script_enabled` must be global** (`-g` → common_site_config.json) and needs a
   backend recreate to take effect (see above).
3. **Config changes need a worker reload.** Editing `site_config`/`common_site_config`
   doesn't hot-apply to running gunicorn workers — recreate the backend.
4. **`bench console` ≠ auto-commit; `bench execute` = auto-commit.** Use `execute` for
   anything scripted/repeatable.
