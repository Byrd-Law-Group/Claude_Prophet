#!/usr/bin/env python3
"""Gather the merge fields needed to fill a standard client/insurer letter from Clio.

Read-only. Pulls the matter, client contact (name/address/phone/email), responsible
attorney, and recent notes (where adjuster/claim/insurer details are often logged),
so the clio-letters skill can fill a Letter of Representation, HIPAA authorization,
spoliation letter, etc. Emits one JSON bundle.

Usage:
    python letter_data.py --matter <id|name> [--connection <id>]
"""
import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://gateway.maton.ai/clio/api/v4"


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
        return api_get(path, params, connection), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} on {path}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__} on {path}"


def resolve_matter(q, connection=None):
    q = str(q).strip()
    fields = ("id,display_number,description,status,open_date,client{id,name},"
              "responsible_attorney{id,name}")
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


def fmt_address(addr):
    if not addr:
        return None
    parts = [addr.get("street"),
             ", ".join(x for x in [addr.get("city"), addr.get("province"),
                                   addr.get("postal_code")] if x)]
    return "\n".join(p for p in parts if p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matter", required=True)
    ap.add_argument("--connection", default=None)
    args = ap.parse_args()
    conn = args.connection
    warnings = []

    matter, candidates = resolve_matter(args.matter, conn)
    if matter is None:
        print(json.dumps({"status": "ambiguous" if candidates else "not_found",
                          "candidates": [{"id": c.get("id"),
                                          "display_number": c.get("display_number"),
                                          "client": (c.get("client") or {}).get("name")}
                                         for c in (candidates or [])]}, indent=2))
        return

    mid = matter["id"]
    client = matter.get("client") or {}
    if client.get("id"):
        c, err = _safe(f"/contacts/{client['id']}.json",
                       {"fields": "id,name,first_name,last_name,primary_phone_number,"
                                  "primary_email_address,"
                                  "addresses{name,street,city,province,postal_code}"}, conn)
        if c:
            client = c
        elif err:
            warnings.append(f"contact: {err}")

    notes, err = _safe("/notes.json", {"type": "Matter", "matter_id": mid,
                                       "fields": "id,subject,detail,date", "limit": 50}, conn)
    if err:
        warnings.append(f"notes: {err}")
    fact_notes = [{"date": n.get("date"), "subject": n.get("subject"),
                   "detail": _strip_html(n.get("detail"))}
                  for n in (notes or [])
                  if "[clio-medical-tracker]" not in (n.get("subject") or "")]

    addrs = client.get("addresses") or []
    print(json.dumps({
        "status": "ok",
        "merge_fields": {
            "matter_display_number": matter.get("display_number"),
            "matter_description_first_line": (matter.get("description") or "").split("\n")[0],
            "date_of_loss_hint": (matter.get("description") or "").split("\n")[0],
            "client_name": client.get("name"),
            "client_first_name": client.get("first_name"),
            "client_last_name": client.get("last_name"),
            "client_phone": client.get("primary_phone_number"),
            "client_email": client.get("primary_email_address"),
            "client_address": fmt_address(addrs[0]) if addrs else None,
            "responsible_attorney": (matter.get("responsible_attorney") or {}).get("name"),
        },
        "liability_notes": fact_notes,
        "note": "Adjuster, claim number, and carrier are often only in the notes or "
                "not in Clio at all — the skill should read liability_notes and ask "
                "the user for anything missing before finalizing a letter.",
        "warnings": warnings,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
