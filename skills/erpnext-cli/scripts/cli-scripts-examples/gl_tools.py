"""Example bench-execute helpers — copy/symlink into your `scripts_bind_dir`, then call:

    erp exec gl_tools.gl_count
    erp exec gl_tools.balance("Bank - HSBC HKD Current 189-838 - SH")

`bench execute` runs these with frappe initialised and AUTO-COMMITS on success. These do the
raw `frappe.db.sql` aggregates the REST API can't. Keep modules flat (no packages)."""
import frappe


def gl_count():
    n = frappe.db.sql("select count(*) from `tabGL Entry` where is_cancelled=0")[0][0]
    print(f"GL entries (live): {n}")


def balance(account):
    """Net Dr-Cr balance on an account across all live GL entries."""
    row = frappe.db.sql(
        "select sum(debit)-sum(credit) bal, count(*) n "
        "from `tabGL Entry` where account=%s and is_cancelled=0",
        account, as_dict=True)[0]
    print(f"{account}: balance={float(row['bal'] or 0):,.2f} over {row['n']} entries")
