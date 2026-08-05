#!/usr/bin/env python3
"""
Open a new motor vehicle accident (MVA) matter in Clio Manage for the Byrd Law Group:
find-or-create the client contact, then create the matter (practice area, responsible
attorney, status, open date, file reference).

Two-stage by design. It defaults to a DRY RUN that prints the full plan — the client
contact it will use or create, and the matter it will open — as JSON. Nothing is written
to Clio until you rerun with --commit. Opening a matter creates real practice-management
records, so the plan is meant to be reviewed and approved by a human first.

Usage:
    # Preview (no writes):
    python create_matter.py "Jane Smith" --injury-date 2026-07-01

    # After the user reviews and approves, create it:
    python create_matter.py "Jane Smith" --injury-date 2026-07-01 --commit

    # Reuse a known client contact instead of searching by name:
    python create_matter.py --client-id 12345 --commit

Key options:
    --client-id ID             Use this existing Clio contact as the client (skips the name search).
    --client-type person|company   Kind of contact to create if the client is new. Default person.
    --first-name / --last-name Override the name parsed from the positional client argument (person).
    --email / --phone          Contact details to set when creating a NEW client contact.
    --description TEXT          Matter description. Defaults to "<client> — Motor Vehicle Accident".
    --practice-area NAME        Practice area to attach (looked up by name). Default "Personal Injury".
    --status open|pending|closed   New matter status. Default open.
    --billing-method contingency|hourly|flat|pro_bono   Default contingency.
    --responsible-attorney ID|NAME  Responsible attorney. Defaults to the current user (who_am_i).
    --originating-attorney ID|NAME  Originating attorney. Defaults to the responsible attorney.
    --open-date YYYY-MM-DD      Matter open date. Defaults today.
    --client-reference TEXT     Firm file / reference number for the matter.
    --injury-date YYYY-MM-DD    Date of injury. Not stored on the matter; recorded in the plan and
                                echoed as the value to pass to the clio-mva-intake skill next.
    --connection ID            Clio connection id (Maton-Connection header).
    --commit                   Actually create the contact (if new) and the matter in Clio.
"""
import argparse
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://gateway.maton.ai/clio/api/v4"


# --------------------------- Clio API ---------------------------

def _headers(connection=None):
    key = os.environ.get("MATON_API_KEY")
    if not key:
        raise RuntimeError("MATON_API_KEY is not set. See the clio skill for setup.")
    h = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    conn = connection or os.environ.get("CLIO_CONNECTION_ID")
    if conn:
        h["Maton-Connection"] = conn
    return h


def api_get(path, params=None, connection=None):
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, safe="{},")
    req = urllib.request.Request(url, headers=_headers(connection))
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def api_post(path, data, connection=None):
    body = json.dumps({"data": data}).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers=_headers(connection), method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def current_user(connection=None):
    try:
        r = api_get("/users/who_am_i", params={"fields": "id,name"}, connection=connection)
        return r.get("data") or None
    except Exception:  # noqa: BLE001
        return None


# --------------------------- resolution helpers ---------------------------

def split_name(full):
    """'John Doe' -> ('John', 'Doe'); 'Mary Jane Watson' -> ('Mary Jane', 'Watson')."""
    parts = full.split()
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def resolve_client(args, connection):
    """Return (contact|None, candidates|None, error|None, to_create|None).

    - contact: an existing Clio contact to use as the client.
    - candidates: several existing contacts matched the name — caller should disambiguate.
    - to_create: a payload describing the NEW contact we'd create (client not found / no id given).
    Never raises: a dry run should still show a plan even if the API is unreachable.
    """
    fields = "id,name,type,primary_email_address,primary_phone_number"
    try:
        if args.client_id:
            r = api_get(f"/contacts/{args.client_id}", params={"fields": fields}, connection=connection)
            c = r.get("data")
            if c:
                return c, None, None, None
            return None, None, f"contact {args.client_id} not found", None

        name = (args.client or "").strip()
        if name:
            r = api_get("/contacts", params={"fields": fields, "query": name, "limit": 25},
                        connection=connection)
            found = r.get("data", [])
            exact = [c for c in found if (c.get("name") or "").strip().lower() == name.lower()]
            if len(exact) == 1:
                return exact[0], None, None, None
            if len(found) == 1:
                return found[0], None, None, None
            if len(found) > 1:
                return None, found, None, _new_contact_payload(args)
        # nothing matched (or no name given) -> plan to create
        return None, None, None, _new_contact_payload(args)
    except urllib.error.HTTPError as e:
        return None, None, f"HTTP {e.code}", _new_contact_payload(args)
    except Exception as e:  # noqa: BLE001
        return None, None, f"{type(e).__name__}: {e}", _new_contact_payload(args)


def _new_contact_payload(args):
    if args.client_type == "company":
        name = args.client or ""
        payload = {"type": "Company", "name": name}
    else:
        first = args.first_name or ""
        last = args.last_name or ""
        if not (first or last) and args.client:
            first, last = split_name(args.client)
        payload = {"type": "Person", "first_name": first, "last_name": last}
    emails = []
    if args.email:
        emails.append({"name": "Work", "address": args.email, "default_email": True})
    if emails:
        payload["email_addresses"] = emails
    phones = []
    if args.phone:
        phones.append({"name": "Mobile", "number": args.phone, "default_number": True})
    if phones:
        payload["phone_numbers"] = phones
    return payload


def contact_display_name(payload):
    if payload.get("type") == "Company":
        return payload.get("name") or "(unnamed company)"
    return " ".join(x for x in [payload.get("first_name"), payload.get("last_name")] if x) or "(unnamed person)"


def resolve_attorney(spec, connection, fallback=None):
    """spec may be a numeric id, a name substring, or None. Returns (user|None, error|None)."""
    if spec is None:
        return (fallback, None) if fallback else (None, None)
    try:
        if str(spec).isdigit():
            r = api_get(f"/users/{spec}", params={"fields": "id,name"}, connection=connection)
            u = r.get("data")
            return (u, None) if u else (None, f"user {spec} not found")
        r = api_get("/users", params={"fields": "id,name", "query": spec, "limit": 25}, connection=connection)
        users = r.get("data", [])
        if len(users) == 1:
            return users[0], None
        if not users:
            return None, f"no user matched '{spec}'"
        return None, f"multiple users matched '{spec}': " + ", ".join(
            f"{u.get('name')} (#{u.get('id')})" for u in users)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def resolve_practice_area(name, connection):
    """Returns (practice_area|None, error|None). Best-effort; matter can be created without it."""
    if not name:
        return None, None
    try:
        r = api_get("/practice_areas", params={"fields": "id,name", "query": name, "limit": 50},
                    connection=connection)
        areas = r.get("data", [])
        exact = [a for a in areas if (a.get("name") or "").strip().lower() == name.strip().lower()]
        if exact:
            return exact[0], None
        if len(areas) == 1:
            return areas[0], None
        if not areas:
            return None, f"no practice area named '{name}' found"
        return None, "multiple practice areas matched: " + ", ".join(
            f"{a.get('name')} (#{a.get('id')})" for a in areas)
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


# --------------------------- plan + commit ---------------------------

def build_matter_payload(args, client_ref, practice_area, resp_att, orig_att, open_date):
    payload = {
        "description": args.description,
        "status": args.status,
        "open_date": open_date.isoformat(),
        "client": client_ref,  # {"id": N}
    }
    if args.billing_method:
        payload["billing_method"] = args.billing_method
    if args.client_reference:
        payload["client_reference"] = args.client_reference
    if practice_area and practice_area.get("id"):
        payload["practice_area"] = {"id": practice_area["id"]}
    if resp_att and resp_att.get("id"):
        payload["responsible_attorney"] = {"id": resp_att["id"]}
    if orig_att and orig_att.get("id"):
        payload["originating_attorney"] = {"id": orig_att["id"]}
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("client", nargs="?", default=None,
                    help="Client name to find or create (person full name, or company name)")
    ap.add_argument("--client-id", default=None, help="Use this existing Clio contact id as the client")
    ap.add_argument("--client-type", choices=["person", "company"], default="person")
    ap.add_argument("--first-name", default=None)
    ap.add_argument("--last-name", default=None)
    ap.add_argument("--email", default=None)
    ap.add_argument("--phone", default=None)
    ap.add_argument("--description", default=None, help="Matter description (default '<client> — Motor Vehicle Accident')")
    ap.add_argument("--practice-area", default="Personal Injury")
    ap.add_argument("--status", choices=["open", "pending", "closed"], default="open")
    ap.add_argument("--billing-method", choices=["contingency", "hourly", "flat", "pro_bono"], default="contingency")
    ap.add_argument("--responsible-attorney", default=None, help="User id or name (default current user)")
    ap.add_argument("--originating-attorney", default=None, help="User id or name (default responsible attorney)")
    ap.add_argument("--open-date", default=None, help="Matter open date YYYY-MM-DD (defaults today)")
    ap.add_argument("--client-reference", default=None, help="Firm file / reference number")
    ap.add_argument("--injury-date", default=None, help="Date of injury YYYY-MM-DD (for the intake step next)")
    ap.add_argument("--connection", default=None, help="Clio connection id")
    ap.add_argument("--commit", action="store_true", help="Actually create the contact (if new) and matter")
    args = ap.parse_args()

    if not args.client and not args.client_id:
        print(json.dumps({"status": "error",
                          "message": "Provide a client name (positional) or --client-id."}, indent=2))
        return

    connection = args.connection or os.environ.get("CLIO_CONNECTION_ID")
    open_date = dt.date.fromisoformat(args.open_date) if args.open_date else dt.date.today()

    # Client
    client, candidates, client_err, to_create = resolve_client(args, connection)
    if candidates:
        print(json.dumps({"status": "ambiguous_client", "candidates": [
            {"id": c.get("id"), "name": c.get("name"), "type": c.get("type"),
             "email": c.get("primary_email_address")} for c in candidates],
            "next_step": "Pick one and rerun with --client-id, or force a new contact by giving "
                         "--first-name/--last-name (or --client-type company) that don't collide."},
            indent=2))
        return

    client_display = (client or {}).get("name") if client else contact_display_name(to_create)

    # Description default
    if not args.description:
        args.description = f"{client_display} — Motor Vehicle Accident"

    # Attorneys
    me = current_user(connection)
    resp_att, resp_err = resolve_attorney(args.responsible_attorney, connection, fallback=me)
    orig_att, orig_err = resolve_attorney(args.originating_attorney, connection, fallback=resp_att)

    # Practice area
    practice_area, pa_err = resolve_practice_area(args.practice_area, connection)

    warnings = []
    if client_err:
        warnings.append(f"Client lookup: {client_err} — plan will create a new contact if committed.")
    if resp_err:
        warnings.append(f"Responsible attorney: {resp_err}")
    if orig_err:
        warnings.append(f"Originating attorney: {orig_err}")
    if pa_err:
        warnings.append(f"Practice area: {pa_err} — matter would be created without a practice area.")

    plan = {
        "client": {
            "action": "use_existing" if client else "create",
            "existing": client,
            "to_create": None if client else to_create,
            "display_name": client_display,
        },
        "matter": {
            "description": args.description,
            "status": args.status,
            "billing_method": args.billing_method,
            "open_date": open_date.isoformat(),
            "client_reference": args.client_reference,
            "practice_area": practice_area,
            "responsible_attorney": resp_att,
            "originating_attorney": orig_att,
        },
        "injury_date": args.injury_date,
        "warnings": warnings,
    }

    if not args.commit:
        plan["status"] = "dry_run"
        nxt = ("Review this plan, then rerun with --commit to open the matter. "
               "After it exists, run the clio-mva-intake skill on the new matter")
        if args.injury_date:
            nxt += f" with --injury-date {args.injury_date}"
        nxt += " to calendar the Georgia deadlines and create the task checklist."
        plan["next_step"] = nxt
        print(json.dumps(plan, indent=2, default=str))
        return

    # ---- commit ----
    created = {"contact_id": None, "matter_id": None, "errors": []}

    if client:
        client_ref = {"id": client["id"]}
        created["contact_id"] = client["id"]
    else:
        try:
            r = api_post("/contacts", to_create, connection)
            cid = r.get("data", {}).get("id")
            created["contact_id"] = cid
            client_ref = {"id": cid}
        except Exception as e:  # noqa: BLE001
            created["errors"].append(f"create contact: {e}")
            print(json.dumps({"status": "error", "created": created,
                              "message": "Client contact could not be created; matter not opened."},
                             indent=2, default=str))
            return

    payload = build_matter_payload(args, client_ref, practice_area, resp_att, orig_att, open_date)
    try:
        r = api_post("/matters", payload, connection)
        m = r.get("data", {})
        created["matter_id"] = m.get("id")
        created["matter_display_number"] = m.get("display_number")
    except Exception as e:  # noqa: BLE001
        created["errors"].append(f"create matter: {e}")

    result = {"status": "committed" if created["matter_id"] else "error",
              "created": created, "warnings": warnings}
    if created["matter_id"]:
        hand = f"Matter #{created['matter_id']} created. Next: run clio-mva-intake on it"
        if args.injury_date:
            hand += f" with --injury-date {args.injury_date}"
        hand += "."
        result["next_step"] = hand
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
