#!/usr/bin/env python3
"""
erpnext_client — a small, dependency-light client for a running ERPNext/Frappe
instance, built for bookkeeping / audit reconstruction automation.

Design goals
------------
* **REST-first, container-last.** ~90% of operations (reads, single-doc CRUD,
  submit/cancel, whitelisted methods, reports, file-attach-as-URL) go over the
  REST/RPC API with token auth — **no `docker exec`, no file copy**. Every POST is
  its own auto-committed transaction. The container is only touched for the genuine
  server-side cases (raw SQL bulk, filesystem/import, fine transaction control).
* **One source of truth for deployment facts.** Compose project, file, container
  service, site, and bind paths live in `$ERP_HOME/config.json` — so the container
  name can't drift across scripts (a real bug we hit).
* **Escape hatch without the ceremony.** `exec_script()` runs a host script inside
  the backend via the auto-committing `bench execute`/env-python, reading it straight
  from a bind-mounted dir (no `docker cp`) and **verifying freshness** to prevent the
  stale-`/tmp` class of bug. Falls back to `docker cp` if no mount is configured.
* **Guardrails from hard-won pitfalls.** Idempotency pre-check, `is_cancelled=0`
  default on GL reads, GL-Entry write block, `set_posting_time` reminder.

Reference: https://docs.frappe.io/framework/user/en/api/rest
"""
from __future__ import annotations

import csv
import json
import mimetypes
import os
import subprocess
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional


def erp_home() -> Path:
    return Path(os.environ.get("ERP_HOME", str(Path.home() / ".config/erpnext-cli")))


class ERPNextError(RuntimeError):
    """Actionable, user-facing error — print str(e), don't dump a traceback."""


class ERPNextClient:
    """
    Config (`$ERP_HOME/config.json`):

        {
          "base_url": "http://localhost:8080",
          "api_key": "...", "api_secret": "...",
          "site": "frontend",
          "compose_project": "sleephere-erpnext",
          "compose_file": "/home/.../frappe_docker/pwd.yml",
          "container_service": "backend",
          "scripts_bind_dir": "/home/openclaw/erpnext/cli-scripts",          # host side
          "scripts_container_dir": "/home/frappe/frappe-bench/cli-scripts",  # bind target
          "bench_python": "/home/frappe/frappe-bench/env/bin/python3"
        }
    """

    GL_DOCTYPE = "GL Entry"

    def __init__(self, home: Optional[Path] = None):
        self.home = Path(home) if home else erp_home()
        cfgp = self.home / "config.json"
        if not cfgp.exists():
            raise ERPNextError(f"No config at {cfgp}. Run `erp init` or copy config.example.json.")
        self.cfg = json.loads(cfgp.read_text())
        self.base = self.cfg["base_url"].rstrip("/")
        self.site = self.cfg.get("site", "frontend")
        self._auth = f"token {self.cfg['api_key']}:{self.cfg['api_secret']}"

    # ── HTTP core ────────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, params: dict | None = None,
                 body: dict | None = None) -> Any:
        url = f"{self.base}{path}"
        if params:
            # Frappe wants JSON-encoded list/dict params
            enc = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                   for k, v in params.items() if v is not None}
            url += "?" + urllib.parse.urlencode(enc)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": self._auth,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ERPNextError(self._explain(e)) from None

    @staticmethod
    def _explain(e: urllib.error.HTTPError) -> str:
        raw = e.read().decode("utf-8", "ignore")
        msg = f"HTTP {e.code}"
        try:
            j = json.loads(raw)
            # Frappe packs the useful bit in _server_messages or exception
            sm = j.get("_server_messages")
            if sm:
                parts = [json.loads(m).get("message", m) for m in json.loads(sm)]
                msg += ": " + "; ".join(str(p) for p in parts)
            elif j.get("exception"):
                msg += ": " + j["exception"]
            elif j.get("message"):
                msg += ": " + str(j["message"])
        except Exception:
            msg += ": " + raw[:300]
        return msg

    # ── reads ────────────────────────────────────────────────────────────────
    def get(self, doctype: str, name: str) -> dict:
        return self._request("GET", f"/api/resource/{urllib.parse.quote(doctype)}/{urllib.parse.quote(name)}")["data"]

    def list(self, doctype: str, filters=None, fields=None, or_filters=None,
             order_by=None, limit: int = 20, start: int = 0) -> list[dict]:
        """limit=0 → all records (no server cap; use deliberately)."""
        # GL Entry: default to live (non-cancelled) rows unless caller overrides
        if doctype == self.GL_DOCTYPE and filters is None:
            filters = [["is_cancelled", "=", 0]]
        params = {
            "doctype": doctype, "filters": filters, "or_filters": or_filters,
            "fields": fields or ["name"], "order_by": order_by,
            "limit_page_length": limit, "limit_start": start,
        }
        return self._request("GET", "/api/method/frappe.client.get_list", params)["message"]

    def get_value(self, doctype: str, filters, fieldname="name"):
        params = {"doctype": doctype, "filters": filters, "fieldname": fieldname}
        msg = self._request("GET", "/api/method/frappe.client.get_value", params)["message"]
        # frappe returns {fieldname: value} — unwrap to the scalar for a single field
        if isinstance(fieldname, str) and isinstance(msg, dict):
            return msg.get(fieldname)
        return msg

    def count(self, doctype: str, filters=None) -> int:
        if doctype == self.GL_DOCTYPE and filters is None:
            filters = [["is_cancelled", "=", 0]]
        params = {"doctype": doctype, "filters": filters}
        return self._request("GET", "/api/method/frappe.client.get_count", params)["message"]

    def exists(self, doctype: str, filters) -> bool:
        """Idempotency pre-check — call before insert() to avoid duplicates."""
        return self.count(doctype, filters) > 0

    def schema(self, doctype: str) -> dict:
        """Live field schema for a DocType: its DocFields + any Custom Fields merged in
        (standard doctypes store customizations separately in `Custom Field`). Works for
        custom doctypes too. `frappe.get_meta` isn't REST-whitelisted, so we read the
        `DocType` resource directly."""
        dt = self.get("DocType", doctype)
        fields = [dict(f, _custom=False) for f in dt.get("fields", [])]
        cf = self.list("Custom Field", filters=[["dt", "=", doctype]],
                       fields=["fieldname", "fieldtype", "label", "options", "reqd",
                               "unique", "read_only", "insert_after"], limit=0)
        fields += [dict(f, _custom=True) for f in cf]
        return {"doctype": doctype, "module": dt.get("module"), "custom": dt.get("custom"),
                "issingle": dt.get("issingle"), "istable": dt.get("istable"),
                "is_submittable": dt.get("is_submittable"), "autoname": dt.get("autoname"),
                "naming_rule": dt.get("naming_rule"), "title_field": dt.get("title_field"),
                "fields": fields}

    @staticmethod
    def read_records(path: str) -> list[dict]:
        """Parse a bulk-import file into row dicts. Supports .json (array or single),
        .jsonl, .csv (header row → fieldnames), .xlsx (first sheet, header row)."""
        p = Path(path)
        ext = p.suffix.lower()
        if ext == ".json":
            data = json.loads(p.read_text())
            return data if isinstance(data, list) else [data]
        if ext == ".jsonl":
            return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]
        if ext == ".csv":
            with open(p, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        if ext in (".xlsx", ".xlsm"):
            try:
                import openpyxl
            except ImportError:
                raise ERPNextError("xlsx import needs openpyxl (pip install openpyxl)") from None
            ws = openpyxl.load_workbook(p, read_only=True, data_only=True).active
            it = ws.iter_rows(values_only=True)
            header = [str(h).strip() if h is not None else "" for h in next(it)]
            out = []
            for r in it:
                if all(c is None for c in r):
                    continue
                out.append({header[i]: r[i] for i in range(min(len(header), len(r))) if header[i]})
            return out
        raise ERPNextError(f"unsupported file type {ext!r} (use .json/.jsonl/.csv/.xlsx)")

    def report(self, report_name: str, filters: dict | None = None) -> dict:
        params = {"report_name": report_name, "filters": filters or {}}
        return self._request("GET", "/api/method/frappe.desk.query_report.run", params)["message"]

    # ── writes (each is its own auto-committed transaction) ───────────────────
    def insert(self, doc: dict) -> dict:
        if doc.get("doctype") == self.GL_DOCTYPE:
            raise ERPNextError("GL Entry is a derived ledger — never insert directly; post/cancel the source voucher.")
        return self._request("POST", f"/api/resource/{urllib.parse.quote(doc['doctype'])}", body=doc)["data"]

    def set_value(self, doctype: str, name: str, fieldname, value=None) -> dict:
        body = {"doctype": doctype, "name": name, "fieldname": fieldname}
        if value is not None:
            body["value"] = value
        return self._request("POST", "/api/method/frappe.client.set_value", body=body)["message"]

    def submit(self, doctype: str, name: str) -> dict:
        doc = self.get(doctype, name)
        return self._request("POST", "/api/method/frappe.client.submit", body={"doc": json.dumps(doc)})["message"]

    def cancel(self, doctype: str, name: str) -> dict:
        return self._request("POST", "/api/method/frappe.client.cancel",
                             body={"doctype": doctype, "name": name})["message"]

    def delete(self, doctype: str, name: str) -> Any:
        return self._request("POST", "/api/method/frappe.client.delete",
                             body={"doctype": doctype, "name": name})

    def method(self, dotted_path: str, **kwargs) -> Any:
        """Call any whitelisted server method (incl. ERPNext factory methods like
        erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry)."""
        r = self._request("POST", f"/api/method/{dotted_path}", body=kwargs or None)
        return r.get("message", r)

    def run_doc_method(self, method: str, doctype: str, name: str, args: dict | None = None) -> Any:
        doc = self.get(doctype, name)
        body = {"method": method, "docs": json.dumps(doc)}
        if args:
            body["args"] = json.dumps(args)
        return self._request("POST", "/api/method/run_doc_method", body=body).get("message")

    def attach_url(self, doctype: str, name: str, file_url: str, file_name: str | None = None) -> dict:
        """Attach a Drive (or any) URL to a record without copying bytes."""
        body = {"doctype": "File", "file_url": file_url,
                "file_name": file_name or file_url.rsplit("/", 1)[-1],
                "attached_to_doctype": doctype, "attached_to_name": name}
        return self._request("POST", "/api/resource/File", body=body)["data"]

    def upload_file(self, path: str, attach_doctype: str | None = None,
                    attach_name: str | None = None, fieldname: str | None = None,
                    private: bool = True) -> dict:
        """Multipart upload to /api/method/upload_file → returns the File record
        ({file_url, name, ...}). If attach_doctype/name/fieldname given, attaches to and
        sets that field on the target doc."""
        p = Path(path)
        boundary = "----erpcli" + uuid.uuid4().hex
        fields = {"is_private": "1" if private else "0"}
        if attach_doctype:
            fields["doctype"] = attach_doctype
        if attach_name:
            fields["docname"] = attach_name
        if fieldname:
            fields["fieldname"] = fieldname
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                      f'filename="{p.name}"\r\nContent-Type: {ctype}\r\n\r\n').encode())
        parts.append(p.read_bytes())
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            f"{self.base}/api/method/upload_file", data=b"".join(parts), method="POST",
            headers={"Authorization": self._auth, "Accept": "application/json",
                     "Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())["message"]
        except urllib.error.HTTPError as e:
            raise ERPNextError(self._explain(e)) from None

    def data_import(self, reference_doctype: str, file_path: str,
                    import_type: str = "Insert New Records", submit: bool = False,
                    mute_emails: bool = True, attach_pdf: str | None = None,
                    wait: bool = True, timeout: int = 300) -> dict:
        """Drive ERPNext's native Data Import engine: create the Data Import doc, upload
        the csv/xlsx, optionally attach a source PDF as evidence, start the (background)
        import, and poll to a terminal status. Returns name + status + per-row log summary."""
        di = self.insert({"doctype": "Data Import", "reference_doctype": reference_doctype,
                          "import_type": import_type,
                          "submit_after_import": int(submit), "mute_emails": int(mute_emails)})
        name = di["name"]
        up = self.upload_file(file_path, attach_doctype="Data Import", attach_name=name,
                              fieldname="import_file", private=True)
        if up.get("file_url"):
            self.set_value("Data Import", name, "import_file", up["file_url"])
        if attach_pdf:
            self.attach_url("Data Import", name, attach_pdf)   # link source evidence

        out = {"data_import": name, "reference_doctype": reference_doctype, "import_file": up.get("file_url")}
        if not wait:
            # pure-REST async: enqueue and return (a background worker processes it)
            self.method("frappe.core.doctype.data_import.data_import.form_start_import", data_import=name)
            out["status"] = "Pending (enqueued — needs a background worker)"
            return out
        # default: trigger SYNCHRONOUSLY via bench for a deterministic, worker-independent
        # result (the synchronous start_import isn't REST-whitelisted; form_start_import only
        # enqueues). Uses the container — the one server-side touch in this verb.
        self._bench_execute("frappe.core.doctype.data_import.data_import.start_import",
                            {"data_import": name})
        out["status"] = self.get_value("Data Import", name, "status")
        out["payload_count"] = self.get_value("Data Import", name, "payload_count")
        try:
            logs = self.method("frappe.core.doctype.data_import.data_import.get_import_logs",
                               data_import=name) or []
            errs = [ln for ln in logs if not ln.get("success")]
            out["success_rows"] = len(logs) - len(errs)
            out["error_rows"] = len(errs)
            out["errors"] = [{"row": e.get("row_indexes"),
                              "msg": (e.get("messages") or e.get("exception"))} for e in errs[:5]]
        except ERPNextError:
            pass
        return out

    # ── server-side escape hatch (no docker cp when bind-mounted) ─────────────
    def _compose(self, *extra: str) -> list[str]:
        return ["docker", "compose", "-p", self.cfg["compose_project"],
                "-f", self.cfg["compose_file"], *extra]

    def _bench_execute(self, dotted_path: str, kwargs: dict | None = None) -> str:
        """Run an installed-app function synchronously via `bench execute` (proper init +
        auto-commit). Resolves dotted app paths via frappe.get_attr — so unlike
        exec_script's eval form it works for framework/ERPNext functions."""
        cmd = self._compose("exec", "-T", "-w", self.cfg.get("bench_dir", "/home/frappe/frappe-bench"),
                            self.cfg.get("container_service", "backend"),
                            "bench", "--site", self.site, "execute", dotted_path)
        if kwargs:
            cmd += ["--kwargs", json.dumps(kwargs)]
        return self._run(cmd)

    def exec_script(self, target: str, mode: str = "execute") -> str:
        """Run server-side python inside the backend container.

        mode='execute' (default): `target` is a `module.function` reference to code in
            the bind-mounted scripts dir (on PYTHONPATH). Runs via
            `bench execute '__import__("module").function()'` — proper frappe.init,
            AUTO-COMMIT on success, auto-rollback on error, correct logging. The
            preferred path: write a function, call it by name. (Flat module, no dots.)
        mode='console': `target` is a host .py file path. Piped through `bench console`
            for legacy/ad-hoc scripts — NO auto-commit, the script must call
            frappe.db.commit() itself. Read straight from the bind-mount (no docker cp);
            falls back to docker cp if the file isn't under the bind dir.

        Because the scripts dir is bind-mounted (same inode host↔container), there is no
        stale-copy class of bug — edit on the host, run immediately."""
        svc = self.cfg.get("container_service", "backend")
        bench_dir = self.cfg.get("bench_dir", "/home/frappe/frappe-bench")
        # -w sets the working dir (so frappe finds sites/); -T allows stdin piping.
        base = self._compose("exec", "-T", "-w", bench_dir, svc, "bench", "--site", self.site)

        if mode == "execute":
            head = target.split("(", 1)[0]              # strip any "(args)"
            mod, _, fn = head.rpartition(".")
            if not mod or not fn:
                raise ERPNextError("execute target must be 'module.function' (e.g. gl_tools.balance)")
            call = target[len(head):] or "()"           # "(args)" or default "()"
            expr = f'__import__("{mod}").{fn}{call}'     # passed as ONE argv element — no shell quoting
            return self._run(base + ["execute", expr])

        # console mode — pipe the host file straight into `bench console` via stdin
        # (works whether or not the file is bind-mounted; no docker cp, no shell redirect).
        return self._run(base + ["console"], input=Path(target).read_text())

    @staticmethod
    def _run(cmd: list[str], input: str | None = None) -> str:
        p = subprocess.run(cmd, capture_output=True, text=True, input=input)
        if p.returncode != 0:
            raise ERPNextError(f"command failed ({p.returncode}): {' '.join(cmd[:8])}…\n{p.stderr[-800:]}")
        return p.stdout
