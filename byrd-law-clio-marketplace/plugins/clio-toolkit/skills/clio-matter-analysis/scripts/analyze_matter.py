#!/usr/bin/env python3
"""
Pull a single matter's full picture from Clio Manage and compute deadline / task-risk
signals. Emits one JSON blob on stdout that the skill turns into a readable report.

Why a script instead of ad-hoc API calls: every matter analysis needs the same
multi-endpoint fetch (matter + tasks + calendar + activities + documents + bills),
the same client-side matter filtering where the API doesn't filter server-side, and
the same date math for "overdue" / "due soon". Doing it once here keeps every
invocation consistent and cheap.

Usage:
    python analyze_matter.py "<matter query or numeric id>" [--soon-days 14] [--connection <id>]

The query can be a numeric matter id (used directly), a display number
(e.g. "00123-Smith"), a client name, or words from the matter description.
If several matters match, the script returns the candidate list instead of an
analysis so the caller can disambiguate with the user.
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


def _now_utc():
    return dt.datetime.now(dt.timezone.utc)


def _headers():
    key = os.environ.get("MATON_API_KEY")
    if not key:
        print(
            json.dumps({"error": "MATON_API_KEY is not set. See the clio skill for setup."}),
            flush=True,
        )
        sys.exit(2)
    h = {"Authorization": f"Bearer {key}"}
    conn = os.environ.get("CLIO_CONNECTION_ID")
    if conn:
        h["Maton-Connection"] = conn
    return h


def api_get(path, params=None, connection=None):
    """GET a Clio endpoint, following cursor pagination, returning the merged `data` list
    (or the single object for a /{id} fetch). Raises on non-recoverable errors."""
    params = dict(params or {})
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, safe="{},")
    headers = _headers()
    if connection:
        headers["Maton-Connection"] = connection

    merged = []
    single = None
    while True:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
        data = payload.get("data")
        if isinstance(data, list):
            merged.extend(data)
        else:
            single = data
        # Clio's `next` URL points at app.clio.com and bypasses the Maton
        # gateway's OAuth injection (page 2+ would 401). Re-request through the
        # gateway with the page_token instead of following that URL directly.
        nxt = (payload.get("meta") or {}).get("paging", {}).get("next")
        if not nxt:
            break
        tok = urllib.parse.parse_qs(urllib.parse.urlparse(nxt).query).get("page_token")
        if not tok:
            break
        params["page_token"] = tok[0]
        url = f"{BASE}{path}?" + urllib.parse.urlencode(params, safe="{},")
    return single if single is not None else merged


def _safe_get(path, params=None, connection=None):
    """Like api_get but degrades gracefully: some endpoints need extra OAuth scopes
    (activities, documents, bills) and may 4xx. We record why rather than crash the
    whole analysis over one unavailable section."""
    try:
        return api_get(path, params=params, connection=connection), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} on {path}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__} on {path}: {e}"


def resolve_matter(query, connection=None):
    """Return (matter_dict, candidates_list). If exactly one match -> (matter, None).
    If ambiguous/none -> (None, candidates)."""
    fields = (
        "id,display_number,description,status,open_date,close_date,client_reference,"
        "client{id,name},responsible_attorney{id,name},practice_area{id,name}"
    )
    q = query.strip()
    if q.isdigit():
        matter, err = _safe_get(f"/matters/{q}", params={"fields": fields}, connection=connection)
        if matter:
            return matter, None
        # fall through to search if the id lookup failed

    # Clio supports a free-text `query` param on /matters that matches display number,
    # description, and client name.
    matters, err = _safe_get(
        "/matters",
        params={"fields": fields, "query": q, "limit": 25},
        connection=connection,
    )
    matters = matters or []
    if len(matters) == 1:
        return matters[0], None
    return None, matters


def _iso(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        # date-only value
        try:
            return dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return None


def _days_until(when, now):
    if not when:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return (when - now).total_seconds() / 86400.0


def analyze(matter, soon_days, connection=None):
    now = _now_utc()
    mid = matter["id"]
    warnings = []

    # --- Tasks (server-side matter filter is well supported) ---
    tasks, err = _safe_get(
        "/tasks",
        params={
            "fields": "id,name,status,due_at,priority,assignee{id,name}",
            "matter_id": mid,
            "limit": 200,
        },
        connection=connection,
    )
    if err:
        warnings.append(f"tasks: {err}")
    tasks = tasks or []

    # --- Activities / time entries (may require extra scope) ---
    activities, err = _safe_get(
        "/activities",
        params={
            "fields": "id,type,date,quantity,total,note",
            "matter_id": mid,
            "limit": 100,
            "order": "date(desc)",
        },
        connection=connection,
    )
    if err:
        warnings.append(f"activities: {err}")
    activities = activities or []

    # --- Calendar entries: the API doesn't reliably filter by matter, so fetch a
    #     forward window and filter client-side on the matter association. ---
    horizon = (now + dt.timedelta(days=180)).date().isoformat()
    cal, err = _safe_get(
        "/calendar_entries",
        params={
            "fields": "id,summary,start_at,end_at,all_day,matter{id}",
            "from": now.date().isoformat(),
            "to": horizon,
            "limit": 200,
        },
        connection=connection,
    )
    if err:
        warnings.append(f"calendar_entries: {err}")
    cal = [c for c in (cal or []) if (c.get("matter") or {}).get("id") == mid]

    # --- Documents (may require extra scope) ---
    docs, err = _safe_get(
        "/documents",
        params={"fields": "id,name,content_type,created_at,updated_at", "matter_id": mid, "limit": 100},
        connection=connection,
    )
    if err:
        warnings.append(f"documents: {err}")
    docs = docs or []

    # --- Bills (may require extra scope; matter filter support varies) ---
    bills, err = _safe_get(
        "/bills",
        params={"fields": "id,number,issued_at,due_at,total,balance,state", "matter_id": mid, "limit": 100},
        connection=connection,
    )
    if err:
        warnings.append(f"bills: {err}")
    bills = bills or []

    # ---------- Risk computation ----------
    def is_open_task(t):
        return (t.get("status") or "").lower() not in ("complete", "completed")

    overdue, due_soon, upcoming_tasks = [], [], []
    for t in tasks:
        if not is_open_task(t):
            continue
        d = _days_until(_iso(t.get("due_at")), now)
        row = {
            "id": t["id"],
            "name": t.get("name"),
            "due_at": t.get("due_at"),
            "priority": t.get("priority"),
            "assignee": (t.get("assignee") or {}).get("name"),
            "days_until": round(d, 1) if d is not None else None,
        }
        if d is None:
            upcoming_tasks.append(row)
        elif d < 0:
            overdue.append(row)
        elif d <= soon_days:
            due_soon.append(row)
        else:
            upcoming_tasks.append(row)

    upcoming_events = []
    for c in cal:
        d = _days_until(_iso(c.get("start_at")), now)
        upcoming_events.append(
            {
                "id": c["id"],
                "summary": c.get("summary"),
                "start_at": c.get("start_at"),
                "all_day": c.get("all_day"),
                "days_until": round(d, 1) if d is not None else None,
            }
        )

    overdue.sort(key=lambda r: (r["days_until"] if r["days_until"] is not None else 0))
    due_soon.sort(key=lambda r: (r["days_until"] if r["days_until"] is not None else 1e9))
    upcoming_events.sort(key=lambda r: (r["days_until"] if r["days_until"] is not None else 1e9))

    # Staleness: most recent activity date.
    last_activity = None
    for a in activities:
        d = _iso(a.get("date"))
        if d and (last_activity is None or d > last_activity):
            last_activity = d
    days_since_activity = None
    if last_activity:
        days_since_activity = round((now - last_activity).total_seconds() / 86400.0, 1)

    # Time totals (quantity is seconds).
    total_seconds = sum((a.get("quantity") or 0) for a in activities if a.get("type") in ("TimeEntry", None))
    outstanding_balance = sum((b.get("balance") or 0) for b in bills)

    return {
        "matter": matter,
        "generated_at": now.isoformat(),
        "soon_days": soon_days,
        "risk": {
            "overdue_tasks": overdue,
            "tasks_due_soon": due_soon,
            "upcoming_events": upcoming_events,
            "days_since_last_activity": days_since_activity,
            "open_task_count": sum(1 for t in tasks if is_open_task(t)),
        },
        "tasks_all": tasks,
        "activities_recent": activities[:25],
        "calendar_upcoming": upcoming_events,
        "documents": {"count": len(docs), "recent": docs[:10]},
        "billing": {
            "unbilled_hours_est": round(total_seconds / 3600.0, 2),
            "outstanding_balance": outstanding_balance,
            "bills": bills,
        },
        "warnings": warnings,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", help="Matter id, display number, client name, or description words")
    ap.add_argument("--soon-days", type=int, default=14, help="Window (days) counted as 'due soon'")
    ap.add_argument("--connection", default=None, help="Clio connection id (Maton-Connection)")
    args = ap.parse_args()

    connection = args.connection or os.environ.get("CLIO_CONNECTION_ID")
    matter, candidates = resolve_matter(args.query, connection=connection)
    if matter is None:
        print(
            json.dumps(
                {
                    "status": "ambiguous" if candidates else "not_found",
                    "query": args.query,
                    "candidates": [
                        {
                            "id": c.get("id"),
                            "display_number": c.get("display_number"),
                            "description": c.get("description"),
                            "client": (c.get("client") or {}).get("name"),
                            "status": c.get("status"),
                        }
                        for c in (candidates or [])
                    ],
                },
                indent=2,
            )
        )
        return

    result = analyze(matter, args.soon_days, connection=connection)
    result["status"] = "ok"
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
