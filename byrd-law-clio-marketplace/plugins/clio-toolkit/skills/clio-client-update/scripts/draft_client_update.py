#!/usr/bin/env python3
"""Gather the data needed to draft a client text update from a Clio matter.

This script is READ-ONLY. It pulls the matter, its client contact (name + phone),
and the matter's recent notes from Clio through the Maton gateway, and prints a
compact JSON bundle. It does NOT compose the message and does NOT send anything —
the skill turns this data into a client-ready draft for the user to review and send.

Usage
-----
    python draft_client_update.py --matter 12345
    python draft_client_update.py --matter-name "Smith" --limit 5
    python draft_client_update.py --matter 12345 --since 2026-07-01

Auth: set MATON_API_KEY (and optionally MATON_CONNECTION) in the environment.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

GATEWAY = "https://gateway.maton.ai/clio/api/v4"


def _api_key():
    key = os.environ.get("MATON_API_KEY")
    if not key:
        sys.exit("ERROR: MATON_API_KEY is not set. See the clio skill for setup.")
    return key


def get(path, params=None):
    url = f"{GATEWAY}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {_api_key()}")
    conn = os.environ.get("MATON_CONNECTION")
    if conn:
        req.add_header("Maton-Connection", conn)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        sys.exit(f"ERROR: Clio GET {path} -> HTTP {e.code}\n{detail}")


def resolve_matter(args):
    """Return a matter id, or exit with candidates if a name is ambiguous."""
    if args.matter:
        return args.matter
    if not args.matter_name:
        sys.exit("ERROR: provide --matter <id> or --matter-name <text>.")
    res = get("/matters.json", {
        "query": args.matter_name,
        "fields": "id,display_number,description,status,client{id,name}",
        "limit": 10,
    })
    matters = res.get("data", [])
    if not matters:
        sys.exit(f"ERROR: no matter matched '{args.matter_name}'.")
    if len(matters) > 1:
        lines = [f"  {m['id']}  {m.get('display_number','')}  "
                 f"{m.get('description','')}  (client: "
                 f"{(m.get('client') or {}).get('name','?')})" for m in matters]
        sys.exit("Multiple matters matched — re-run with --matter <id>:\n"
                 + "\n".join(lines))
    return matters[0]["id"]


def pick_phone(contact):
    """Choose the best phone number for a text: default > mobile/cell > first."""
    if not contact:
        return None
    phones = contact.get("phone_numbers") or []
    if not phones:
        return contact.get("primary_phone_number")
    for p in phones:
        if p.get("default_number"):
            return p.get("number")
    for p in phones:
        if str(p.get("name", "")).lower() in ("mobile", "cell", "cell phone"):
            return p.get("number")
    return phones[0].get("number")


def main():
    p = argparse.ArgumentParser(description="Gather data for a client text update.")
    p.add_argument("--matter", help="Matter ID.")
    p.add_argument("--matter-name", help="Search text to find the matter by name.")
    p.add_argument("--limit", type=int, default=5,
                   help="How many recent notes to pull (default 5).")
    p.add_argument("--since", help="Only notes on/after this date (YYYY-MM-DD).")
    args = p.parse_args()

    matter_id = resolve_matter(args)

    matter = get(f"/matters/{matter_id}.json", {
        "fields": "id,display_number,description,status,open_date,"
                  "client{id,name,primary_phone_number,"
                  "phone_numbers{name,number,default_number}}",
    }).get("data", {})

    client = matter.get("client") or {}
    # If phone wasn't nested, fetch the contact directly.
    if client.get("id") and not (client.get("phone_numbers")
                                 or client.get("primary_phone_number")):
        client = get(f"/contacts/{client['id']}.json", {
            "fields": "id,name,primary_phone_number,"
                      "phone_numbers{name,number,default_number}",
        }).get("data", client)

    note_params = {
        "matter_id": matter_id,
        "fields": "id,subject,detail,date,created_at",
        "limit": max(1, args.limit),
        "order": "date(desc)",
    }
    if args.since:
        note_params["created_since"] = f"{args.since}T00:00:00Z"
    notes = get("/notes.json", note_params).get("data", [])
    # Sort newest-first defensively (in case the API ignores `order`).
    notes.sort(key=lambda n: (n.get("date") or n.get("created_at") or ""),
               reverse=True)

    bundle = {
        "matter": {
            "id": matter.get("id"),
            "display_number": matter.get("display_number"),
            "description": matter.get("description"),
            "status": matter.get("status"),
        },
        "client": {
            "id": client.get("id"),
            "name": client.get("name"),
            "phone": pick_phone(client),
        },
        "notes": [
            {
                "date": n.get("date") or (n.get("created_at") or "")[:10],
                "subject": n.get("subject"),
                "detail": n.get("detail"),
            }
            for n in notes[:args.limit]
        ],
    }
    print(json.dumps(bundle, indent=2))
    if not bundle["client"]["phone"]:
        print("\nWARNING: no phone number found for the client — cannot text "
              "without one.", file=sys.stderr)
    if not bundle["notes"]:
        print("\nWARNING: no matter notes found — nothing to summarize.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
