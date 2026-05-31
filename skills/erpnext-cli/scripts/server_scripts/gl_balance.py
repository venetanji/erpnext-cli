# api_method: gl_balance
# Read-only. Net Dr-Cr balance + entry count for an account — the frappe.db.sql
# aggregate the REST API cannot do. Params: account.
account = frappe.form_dict.get("account")
row = frappe.db.sql(
    "select sum(debit)-sum(credit) as bal, count(*) as n "
    "from `tabGL Entry` where account=%s and is_cancelled=0",
    account, as_dict=True)[0]
frappe.response["message"] = {"account": account, "balance": float(row.bal or 0), "entries": row.n}
