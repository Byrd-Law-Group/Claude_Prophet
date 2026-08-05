#!/usr/bin/env python3
"""
Generic Clio workflow engine. Applies a named workflow template (a checklist of tasks, plus
optional calculated deadlines) to a Clio matter. New workflows are added by dropping a JSON
file in templates/ — no code changes.

Preview-first, like all writing tools here: it dry-runs by default and only creates anything
in Clio with --commit. That matters because these tasks and deadlines drive real casework.

Usage:
    # See available workflows:
    python apply_workflow.py --list

    # Preview applying a workflow to a matter (no writes):
    python apply_workflow.py "<matter query or id>" --template mva-prelit \
        --date injury_date=2026-05-01 --flag defendant=state --flag commercial_truck=true

    # After the user approves, create it:
    python apply_workflow.py "<matter id>" --template mva-prelit \
        --date injury_date=2026-05-01 --assignees roles.json --commit

Templates declare the date inputs and flags they need; run --template X --describe (or just
preview) and the engine tells you what's missing.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://gateway.maton.ai/clio/api/v4"
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")


# --------------------------- date + condition helpers ---------------------------

def parse_date(s):
    return dt.date.fromisoformat(s)


def add_months(d, months):
    """Add whole months to a date, clamping to the target month's last day."""
    m = d.month - 1 + months
    year = d.year + m // 12
    month = m % 12 + 1
    if month == 12:
        nxt = dt.date(year + 1, 1, 1)
    else:
        nxt = dt.date(year, month + 1, 1)
    last = (nxt - dt.timedelta(days=1)).day
    return dt.date(year, month, min(d.day, last))


def cond_true(expr, flags):
    """Evaluate a simple condition against flag values.
    Supported: '' / 'always' -> True; 'key' -> truthy; 'key==value'; 'key!=value'."""
    if not expr or expr == "always":
        return True
    for op in ("==", "!="):
        if op in expr:
            k, v = (x.strip() for x in expr.split(op, 1))
            actual = str(flags.get(k, "")).lower()
            want = v.lower()
            return (actual == want) if op == "==" else (actual != want)
    return bool(flags.get(expr))


def coerce_flag(raw, spec):
    if spec and spec.get("type") == "bool":
        return str(raw).lower() in ("1", "true", "yes", "y", "on")
    return raw


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


def api_write(path, data, method, connection=None):
    body = json.dumps({"data": data}).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers=_headers(connection), method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def resolve_matter(query, connection=None):
    fields = "id,display_number,description,status,responsible_attorney{id,name}"
    try:
        q = query.strip()
        if q.isdigit():
            r = api_get(f"/matters/{q}", params={"fields": fields}, connection=connection)
            if r.get("data"):
                return r["data"], None, None
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
        return api_get("/users/who_am_i", params={"fields": "id"}, connection=connection).get("data", {}).get("id")
    except Exception:  # noqa: BLE001
        return None


# --------------------------- templates ---------------------------

def list_templates():
    out = []
    for path in sorted(glob.glob(os.path.join(TEMPLATE_DIR, "*.json"))):
        try:
            t = json.load(open(path))
            out.append({"name": t.get("name", os.path.splitext(os.path.basename(path))[0]),
                        "description": t.get("description", ""),
                        "practice_area": t.get("practice_area", ""),
                        "tasks": len(t.get("tasks", [])),
                        "deadlines": len(t.get("deadlines", []))})
        except Exception as e:  # noqa: BLE001
            out.append({"name": os.path.basename(path), "error": str(e)})
    return out


def load_template(name):
    path = os.path.join(TEMPLATE_DIR, name if name.endswith(".json") else name + ".json")
    if not os.path.exists(path):
        raise FileNotFoundError(name)
    return json.load(open(path))


def resolve_dates(tmpl, date_args):
    """Turn the template's date_inputs + user-provided --date values into a {key: date} map.
    Returns (dates, missing_required_keys)."""
    provided = {}
    for kv in date_args or []:
        k, _, v = kv.partition("=")
        provided[k.strip()] = v.strip()
    dates = {}
    missing = []
    today = dt.date.today()
    for spec in tmpl.get("date_inputs", []):
        key = spec["key"]
        if key in provided and provided[key]:
            dates[key] = parse_date(provided[key])
        elif spec.get("default") == "today":
            dates[key] = today
        elif spec.get("default_from") and dates.get(spec["default_from"]):
            dates[key] = dates[spec["default_from"]]
        elif spec.get("required"):
            missing.append(key)
    # allow ad-hoc dates not declared in the template
    for k, v in provided.items():
        if k not in dates and v:
            dates[k] = parse_date(v)
    return dates, missing


def resolve_flags(tmpl, flag_args):
    provided = {}
    for kv in flag_args or []:
        k, _, v = kv.partition("=")
        provided[k.strip()] = v.strip()
    flags = {}
    for spec in tmpl.get("flags", []):
        key = spec["key"]
        if key in provided:
            flags[key] = coerce_flag(provided[key], spec)
        elif "default" in spec:
            flags[key] = spec["default"]
    for k, v in provided.items():
        if k not in flags:
            flags[k] = v
    return flags


# --------------------------- plan ---------------------------

def build_plan(tmpl, dates, flags, matter):
    today = dt.date.today()
    anchor_key = tmpl.get("anchor_date", "open_date")
    anchor = dates.get(anchor_key) or today
    reminder_offsets = tmpl.get("reminder_offsets_days", [])
    warnings = []

    deadlines = []
    for d in tmpl.get("deadlines", []):
        if not cond_true(d.get("applies", "always"), flags):
            continue
        if d.get("skip_if") and cond_true(d["skip_if"], flags):
            warnings.append(f"{d['label']}: skipped ({d['skip_if']} is set) — confirm the controlling deadline with the attorney.")
            continue
        basis = dates.get(d["basis"])
        if not basis:
            warnings.append(f"{d['label']}: needs date '{d['basis']}' which was not provided; deadline not computed.")
            continue
        months = d.get("months", d.get("years", 0) * 12)
        due = add_months(basis, months)
        reminders = [{"days_before": off, "date": (due - dt.timedelta(days=off)).isoformat(),
                      "past": (due - dt.timedelta(days=off)) < today} for off in reminder_offsets]
        deadlines.append({"key": d.get("key"), "label": d["label"], "authority": d.get("authority", ""),
                          "date": due.isoformat(), "basis_date": basis.isoformat(),
                          "past": due < today, "reminders": reminders})

    tasks = []
    for t in tmpl.get("tasks", []):
        if not cond_true(t.get("applies_if", "always"), flags):
            continue
        row = {"name": t["name"], "owner": t.get("owner", "unassigned"),
               "priority": t.get("priority", "Normal"), "phase": t.get("phase")}
        if "offset_days" in t:
            base = dates.get(t.get("anchor", anchor_key)) or anchor
            row["due_date"] = (base + dt.timedelta(days=t["offset_days"])).isoformat()
            row["offset_days"] = t["offset_days"]
        else:
            row["due_date"] = None
            row["trigger"] = t.get("trigger", "Milestone")
        tasks.append(row)

    return {
        "template": tmpl.get("name"),
        "matter": matter,
        "dates": {k: v.isoformat() for k, v in dates.items()},
        "flags": flags,
        "counts": {"tasks": len(tasks), "deadlines": len(deadlines),
                   "reminders": sum(len(d["reminders"]) for d in deadlines)},
        "deadlines": deadlines,
        "tasks": tasks,
        "warnings": warnings,
    }


# --------------------------- commit ---------------------------

def resolve_assignees(args, matter, connection):
    mapping = {}
    if args.assignees and os.path.exists(args.assignees):
        mapping = json.load(open(args.assignees))
    default_id = args.default_assignee
    if default_id is None:
        default_id = ((matter or {}).get("responsible_attorney") or {}).get("id") or current_user_id(connection)
    return mapping, default_id


def assignee_for(owner, mapping, default_id):
    if owner in mapping:
        a = mapping[owner]
        return {"id": a["id"], "type": a.get("type", "User")}
    return {"id": default_id, "type": "User"} if default_id is not None else None


def commit(plan, args, matter, connection):
    if not matter:
        raise RuntimeError("Cannot commit without a resolved matter. Rerun with an exact matter id.")
    mapping, default_id = resolve_assignees(args, matter, connection)
    mid = matter["id"]
    created = {"tasks": [], "reminders": [], "calendar_entries": [], "errors": []}

    for t in plan["tasks"]:
        assignee = assignee_for(t["owner"], mapping, default_id)
        if assignee is None:
            created["errors"].append(f"No assignee for task '{t['name']}'")
            continue
        prefix = f"[P{t['phase']}] " if t.get("phase") else ""
        data = {"name": f"{prefix}{t['name']}", "priority": t["priority"],
                "assignee": assignee, "matter": {"id": mid}}
        if t["due_date"]:
            data["due_at"] = f"{t['due_date']}T17:00:00Z"
        try:
            created["tasks"].append(api_write("/tasks", data, "POST", connection).get("data", {}).get("id"))
        except Exception as e:  # noqa: BLE001
            created["errors"].append(f"task '{t['name']}': {e}")

    for d in plan["deadlines"]:
        summary = f"⚠️ DEADLINE: {d['label']}" + (f" ({d['authority']})" if d['authority'] else "")
        if default_id is not None:
            try:
                r = api_write("/calendar_entries",
                              {"summary": summary, "start_at": d["date"], "end_at": d["date"],
                               "all_day": True, "calendar_owner": {"id": default_id, "type": "User"}},
                              "POST", connection)
                cid = r.get("data", {}).get("id")
                created["calendar_entries"].append(cid)
                if cid:
                    try:
                        api_write(f"/calendar_entries/{cid}", {"matter": {"id": mid}}, "PATCH", connection)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as e:  # noqa: BLE001
                created["errors"].append(f"calendar '{d['label']}': {e}")
        rem_assignee = assignee_for("case_manager", mapping, default_id) or assignee_for("_default", mapping, default_id)
        for rem in d["reminders"]:
            if rem["past"] or rem_assignee is None:
                continue
            try:
                created["reminders"].append(api_write(
                    "/tasks",
                    {"name": f"Reminder ({rem['days_before']}d): {d['label']} due {d['date']}",
                     "priority": "High", "due_at": f"{rem['date']}T09:00:00Z",
                     "assignee": rem_assignee, "matter": {"id": mid}},
                    "POST", connection).get("data", {}).get("id"))
            except Exception as e:  # noqa: BLE001
                created["errors"].append(f"reminder '{d['label']}' {rem['days_before']}d: {e}")

    return created


# --------------------------- main ---------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", help="Matter id, display number, client, or description")
    ap.add_argument("--template", help="Template name (see --list)")
    ap.add_argument("--date", action="append", help="Date input key=YYYY-MM-DD (repeatable)")
    ap.add_argument("--flag", action="append", help="Flag key=value (repeatable)")
    ap.add_argument("--assignees", help="Path to role->user JSON mapping")
    ap.add_argument("--default-assignee", type=int, help="Fallback Clio user id")
    ap.add_argument("--connection", help="Clio connection id")
    ap.add_argument("--list", action="store_true", help="List available templates and exit")
    ap.add_argument("--describe", action="store_true", help="Show a template's required inputs and exit")
    ap.add_argument("--commit", action="store_true", help="Actually create tasks/deadlines in Clio")
    args = ap.parse_args()

    if args.list:
        print(json.dumps({"templates": list_templates()}, indent=2))
        return

    if not args.template:
        print(json.dumps({"status": "error", "message": "Provide --template NAME (or --list)."}))
        return
    try:
        tmpl = load_template(args.template)
    except FileNotFoundError:
        print(json.dumps({"status": "error", "message": f"Template '{args.template}' not found. Try --list."}))
        return

    if args.describe:
        print(json.dumps({"name": tmpl.get("name"), "description": tmpl.get("description"),
                          "date_inputs": tmpl.get("date_inputs", []), "flags": tmpl.get("flags", []),
                          "anchor_date": tmpl.get("anchor_date", "open_date")}, indent=2))
        return

    connection = args.connection or os.environ.get("CLIO_CONNECTION_ID")
    dates, missing = resolve_dates(tmpl, args.date)
    if missing:
        print(json.dumps({"status": "missing_inputs", "template": tmpl.get("name"),
                          "missing_required_dates": missing,
                          "hint": "Provide each with --date key=YYYY-MM-DD."}, indent=2))
        return
    flags = resolve_flags(tmpl, args.flag)

    matter, candidates, err = resolve_matter(args.query, connection) if args.query else (None, None, "no matter given")
    if matter is None and candidates:
        print(json.dumps({"status": "ambiguous", "candidates": [
            {"id": c.get("id"), "display_number": c.get("display_number"),
             "description": c.get("description"), "status": c.get("status")} for c in candidates]}, indent=2))
        return
    if matter is None and args.commit:
        print(json.dumps({"status": "error",
                          "message": f"Could not resolve matter to commit ({err}). Use an exact matter id."}))
        return

    plan = build_plan(tmpl, dates, flags, matter)
    if matter is None:
        plan["matter_note"] = f"Matter not resolved ({err}); showing plan only. Provide an exact id to commit."

    if not args.commit:
        plan["status"] = "dry_run"
        plan["next_step"] = "Review the plan (verify any legal deadlines against current law), then rerun with --commit and an exact matter id."
        print(json.dumps(plan, indent=2, default=str))
        return

    created = commit(plan, args, matter, connection)
    print(json.dumps({"status": "committed", "matter_id": matter["id"], "template": tmpl.get("name"),
                      "created": created, "warnings": plan["warnings"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
