# ERPNext REST/RPC — the no-container surface

Token auth (`Authorization: token <key>:<secret>`) against `base_url`. Two layers:

- **Resource REST**: `/api/resource/<DocType>[/<name>]` — GET (list/read), POST (insert),
  PUT (update), DELETE.
- **RPC**: `/api/method/<dotted.path>` — any `@frappe.whitelist()` method.

**Every POST/PUT/DELETE is its own auto-committed transaction** (commit on success,
rollback on exception). There is no cross-request transaction — for atomic multi-step, use a
Server Script (see `server-side.md`).

## Operations (all in `erpnext_client.py`)

| Method | Endpoint | Notes |
|---|---|---|
| `get(dt, name)` | `GET /api/resource/<dt>/<name>` | one doc (with child tables) |
| `list(dt, filters, fields, or_filters, order_by, limit, start)` | `frappe.client.get_list` | `limit=0` → all |
| `get_value(dt, filters, fieldname)` | `frappe.client.get_value` | single value |
| `count(dt, filters)` | `frappe.client.get_count` | |
| `insert(doc)` | `POST /api/resource/<dt>` | doc dict incl. `doctype`; child rows inline |
| `set_value(dt, name, field, value)` | `frappe.client.set_value` | runs validation + hooks |
| `submit(dt, name)` / `cancel(dt, name)` | `frappe.client.submit/cancel` | lifecycle |
| `delete(dt, name)` | `frappe.client.delete` | |
| `method(path, **kw)` | `POST /api/method/<path>` | whitelisted / factory / Server Script |
| `run_doc_method(method, dt, name, args)` | `run_doc_method` | controller method on a doc |
| `attach_url(dt, name, url, file_name)` | `POST /api/resource/File` | link a URL, no byte copy |
| `exists(dt, filters)` | (count>0) | idempotency pre-check |

Bulk (server-side, one transaction): `frappe.client.insert_many` (≤200 docs) and
`frappe.client.bulk_update` are reachable via `method(...)`.

## get_list filters

```bash
erp list "Journal Entry" \
  --filters '[["company","=","SleepHere HK"],["posting_date","between",["2024-04-01","2025-03-31"]],["docstatus","=",1]]' \
  --fields '["name","posting_date","total_debit","user_remark"]' \
  --order-by 'posting_date asc' --limit 500
```

Operators: `=, !=, >, <, >=, <=, like, not like, in, not in, between, is`. `or_filters`
takes the same shape. `--limit 0` returns everything (no server cap — use deliberately).

## ERPNext factory methods (high-leverage over REST)

One call generates a pre-filled child doc dict; a second `insert`s it:

```bash
# Payment Entry pre-filled from a Sales Invoice
erp method erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry \
  --json '{"dt":"Sales Invoice","dn":"ACC-SINV-2026-00001"}'
# Sales Invoice from a Sales Order
erp method erpnext.selling.doctype.sales_order.sales_order.make_sales_invoice \
  --json '{"source_name":"SAL-ORD-2026-00001"}'
```

## Reports

```bash
erp report "General Ledger" --filters '{"company":"SleepHere HK","from_date":"2024-04-01","to_date":"2025-03-31","account":"..."}'
```
Returns `{result:[...], columns:[...]}`. A user with the **"No reports" role gets HTTP 403**
on `/Reports` and `/Journals`. Standard financial statements (Trial Balance, Balance Sheet,
P&L) are query reports — pass their exact report name.

## Bank reconciliation

ERPNext's Bank Reconciliation Tool exposes a full matcher over REST. `erp reconcile
<BankAccount>` previews it (read-only): for each **open** bank transaction
(`unallocated_amount > 0`) it lists the candidate vouchers the engine proposes.

```bash
erp reconcile "HSBC HKD Current 189-838 - HSBC" --from-date 2026-04-01 --to-date 2026-05-31 --exact
```

- `<BankAccount>` is the **Bank Account** doctype record name (not the chart account).
- `--types` = any of `payment_entry,journal_entry,sales_invoice,purchase_invoice,bank_transaction`.
- `--exact` restricts to exact-amount matches.
- Matching needs vouchers on the other side: a rent receipt matches an outstanding **Sales
  Invoice**; a utility autopay matches a **Purchase Invoice/Payment Entry**. No vouchers →
  no matches (an empty period reconciles to nothing).
- Client helpers: `bank_transactions_open()`, `linked_payments()`, `reconcile_voucher()`.

**Matching settings** live in the `Accounts Settings` single doctype (tune via
`erp set-value "Accounts Settings" "Accounts Settings" <field> <value>`):

| Field | Effect |
|---|---|
| `auto_reconcile_payments` | enable the **background** auto-matcher (exact matches reconcile on a schedule — needs healthy workers, see `erp doctor`) |
| `auto_reconciliation_job_trigger` | minutes between auto-reconcile runs |
| `reconciliation_queue_size` | batch size per run |
| `enable_fuzzy_matching` | fuzzy reference/description matching |
| `enable_party_matching` | match on party as well as amount |

## Hard rules (the client enforces / reminds)

1. **`docstatus`** 0/1/2; submit is one-way → cancel+amend (see `server-side.md`).
2. **GL Entry is derived** — `insert()` refuses it; reads default `is_cancelled=0`. Never
   filter GL without excluding cancelled rows or balances double-count.
3. **POST is not idempotent** — `--unique`/`exists()` before insert.
4. **Don't set `naming_series`** — the `tabSeries` counter doesn't roll back on delete.
5. **set_posting_time=1** when amending dated vouchers, else `posting_date` resets to today.
6. **`set_value` runs full validation + hooks**; for a hook-bypassing raw column write
   (rare — e.g. resetting JE `title` after bulk submit) use a Server Script / `exec` with
   `frappe.db.set_value`.
7. **Multi-currency**: set `conversion_rate`; amounts exist in both account & base currency.
8. **Open period**: posting dates must fall in an open Fiscal Year (watch "Accounts Frozen
   Upto" / Period Closing Vouchers).

## Introspection & custom doctypes

`frappe.get_meta` is **not** REST-whitelisted (403). Use the dedicated commands, which read
the `DocType` resource and merge in `Custom Field` rows:

```bash
erp schema "Sales Invoice"          # fields + types + reqd/unique/read-only/link targets; custom fields marked *
erp schema "License Agreement"      # works for custom doctypes too
erp doctypes --custom               # discover custom doctypes (e.g. Flat / License Agreement / Room)
erp doctypes --module Accounts
```

Custom doctypes are ordinary DocTypes — manage their documents with the same
`get/list/insert/submit/...` verbs. `schema` is the quick "what fields does this actually
have here?" check (every site can be customized — trust the live schema over assumptions).

### Customization wrappers

`Custom Field` / `Property Setter` are themselves DocTypes, so customization is just
inserts — these wrappers make them idempotent and one-line:

```bash
erp add-field "Sales Invoice" xero_invoice_no Data --after customer --read-only   # idempotent
erp set-prop  "Sales Invoice" xero_invoice_no in_list_view 1 --type Check          # Property Setter, no code
erp set-prop  "Sales Invoice" "" naming_series Data --doctype-prop                 # doctype-level property
```

`add-field` skips if the field exists (`--force` to update); `set-prop` upserts. Confirm with
`erp schema <DocType>` (custom fields show `*`).

## Bulk import (json / jsonl / csv / xlsx)

```bash
erp import "Journal Entry" rows.json   --key user_remark            # idempotent: skip existing
erp import Customer        guests.csv  --key customer_name --update # update matches instead
erp import "Sales Invoice" si.xlsx     --submit                     # submit each after insert
erp import Note            notes.jsonl --dry-run                    # preview counts, no writes
```

Each row becomes a doc (file's columns/keys → fieldnames; child tables as nested lists in
json/jsonl). **Each row is its own REST transaction**, so a failed row doesn't roll back the
others and a re-run with `--key` resumes cleanly. `--key F` matches existing rows by a
*field filter* (not the doc name — works even when autoname is a hash).

### Native Data Import engine (`erp data-import`)

Drives ERPNext's own Data Import (column mapping, type coercion, validation, per-row error
log) for **csv/xlsx**. Use it when you want ERPNext's mapping/validation and an auditable
import record; use `erp import` when you want a fast, idempotent scripted loop.

```bash
erp data-import "Purchase Invoice" bills.csv --submit --attach-pdf "<drive-url-of-source-pdf>"
erp data-import Customer guests.xlsx --update          # Update Existing Records
erp data-import "Journal Entry" rows.csv --no-wait     # enqueue only (pure REST, async)
```

- The target DocType must have **`allow_import`** enabled (`erp set-prop <DocType> "" allow_import 1 --type Check --doctype-prop`).
- The csv/xlsx **header must map to field labels or fieldnames** (incl. child-table columns) —
  that template is the caller's responsibility (and, for specific document formats, lives in a
  back-office runbook skill, not here).
- **`--attach-pdf <url>`** attaches the source document (e.g. the Drive PDF) to the Data Import
  doc — so the import record links the loaded rows to their evidence. The csv is attached too.
- **Synchronous by default**: the CLI triggers `start_import` synchronously via bench and
  returns the terminal `status` + a row-level error summary. `--no-wait` instead enqueues via
  the whitelisted `form_start_import` (pure REST, no container) and returns immediately — but
  that needs a healthy **background worker** to process the queue.
