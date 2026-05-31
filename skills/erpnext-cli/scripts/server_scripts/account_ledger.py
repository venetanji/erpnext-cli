# api_method: account_ledger
# Read-only. GL lines for an account in a date range, ordered, with running balance.
# Params: account, from_date (YYYY-MM-DD), to_date (YYYY-MM-DD).
account = frappe.form_dict.get("account")
from_date = frappe.form_dict.get("from_date")
to_date = frappe.form_dict.get("to_date")
rows = frappe.db.sql(
    "select posting_date, voucher_type, voucher_no, debit, credit, against, remarks "
    "from `tabGL Entry` where account=%s and is_cancelled=0 "
    "and posting_date between %s and %s order by posting_date, creation",
    (account, from_date, to_date), as_dict=True)
bal = 0.0
for r in rows:
    bal += float(r.debit or 0) - float(r.credit or 0)
    r["balance"] = round(bal, 2)
frappe.response["message"] = {"account": account, "from": from_date, "to": to_date,
                              "count": len(rows), "rows": rows}
