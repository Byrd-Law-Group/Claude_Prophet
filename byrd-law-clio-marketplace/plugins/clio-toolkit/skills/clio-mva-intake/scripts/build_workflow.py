#!/usr/bin/env python3
"""
Build (and optionally create) the Byrd Law Group MVA pre-litigation workflow on a Clio
matter: standard phase tasks with due-date offsets + calendar entries for the critical
Georgia deadlines, with stacked reminder tasks.

Two-stage by design. It defaults to a DRY RUN that prints the full plan (every task and
deadline with computed dates and assignees) as JSON. Nothing is written to Clio until you
rerun with --commit. Georgia deadlines gate whether a claim survives, so the plan is meant
to be reviewed by a human — and the computed dates verified against current law — before
anything is created.

Usage:
    # Preview the plan (no writes):
    python build_workflow.py "<matter query or id>" --injury-date 2026-05-01

    # After the user reviews and approves, create it:
    python build_workflow.py "<matter id>" --injury-date 2026-05-01 --commit

Key options:
    --injury-date YYYY-MM-DD   Date of injury (drives the PI SOL and ante litem). Required.
    --loss-date  YYYY-MM-DD    Date of property loss (drives the PD SOL). Defaults to injury date.
    --open-date  YYYY-MM-DD    Matter open / intake date (task offsets count from here). Defaults today.
    --defendant municipal|county|state|private   Adds the matching ante litem deadline. Default private.
    --commercial-truck         Include the trucking spoliation / § 9-11-67.1 tasks.
    --minor                    Flag the claim as a minor's (tolled) — emits a warning, computes nothing.
    --assignees FILE.json      Map roles to Clio users: {"attorney": {"id": 1, "type": "User"}, ...}.
                               Roles: intake, case_manager, paralegal, attorney. Unmapped roles fall
                               back to --default-assignee, then to the current user (who_am_i).
    --default-assignee ID      Clio user id to assign any unmapped task/owner to.
    --connection ID            Clio connection id (Maton-Connection header).
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://gateway.maton.ai/clio/api/v4"
TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "references", "mva_template.json")


# --------------------------- date helpers ---------------------------

def parse_date(s):
    return dt.date.fromisoformat(s)


def add_months(d, months):
    """Add whole months to a date, clamping the day to the target month's length
    (e.g. Aug 31 + 6 months -> Feb 28/29). Used for SOL and ante litem math."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    # clamp day
    if month == 12:
        next_month_first = dt.date(year + 1, 1, 1)
    else:
        next_month_first = dt.date(year, month + 1, 1)
    last_day = (next_month_first - dt.timedelta(days=1)).day
    return dt.date(year, month, min(d.day, last_day))


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


def api_patch(path, data, connection=None):
    body = json.dumps({"data": data}).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers=_headers(connection), method="PATCH")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def resolve_matter(query, connection=None):
    """Best-effort. Returns (matter|None, candidates|None, error|None). Never raises —
    a dry run should still be able to show the plan even if the API is unreachable."""
    fields = "id,display_number,description,status,responsible_attorney{id,name}"
    try:
        q = query.strip()
        if q.isdigit():
            r = api_get(f"/matters/{q}", params={"fields": fields}, connection=connection)
            m = r.get("data")
            if m:
                return m, None, None
        r = api_get("/matters", params={"fields": fields, "query": q, "limit": 25}, connection=connection)
        matters = r.get("data", [])
        if len(matters) == 1:
            return matters[0], None, None
        return None, matters, None
    except urllib.error.HTTPError as e:
        return None, None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, None, f"{type(e).__name__}: {e}"


def current_user_id(connection=None):
    try:
        r = api_get("/users/who_am_i", params={"fields": "id,name"}, connection=connection)
        return r.get("data", {}).get("id")
    except Exception:  # noqa: BLE001
        return None


# --------------------------- plan building ---------------------------

def build_plan(tmpl, args, matter):
    open_date = parse_date(args.open_date) if args.open_date else dt.date.today()
    injury = parse_date(args.injury_date)
    loss = parse_date(args.loss_date) if args.loss_date else injury
    today = dt.date.today()

    warnings = []
    if args.minor:
        warnings.append(
            "MINOR'S CLAIM: the standard limitations period is tolled and special rules apply. "
            "No SOL date has been computed — the supervising attorney must confirm the controlling deadline."
        )
    if args.defendant != "private":
        warnings.append(
            f"GOVERNMENT PARTY ({args.defendant}): ante litem notice deadlines are far shorter than the "
            "standard SOL and are easy to miss. Confirm applicability and calendar immediately."
        )

    # --- deadlines ---
    applies_map = {"private": set(), "municipal": {"municipal"}, "county": {"county"}, "state": {"state"}}
    active = applies_map.get(args.defendant, set())
    deadlines = []
    for d in tmpl["deadlines"]:
        if d["applies"] != "always" and d["applies"] not in active:
            continue
        if d["key"] == "sol_pi" and args.minor:
            continue  # tolled — do not compute a PI SOL for a minor
        basis = injury if d["basis"] == "injury_date" else loss
        due = add_months(basis, d["months"])
        reminders = []
        for off in tmpl["reminder_offsets_days"]:
            rd = due - dt.timedelta(days=off)
            reminders.append({"days_before": off, "date": rd.isoformat(), "past": rd < today})
        deadlines.append(
            {
                "key": d["key"],
                "label": d["label"],
                "authority": d["authority"],
                "date": due.isoformat(),
                "basis_date": basis.isoformat(),
                "past": due < today,
                "reminders": reminders,
            }
        )

    # --- phase tasks ---
    tasks = []
    for t in tmpl["phase_tasks"]:
        cond = t.get("applies_if")
        if cond == "commercial_truck" and not args.commercial_truck:
            continue
        if cond == "government" and args.defendant == "private":
            continue
        row = {
            "phase": t["phase"],
            "name": t["name"],
            "owner": t["owner"],
            "priority": t.get("priority", "Normal"),
        }
        if "offset_days" in t:
            row["due_date"] = (open_date + dt.timedelta(days=t["offset_days"])).isoformat()
            row["offset_days"] = t["offset_days"]
        else:
            row["due_date"] = None
            row["trigger"] = t.get("trigger", "Milestone")
        tasks.append(row)

    return {
        "matter": matter,
        "open_date": open_date.isoformat(),
        "injury_date": injury.isoformat(),
        "loss_date": loss.isoformat(),
        "defendant_type": args.defendant,
        "commercial_truck": args.commercial_truck,
        "minor": args.minor,
        "counts": {
            "tasks": len(tasks),
            "deadlines": len(deadlines),
            "reminders": sum(len(d["reminders"]) for d in deadlines),
        },
        "deadlines": deadlines,
        "tasks": tasks,
        "warnings": warnings,
    }


# --------------------------- commit ---------------------------

def resolve_assignees(args, matter, connection):
    mapping = {}
    if args.assignees and os.path.exists(args.assignees):
        with open(args.assignees) as f:
            mapping = json.load(f)
    default_id = args.default_assignee
    if default_id is None:
        ra = (matter or {}).get("responsible_attorney") or {}
        default_id = ra.get("id") or current_user_id(connection)
    return mapping, default_id


def assignee_for(owner, mapping, default_id):
    if owner in mapping:
        a = mapping[owner]
        return {"id": a["id"], "type": a.get("type", "User")}
    if default_id is not None:
        return {"id": default_id, "type": "User"}
    return None


def commit(plan, tmpl, args, matter, connection):
    if not matter:
        raise RuntimeError("Cannot commit without a resolved matter. Rerun with an exact matter id.")
    mapping, default_id = resolve_assignees(args, matter, connection)
    mid = matter["id"]
    created = {"tasks": [], "reminders": [], "calendar_entries": [], "errors": []}
    owner_id = default_id  # calendar owner + deadline reminder assignee

    # Phase tasks
    for t in plan["tasks"]:
        assignee = assignee_for(t["owner"], mapping, default_id)
        if assignee is None:
            created["errors"].append(f"No assignee for task '{t['name']}'")
            continue
        data = {"name": f"[P{t['phase']}] {t['name']}", "priority": t["priority"],
                "assignee": assignee, "matter": {"id": mid}}
        if t["due_date"]:
            data["due_at"] = f"{t['due_date']}T17:00:00Z"
        try:
            r = api_post("/tasks", data, connection)
            created["tasks"].append(r.get("data", {}).get("id"))
        except Exception as e:  # noqa: BLE001
            created["errors"].append(f"task '{t['name']}': {e}")

    # Deadlines -> calendar entries (+ matter link via PATCH) and reminder tasks
    for d in plan["deadlines"]:
        summary = f"⚠️ DEADLINE: {d['label']} ({d['authority']})"
        if owner_id is not None:
            try:
                r = api_post(
                    "/calendar_entries",
                    {"summary": summary, "start_at": d["date"], "end_at": d["date"],
                     "all_day": True, "calendar_owner": {"id": owner_id, "type": "User"}},
                    connection,
                )
                cid = r.get("data", {}).get("id")
                created["calendar_entries"].append(cid)
                if cid:
                    try:
                        api_patch(f"/calendar_entries/{cid}", {"matter": {"id": mid}}, connection)
                    except Exception:  # noqa: BLE001 - matter link is best-effort per Clio quirk
                        pass
            except Exception as e:  # noqa: BLE001
                created["errors"].append(f"calendar '{d['label']}': {e}")
        # reminder tasks (skip ones already in the past)
        rem_assignee = assignee_for("case_manager", mapping, default_id)
        for rem in d["reminders"]:
            if rem["past"] or rem_assignee is None:
                continue
            try:
                r = api_post(
                    "/tasks",
                    {"name": f"Reminder ({rem['days_before']}d): {d['label']} due {d['date']}",
                     "priority": "High", "due_at": f"{rem['date']}T09:00:00Z",
                     "assignee": rem_assignee, "matter": {"id": mid}},
                    connection,
                )
                created["reminders"].append(r.get("data", {}).get("id"))
            except Exception as e:  # noqa: BLE001
                created["errors"].append(f"reminder '{d['label']}' {rem['days_before']}d: {e}")

    return created


# --------------------------- main ---------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="Matter id, display number, client name, or description words")
    ap.add_argument("--injury-date", required=True, help="Date of injury YYYY-MM-DD")
    ap.add_argument("--loss-date", default=None, help="Date of property loss YYYY-MM-DD (defaults to injury date)")
    ap.add_argument("--open-date", default=None, help="Matter open/intake date YYYY-MM-DD (defaults today)")
    ap.add_argument("--defendant", choices=["private", "municipal", "county", "state"], default="private")
    ap.add_argument("--commercial-truck", action="store_true")
    ap.add_argument("--minor", action="store_true")
    ap.add_argument("--assignees", default=None, help="Path to role->user JSON mapping")
    ap.add_argument("--default-assignee", type=int, default=None, help="Fallback Clio user id")
    ap.add_argument("--connection", default=None, help="Clio connection id")
    ap.add_argument("--commit", action="store_true", help="Actually create tasks/calendar entries in Clio")
    args = ap.parse_args()

    with open(TEMPLATE) as f:
        tmpl = json.load(f)

    connection = args.connection or os.environ.get("CLIO_CONNECTION_ID")
    matter, candidates, err = resolve_matter(args.query, connection=connection)

    if matter is None and candidates:
        print(json.dumps({"status": "ambiguous", "candidates": [
            {"id": c.get("id"), "display_number": c.get("display_number"),
             "description": c.get("description"), "status": c.get("status")} for c in candidates]}, indent=2))
        return
    if matter is None and args.commit:
        print(json.dumps({"status": "error",
                          "message": f"Could not resolve matter to commit ({err or 'not found'}). "
                                     "Rerun with an exact matter id."}, indent=2))
        return

    plan = build_plan(tmpl, args, matter)
    if matter is None:
        plan["matter_note"] = f"Matter not resolved ({err or 'not found'}); showing plan only. " \
                              "Provide an exact matter id to link and commit."

    if not args.commit:
        plan["status"] = "dry_run"
        plan["next_step"] = "Review this plan (verify every deadline against current Georgia law), then " \
                            "rerun with --commit and an exact matter id to create it in Clio."
        print(json.dumps(plan, indent=2, default=str))
        return

    created = commit(plan, tmpl, args, matter, connection)
    print(json.dumps({"status": "committed", "matter_id": matter["id"], "created": created,
                      "warnings": plan["warnings"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
