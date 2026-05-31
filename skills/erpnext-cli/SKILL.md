---
name: erpnext-cli
description: Use when reading or writing a running ERPNext/Frappe instance from the command line or scripts — looking up / listing / counting documents, creating or updating docs, submitting/cancelling, running query reports, calling whitelisted (incl. ERPNext factory) methods, attaching Drive URLs, or running server-side python (frappe.db.sql aggregates, atomic multi-step transactions) without the docker-exec + file-copy ceremony. Generic over any token-authenticated ERPNext instance.
---

# erpnext-cli

A REST-first swiss-army CLI + client for a running ERPNext/Frappe instance, built
for bookkeeping / audit-reconstruction automation.

**Core principle: REST-first, container-last.** ~90% of work (reads, single-doc
CRUD, submit/cancel, whitelisted methods, reports, file-attach-as-URL) goes over the
token-auth REST/RPC API — **no `docker exec`, no file copy** — and each POST is its own
auto-committed transaction. The container is touched only for genuine server-side python,
and even that avoids `docker cp` via a bind-mounted scripts dir.

## When to use

- "Look up / list / count Sales Invoices, JEs, Accounts, …" → `erp get|list|count`
- "Create / update / submit / cancel a doc" → `erp insert|set-value|submit|cancel`
- "Run the Trial Balance / a query report" → `erp report`
- "Call get_payment_entry / make_sales_invoice / any whitelisted method" → `erp method`
- "Attach a Drive PDF to a PI" → `erp attach`
- "Net Dr-Cr balance on an account" / aggregates REST can't do → a **Server Script** (`erp method gl_balance`) or `erp exec`
- "Cancel + amend a JE atomically" → the `cancel_and_amend_je` Server Script (one transaction)
- A bulk loop, raw SQL, or filesystem/import → `erp exec module.function` (bench execute, auto-commit)
- Loading a batch from a file (csv/xlsx) → `erp data-import` (native engine) or `erp import` (fast REST loop)

**Not for: parsing source documents.** Turning a bank-statement or utility-bill **PDF** into
rows is client- and format-specific and belongs in a back-office runbook skill (e.g.
`shicheng-agents`), which parses PDF → csv/xlsx and then calls `erp data-import`/`erp import`.
This CLI stays format-agnostic — it drives ERPNext, it does not read PDFs.

## Setup (per instance)

`$ERP_HOME` (default `~/.config/erpnext-cli`) holds `config.json` — **secrets, never
committed** (copy `scripts/config.example.json`):

```json
{ "base_url":"http://localhost:8080", "api_key":"...","api_secret":"...",
  "site":"frontend", "compose_project":"...","compose_file":"/abs/pwd.yml",
  "container_service":"backend",
  "scripts_bind_dir":"/host/erpnext/cli-scripts",
  "scripts_container_dir":"/home/frappe/frappe-bench/cli-scripts",
  "bench_dir":"/home/frappe/frappe-bench" }
```

For the `exec`/Server-Script paths, do the **one-time** infra setup in
`references/server-side.md` (bind-mount + `server_script_enabled`).

## Quick reference

| Command | Does (all REST, no container) |
|---|---|
| `erp ping` | auth + identity check |
| `erp doctor [--fix] [--quiet]` | background-worker/queue health; `--fix` restarts dead workers (cron-friendly) |
| `erp get <DocType> <name>` | one document |
| `erp list <DocType> [--filters JSON] [--fields JSON] [--order-by S] [--limit N]` | `frappe.client.get_list` |
| `erp count <DocType> [--filters JSON]` | count |
| `erp report <Name> [--filters JSON]` | query report |
| `erp schema <DocType> [--all]` | live field schema (standard **+ custom** fields, with reqd/unique/link flags) |
| `erp doctypes [--custom] [--module M]` | discover doctypes (e.g. the custom ones) |
| `erp insert <DocType> --json '{…}' [--unique '[["bill_no","=","X"]]']` | create (idempotent if `--unique`) |
| `erp set-value <DocType> <name> <field> <value>` | update one field |
| `erp submit\|cancel\|delete <DocType> <name>` | lifecycle |
| `erp method <dotted.path> [--json '{…}']` | any whitelisted / ERPNext factory method, or a Server Script API |
| `erp doc-method <method> <DocType> <name> [--json '{…}']` | run a controller method on a doc |
| `erp attach <DocType> <name> <url> [--filename N]` | attach a URL (no byte copy) |
| `erp add-field <DocType> <fieldname> <fieldtype> [--label --after --options --reqd --unique --read-only --force]` | add a Custom Field (idempotent) |
| `erp set-prop <DocType> <field> <property> <value> [--type T] [--doctype-prop]` | tweak a field/doctype property via Property Setter (no code) |
| `erp import <DocType> <file.{json,jsonl,csv,xlsx}> [--key F --update --submit --limit N --dry-run]` | fast bulk loop (each row its own txn; `--key` = idempotent skip/update) |
| `erp data-import <DocType> <file.{csv,xlsx}> [--update --submit --attach-pdf URL --no-wait]` | ERPNext's **native Data Import** engine (column mapping + validation + error log); `--attach-pdf` links source evidence to the Data Import doc |
| `erp exec module.function` | server-side python via `bench execute` (auto-commit) |
| `erp exec --console file.py` | ad-hoc `bench console` (script self-commits) |

## Hard rules baked in (don't fight them)

- **`docstatus`**: 0 draft / 1 submitted / 2 cancelled. Submit is one-way — to change a
  submitted doc, **cancel → amend** (use the `cancel_and_amend_je` Server Script; never
  post a fixing Dr/Cr reclass JE).
- **GL Entry is derived & read-only** — the client refuses to insert it; GL reads default
  to `is_cancelled=0`.
- **POST is not idempotent** — pre-check by business key (`--unique`, or `client.exists()`).
- **Never set `naming_series`**; let the server default fire.
- Amending a JE? the Server Script sets `set_posting_time=1` so the date doesn't reset to today.

See **references/api.md** (REST/RPC surface, filters, reports) and
**references/server-side.md** (the `exec` hatch, the bind-mount, Server Scripts, and the
operational gotchas — backend-recreate-needs-frontend-restart, the `common_site_config`
gate). Extend per **CONTRIBUTING.md**.
