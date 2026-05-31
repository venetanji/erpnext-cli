# api_method: reset_bank_txn_recon
# Post-TDR cleanup: a Transaction Deletion Record wipes JE/PE/SI/PI/GL but leaves Bank
# Transactions flagged Reconciled with stale payment rows. This resets one back to
# Unreconciled atomically. Params: name (Bank Transaction), dry_run (default "true").
name = frappe.form_dict.get("name")
dry_run = frappe.form_dict.get("dry_run", True)
if dry_run in (False, 0, "false", "False", "0"):
    dry_run = False
else:
    dry_run = True

bt = frappe.get_doc("Bank Transaction", name)
info = {"name": name, "status": bt.status,
        "allocated_amount": bt.allocated_amount,
        "payment_rows": len(bt.payment_entries)}

if dry_run:
    frappe.response["message"] = {"dry_run": True, **info}
else:
    bt.payment_entries = []
    bt.allocated_amount = 0
    bt.unallocated_amount = (bt.deposit or 0) or (bt.withdrawal or 0)
    bt.status = "Unreconciled"
    bt.save()
    frappe.response["message"] = {"dry_run": False, "reset": True, **info}
