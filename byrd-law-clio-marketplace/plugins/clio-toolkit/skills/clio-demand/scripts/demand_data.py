#!/usr/bin/env python3
"""Gather everything needed to draft a PI demand letter from a Clio matter.

Read-only. Pulls the matter + client + responsible attorney, the liability facts
from the matter description and recent notes, the medical special damages from the
clio-medical-tracker ledger note (if present), and the list of documents on file
(records/bills to reference or attach). Emits one JSON bundle the clio-demand skill
turns into a demand letter draft.

Usage:
    python demand_data.py --matter <id|name> [--notes 10] [--connection <id>]
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://gateway.maton.ai/clio/api/v4"
LEDGER_SUBJECT = "MEDICAL LEDGER [clio-medical-tracker]"
BEGIN, END = "<<<LEDGER", "LEDGER>>>"


def _headers(connection=None):
    key = os.environ.get("MATON_API_KEY")
    if not key:
        sys.exit("ERROR: MATON_API_KEY is not set. See the clio skill for setup.")
    h = {"Authorization": f"Bearer {key}"}
    conn = connection or os.environ.get("MATON_CONNECTION") or os.environ.get("CLIO_CONNECTION_ID")
    if conn:
        h["Maton-Connection"] = conn
    return h


def _next_token(payload):
    # Re-request via the gateway with page_token; Clio's `next` URL points at
    # app.clio.com and bypasses the gateway's token injection (401).
    nxt = (payload.get("meta") or {}).get("paging", {}).get("next")
    if not nxt:
        return None
    tok = urllib.parse.parse_qs(urllib.parse.urlparse(nxt).query).get("page_token")
    return tok[0] if tok else None


def api_get(path, params=None, connection=None):
    params = dict(params or {})
    headers = _headers(connection)
    merged, single = [], None
    while True:
        url = f"{BASE}{path}?" + urllib.parse.urlencode(params, safe="{},")
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
        data = payload.get("data")
        if isinstance(data, list):
            merged.extend(data)
        else:
            single = data
        token = _next_token(payload)
        if not token:
            break
        params["page_token"] = token
    return single if single is not None else merged


def _safe(path, params=None, connection=None):
    try:
        return api_get(path, params=params, connection=connection), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} on {path}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__} on {path}"


def resolve_matter(q, connection=None):
    q = str(q).strip()
    fields = ("id,display_number,description,status,open_date,client{id,name},"
              "responsible_attorney{id,name},practice_area{id,name}")
    if q.isdigit():
        m, _ = _safe(f"/matters/{q}.json", {"fields": fields}, connection)
        if m:
            return m, None
    matters, _ = _safe("/matters.json", {"query": q, "fields": fields, "limit": 10}, connection)
    matters = matters or []
    if len(matters) == 1:
        return matters[0], None
    return None, matters


def _strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))


def parse_ledger(notes):
    for n in notes:
        if (n.get("subject") or "").strip() == LEDGER_SUBJECT:
            text = _strip_html(n.get("detail") or "")
            m = re.search(re.escape(BEGIN) + r"(.*?)" + re.escape(END), text, re.S)
            if m:
                try:
                    return json.loads(m.group(1).strip())
                except json.JSONDecodeError:
                    return None
    return None


def specials_totals(ledger):
    if not ledger:
        return None
    billed = sum(float(p.get("bill_amount") or 0) for p in ledger.get("providers", []))
    return {
        "total_billed_medical": round(billed, 2),
        "wage_loss": round(float(ledger.get("wage_loss") or 0), 2),
        "out_of_pocket": round(float(ledger.get("out_of_pocket") or 0), 2),
        "total_special_damages": round(billed + float(ledger.get("wage_loss") or 0)
                                       + float(ledger.get("out_of_pocket") or 0), 2),
        "providers": [{"name": p.get("name"), "bill_amount": p.get("bill_amount"),
                       "records_received": p.get("records_received"),
                       "lien": p.get("lien"), "lien_amount": p.get("lien_amount")}
                      for p in ledger.get("providers", [])],
        "records_outstanding": [p.get("name") for p in ledger.get("providers", [])
                                if not p.get("records_received")],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matter", required=True)
    ap.add_argument("--notes", type=int, default=10)
    ap.add_argument("--connection", default=None)
    args = ap.parse_args()
    conn = args.connection
    warnings = []

    matter, candidates = resolve_matter(args.matter, conn)
    if matter is None:
        print(json.dumps({"status": "ambiguous" if candidates else "not_found",
                          "candidates": [{"id": c.get("id"),
                                          "display_number": c.get("display_number"),
                                          "description": (c.get("description") or "")[:60],
                                          "client": (c.get("client") or {}).get("name")}
                                         for c in (candidates or [])]}, indent=2))
        return

    mid = matter["id"]
    client = matter.get("client") or {}
    if client.get("id"):
        c, err = _safe(f"/contacts/{client['id']}.json",
                       {"fields": "id,name,primary_phone_number,primary_email_address,"
                                  "addresses{name,street,city,province,postal_code}"}, conn)
        if c:
            client = c
        elif err:
            warnings.append(f"contact: {err}")

    notes, err = _safe("/notes.json", {"type": "Matter", "matter_id": mid,
                                       "fields": "id,subject,detail,date,created_at",
                                       "limit": 100}, conn)
    if err:
        warnings.append(f"notes: {err}")
    notes = notes or []
    ledger = parse_ledger(notes)
    # Liability facts = non-ledger notes, most recent first.
    fact_notes = [{"date": n.get("date") or (n.get("created_at") or "")[:10],
                   "subject": n.get("subject"),
                   "detail": _strip_html(n.get("detail"))}
                  for n in notes if (n.get("subject") or "").strip() != LEDGER_SUBJECT]
    fact_notes.sort(key=lambda n: n.get("date") or "", reverse=True)

    docs, err = _safe("/documents.json", {"matter_id": mid,
                                          "fields": "id,name,content_type,updated_at",
                                          "limit": 100}, conn)
    if err:
        warnings.append(f"documents: {err}")

    print(json.dumps({
        "status": "ok",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "matter": {"id": mid, "display_number": matter.get("display_number"),
                   "description": matter.get("description"), "status": matter.get("status"),
                   "open_date": matter.get("open_date"),
                   "responsible_attorney": (matter.get("responsible_attorney") or {}).get("name")},
        "client": {"name": client.get("name"),
                   "phone": client.get("primary_phone_number"),
                   "email": client.get("primary_email_address"),
                   "addresses": client.get("addresses")},
        "liability_notes": fact_notes[:args.notes],
        "specials": specials_totals(ledger),
        "documents_on_file": docs or [],
        "warnings": warnings,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
