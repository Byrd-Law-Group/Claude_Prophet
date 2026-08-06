#!/usr/bin/env python3
"""Per-matter medical records & bills tracker for Clio (PI special damages).

Clio has no native 'medical bills' object, so this keeps a small structured ledger
as a MATTER NOTE with a machine-readable JSON payload (subject tagged so it's easy
to find, and human-visible in Clio's notes). It tracks, per provider: records
requested/received dates, billed amount, who paid (MedPay/PIP/health), and any
lien — and totals the medical specials that feed a demand.

Writes are limited to this one ledger note. Every mutation prints the resulting
ledger; the skill previews changes for the user before saving.

Usage:
    python medical_tracker.py show     --matter <id|name>
    python medical_tracker.py totals   --matter <id|name>
    python medical_tracker.py add-provider --matter <id> --name "Grady ER"
    python medical_tracker.py set-records  --matter <id> --name "Grady ER" \
        --requested 2026-01-10 --received 2026-02-01
    python medical_tracker.py set-bill     --matter <id> --name "Grady ER" \
        --amount 4200.00 --paid-by MedPay --lien 4200.00
    python medical_tracker.py set-extras   --matter <id> --wage-loss 3000 --out-of-pocket 250
    python medical_tracker.py remove-provider --matter <id> --name "Grady ER"

Set MATON_API_KEY (and MATON_CONNECTION if needed).
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
SUBJECT = "MEDICAL LEDGER [clio-medical-tracker]"
BEGIN, END = "<<<LEDGER", "LEDGER>>>"


def _headers(method="GET"):
    key = os.environ.get("MATON_API_KEY")
    if not key:
        sys.exit("ERROR: MATON_API_KEY is not set. See the clio skill for setup.")
    h = {"Authorization": f"Bearer {key}"}
    if method in ("POST", "PATCH"):
        h["Content-Type"] = "application/json"
    conn = os.environ.get("MATON_CONNECTION") or os.environ.get("CLIO_CONNECTION_ID")
    if conn:
        h["Maton-Connection"] = conn
    return h


def api(method, path, params=None, body=None):
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, safe="{},")
    data = json.dumps({"data": body}).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=_headers(method))
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"ERROR: Clio {method} {path} -> HTTP {e.code}\n{e.read().decode(errors='replace')}")


def resolve_matter(q):
    q = str(q).strip()
    if q.isdigit():
        m = api("GET", f"/matters/{q}.json",
                {"fields": "id,display_number,description,client{id,name}"}).get("data")
        if m:
            return m
    res = api("GET", "/matters.json",
              {"query": q, "fields": "id,display_number,description,client{id,name}", "limit": 10})
    matters = res.get("data", [])
    if not matters:
        sys.exit(f"ERROR: no matter matched '{q}'.")
    if len(matters) > 1:
        lines = [f"  {m['id']}  {m.get('display_number','')}  {m.get('description','')[:50]}"
                 for m in matters]
        sys.exit("Multiple matters matched — re-run with the numeric --matter id:\n" + "\n".join(lines))
    return matters[0]


def _strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or ""))


def load_ledger(matter_id):
    """Return (note_id_or_None, ledger_dict)."""
    res = api("GET", "/notes.json", {
        "type": "Matter", "matter_id": matter_id,
        "fields": "id,subject,detail", "limit": 100,
    })
    for n in res.get("data", []):
        if (n.get("subject") or "").strip() == SUBJECT:
            text = _strip_html(n.get("detail") or "")
            m = re.search(re.escape(BEGIN) + r"(.*?)" + re.escape(END), text, re.S)
            if m:
                try:
                    return n["id"], json.loads(m.group(1).strip())
                except json.JSONDecodeError:
                    pass
            return n["id"], _empty(matter_id)
    return None, _empty(matter_id)


def _empty(matter_id):
    return {"matter_id": matter_id, "providers": [], "wage_loss": 0.0,
            "out_of_pocket": 0.0}


def save_ledger(note_id, matter_id, ledger):
    ledger["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    payload = (f"Maintained by clio-medical-tracker — edit via the skill, not by hand.\n"
               f"{BEGIN}\n{json.dumps(ledger, indent=2)}\n{END}")
    body = {"subject": SUBJECT, "detail": payload, "type": "Matter",
            "matter": {"id": matter_id}}
    if note_id:
        api("PATCH", f"/notes/{note_id}.json", body={"detail": payload})
    else:
        api("POST", "/notes.json", body=body)


def find_provider(ledger, name):
    for p in ledger["providers"]:
        if p["name"].strip().lower() == name.strip().lower():
            return p
    return None


def totals(ledger):
    billed = sum(float(p.get("bill_amount") or 0) for p in ledger["providers"])
    liens = sum(float(p.get("lien_amount") or 0) for p in ledger["providers"] if p.get("lien"))
    specials = billed + float(ledger.get("wage_loss") or 0) + float(ledger.get("out_of_pocket") or 0)
    return {
        "total_billed_medical": round(billed, 2),
        "total_liens": round(liens, 2),
        "wage_loss": round(float(ledger.get("wage_loss") or 0), 2),
        "out_of_pocket": round(float(ledger.get("out_of_pocket") or 0), 2),
        "total_special_damages": round(specials, 2),
        "providers": len(ledger["providers"]),
        "records_outstanding": [p["name"] for p in ledger["providers"]
                                if not p.get("records_received")],
    }


def emit(matter, ledger, saved=False):
    out = {"status": "ok", "saved": saved,
           "matter": {"id": matter["id"], "display_number": matter.get("display_number"),
                      "client": (matter.get("client") or {}).get("name")},
           "ledger": ledger, "totals": totals(ledger)}
    print(json.dumps(out, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("show", "totals"):
        s = sub.add_parser(c); s.add_argument("--matter", required=True)
    p = sub.add_parser("add-provider"); p.add_argument("--matter", required=True); p.add_argument("--name", required=True)
    p = sub.add_parser("remove-provider"); p.add_argument("--matter", required=True); p.add_argument("--name", required=True)
    p = sub.add_parser("set-records"); p.add_argument("--matter", required=True); p.add_argument("--name", required=True)
    p.add_argument("--requested"); p.add_argument("--received")
    p = sub.add_parser("set-bill"); p.add_argument("--matter", required=True); p.add_argument("--name", required=True)
    p.add_argument("--amount", type=float); p.add_argument("--paid-by"); p.add_argument("--lien", type=float)
    p = sub.add_parser("set-extras"); p.add_argument("--matter", required=True)
    p.add_argument("--wage-loss", type=float); p.add_argument("--out-of-pocket", type=float)
    args = ap.parse_args()

    matter = resolve_matter(args.matter)
    mid = matter["id"]
    note_id, ledger = load_ledger(mid)

    if args.cmd in ("show", "totals"):
        emit(matter, ledger); return

    if args.cmd == "add-provider":
        if find_provider(ledger, args.name):
            sys.exit(f"Provider '{args.name}' already exists.")
        ledger["providers"].append({"name": args.name, "records_requested": None,
                                     "records_received": None, "bill_amount": None,
                                     "paid_by": None, "lien": False, "lien_amount": None})
    elif args.cmd == "remove-provider":
        before = len(ledger["providers"])
        ledger["providers"] = [p for p in ledger["providers"]
                               if p["name"].strip().lower() != args.name.strip().lower()]
        if len(ledger["providers"]) == before:
            sys.exit(f"No provider named '{args.name}'.")
    elif args.cmd == "set-records":
        prov = find_provider(ledger, args.name) or sys.exit(f"No provider '{args.name}'. Add it first.")
        if args.requested is not None: prov["records_requested"] = args.requested
        if args.received is not None: prov["records_received"] = args.received
    elif args.cmd == "set-bill":
        prov = find_provider(ledger, args.name) or sys.exit(f"No provider '{args.name}'. Add it first.")
        if args.amount is not None: prov["bill_amount"] = args.amount
        if args.paid_by is not None: prov["paid_by"] = args.paid_by
        if args.lien is not None:
            prov["lien"] = True; prov["lien_amount"] = args.lien
    elif args.cmd == "set-extras":
        if args.wage_loss is not None: ledger["wage_loss"] = args.wage_loss
        if args.out_of_pocket is not None: ledger["out_of_pocket"] = args.out_of_pocket

    save_ledger(note_id, mid, ledger)
    emit(matter, ledger, saved=True)


if __name__ == "__main__":
    main()
