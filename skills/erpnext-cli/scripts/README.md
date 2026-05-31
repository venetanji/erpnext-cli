# scripts/

| File | What |
|---|---|
| `erpnext_client.py` | The library — config, REST/RPC (`get/list/count/insert/set_value/submit/cancel/delete/method/run_doc_method/attach_url/exists`), and the `exec_script` server-side hatch. Import it; don't reinvent. |
| `erp` | The CLI — argparse subparsers, one `cmd_<name>(args, c)` per verb. |
| `deploy_server_scripts.py` | Idempotently upserts `server_scripts/*.py` to the instance over REST. |
| `server_scripts/` | API-type Server Scripts (`# api_method:` header each). gl_balance, account_ledger, cancel_and_amend_je, reset_bank_txn_recon. |
| `cli-scripts-examples/` | Example `bench execute` helpers to drop into your bind-mounted `scripts_bind_dir`. |
| `config.example.json` | Template for `$ERP_HOME/config.json` (real one gitignored — holds the api_secret). |

## Run

```bash
export ERP_HOME=~/.config/erpnext-cli      # default
./erp ping
./erp list "Sales Invoice" --filters '[["docstatus","=",1]]' --fields '["name","grand_total"]' --limit 20
./erp method gl_balance --json '{"account":"..."}'
./erp exec gl_tools.gl_count
```

Symlink `erp` onto PATH for `erp …` without `./`. Deploy server scripts with
`python3 deploy_server_scripts.py` (needs `server_script_enabled` — see
`../references/server-side.md`).
