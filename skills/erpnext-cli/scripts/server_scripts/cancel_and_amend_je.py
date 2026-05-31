# api_method: cancel_and_amend_je
# ATOMIC cancel -> copy -> apply account/amount changes -> submit, in ONE transaction
# (a whole REST call = one DB transaction, so it all commits or all rolls back).
# This is the canonical amend pattern (NEVER post a fixing Dr/Cr reclass JE).
# Params:
#   name     : Journal Entry name (submitted)
#   changes  : JSON list of {"idx": <row index>, "account": "...", "debit": n, "credit": n}
#   dry_run  : default "true" — returns the planned new lines WITHOUT touching anything.
# Honours set_posting_time so the amended posting_date doesn't reset to today.
# Frappe parses the JSON POST body into form_dict, so changes is already a list and
# dry_run already a bool (parse_json/import are not available in the sandbox).
name = frappe.form_dict.get("name")
changes = frappe.form_dict.get("changes") or []
dry_run = frappe.form_dict.get("dry_run", True)
if dry_run in (False, 0, "false", "False", "0"):
    dry_run = False
else:
    dry_run = True

src = frappe.get_doc("Journal Entry", name)
new = frappe.copy_doc(src)
new.set_posting_time = 1
new.posting_date = src.posting_date
for ch in changes:
    row = new.accounts[ch["idx"]]
    if ch.get("account"):
        row.account = ch["account"]
    if "debit" in ch:
        row.debit_in_account_currency = ch["debit"]
    if "credit" in ch:
        row.credit_in_account_currency = ch["credit"]

preview = [{"account": a.account,
            "debit": a.debit_in_account_currency,
            "credit": a.credit_in_account_currency} for a in new.accounts]

if dry_run:
    frappe.response["message"] = {"dry_run": True, "source": name, "planned_lines": preview}
else:
    if src.docstatus == 1:
        src.cancel()
    new.amended_from = name
    new.insert()
    new.submit()
    frappe.response["message"] = {"dry_run": False, "amended_to": new.name, "lines": preview}
