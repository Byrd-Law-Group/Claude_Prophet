#!/usr/bin/env python3
"""Firm-wide deadline & statute-of-limitations radar for Clio Manage.

Sweeps EVERY open matter for hard legal deadlines — statutes of limitation,
Georgia ante litem notices, court/hearing/trial/mediation dates, and demand
response deadlines — from both calendar entries and tasks, buckets them by
urgency, and (critically) flags open matters that have NO statute-of-limitations
deadline on the calendar at all. A missing SOL is the scariest gap in a PI book.

Read-only. Emits one JSON blob on stdout; the skill turns it into a triage report.

Usage:
    python deadline_radar.py [--horizon-days 365] [--sol-scan-days 1830]
                             [--include-pending] [--connection <id>]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://gateway.maton.ai/clio/api/v4"
# The Maton gateway occasionally returns a transient 401/429/5xx during token
# refresh; the same request then succeeds. Retry these a few times.
RETRY_CODES = {401, 429, 500, 502, 503, 504}

# Deadline classification by keyword (matched case-insensitively against the
# calendar-entry summary or task name). Order matters: first match wins.
CLASSIFIERS = [
    ("statute_of_limitations", re.compile(r"statute of limitation|limitation period|\bsol\b", re.I)),
    ("ante_litem", re.compile(r"ante[\s-]?litem", re.I)),
    ("court", re.compile(r"\bhearing\b|\btrial\b|\bmediation\b|\bdeposition\b|\bcourt\b|arbitration", re.I)),
    ("filing", re.compile(r"file suit|complaint filing|answer due|discovery due|response to", re.I)),
    ("demand_response", re.compile(r"demand.*(response|deadline)|response.*demand|time[\s-]?limited demand", re.I)),
]


def _now_utc():
    return dt.datetime.now(dt.timezone.utc)


def _headers(connection=None):
    key = os.environ.get("MATON_API_KEY")
    if not key:
        print(json.dumps({"error": "MATON_API_KEY is not set. See the clio skill for setup."}))
        sys.exit(2)
    h = {"Authorization": f"Bearer {key}"}
    conn = connection or os.environ.get("MATON_CONNECTION") or os.environ.get("CLIO_CONNECTION_ID")
    if conn:
        h["Maton-Connection"] = conn
    return h


def _fetch(url, headers):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in RETRY_CODES and attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def _next_token(payload):
    """Pull page_token out of Clio's `next` URL. We must NOT follow that URL
    directly — it points at app.clio.com and bypasses the Maton gateway's token
    injection (yielding a 401). Re-request through the gateway with the token."""
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
        payload = _fetch(url, headers)
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


def _safe_get(path, params=None, connection=None):
    try:
        return api_get(path, params=params, connection=connection), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} on {path}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__} on {path}: {e}"


def _iso(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
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


def classify(text):
    if not text:
        return None
    for kind, rx in CLASSIFIERS:
        if rx.search(text):
            return kind
    return None


def bucket(days):
    if days is None:
        return "undated"
    if days < 0:
        return "overdue"
    if days <= 30:
        return "d30"
    if days <= 60:
        return "d60"
    if days <= 90:
        return "d90"
    if days <= 180:
        return "d180"
    return "beyond"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon-days", type=int, default=365,
                    help="How far ahead to report deadlines (default 365).")
    ap.add_argument("--sol-scan-days", type=int, default=1830,
                    help="Wider window used only to detect whether an SOL exists (default 1830 ~ 5y).")
    ap.add_argument("--include-pending", action="store_true",
                    help="Also include matters with status 'pending', not just 'open'.")
    ap.add_argument("--connection", default=None)
    args = ap.parse_args()
    conn = args.connection
    now = _now_utc()
    warnings = []

    # --- All open (and optionally pending) matters ---
    statuses = ["open"] + (["pending"] if args.include_pending else [])
    matters = []
    for st in statuses:
        m, err = _safe_get("/matters", params={
            "fields": "id,display_number,description,status,client{id,name},"
                      "responsible_attorney{id,name}",
            "status": st, "limit": 200,
        }, connection=conn)
        if err:
            warnings.append(f"matters({st}): {err}")
        matters.extend(m or [])
    matters_by_id = {m["id"]: m for m in matters}

    # --- Calendar entries across the firm (wide window for SOL presence check) ---
    # Clio requires xmlschema datetimes (…T00:00:00Z), not bare dates.
    def _dt(d):
        return d.strftime("%Y-%m-%dT%H:%M:%SZ")
    horizon = now + dt.timedelta(days=max(args.horizon_days, args.sol_scan_days))
    cal, cal_err = _safe_get("/calendar_entries", params={
        "fields": "id,summary,start_at,all_day,matter{id}",
        "from": _dt(now), "to": _dt(horizon), "limit": 200,
    }, connection=conn)
    if cal_err:
        warnings.append(f"calendar_entries: {cal_err}")
    cal = cal or []

    # --- Tasks across the firm (open only) ---
    tasks, task_err = _safe_get("/tasks", params={
        "fields": "id,name,status,due_at,priority,matter{id},assignee{id,name}",
        "status": "pending", "limit": 200,
    }, connection=conn)
    if task_err:
        warnings.append(f"tasks: {task_err}")
    tasks = tasks or []
    # If BOTH deadline sources failed, we read no deadlines at all — a "missing
    # SOL" verdict would be a false alarm. Track that so we can suppress it.
    deadline_sources_ok = (cal_err is None) or (task_err is None)

    # --- Collect classified deadlines, keyed by matter ---
    deadlines = []
    sol_matter_ids = set()  # matters that have SOME SOL deadline on record

    for c in cal:
        mid = (c.get("matter") or {}).get("id")
        if mid not in matters_by_id:
            continue
        kind = classify(c.get("summary"))
        if not kind:
            continue
        d = _days_until(_iso(c.get("start_at")), now)
        if kind == "statute_of_limitations":
            sol_matter_ids.add(mid)
        if d is not None and d <= args.horizon_days:
            deadlines.append({"matter_id": mid, "kind": kind, "source": "calendar",
                              "label": c.get("summary"), "date": c.get("start_at"),
                              "days_until": round(d, 1), "bucket": bucket(d)})

    for t in tasks:
        mid = (t.get("matter") or {}).get("id")
        if mid not in matters_by_id:
            continue
        kind = classify(t.get("name"))
        if not kind:
            continue
        d = _days_until(_iso(t.get("due_at")), now)
        if kind == "statute_of_limitations":
            sol_matter_ids.add(mid)
        if d is None or d <= args.horizon_days:
            deadlines.append({"matter_id": mid, "kind": kind, "source": "task",
                              "label": t.get("name"), "date": t.get("due_at"),
                              "days_until": round(d, 1) if d is not None else None,
                              "bucket": bucket(d),
                              "assignee": (t.get("assignee") or {}).get("name")})

    def matter_label(mid):
        m = matters_by_id.get(mid, {})
        return {"id": mid, "display_number": m.get("display_number"),
                "description": (m.get("description") or "").split("\n")[0][:80],
                "client": (m.get("client") or {}).get("name"),
                "attorney": (m.get("responsible_attorney") or {}).get("name"),
                "status": m.get("status")}

    for d in deadlines:
        d["matter"] = matter_label(d["matter_id"])

    # Sort: overdue first, then soonest.
    order = {"overdue": 0, "d30": 1, "d60": 2, "d90": 3, "d180": 4, "beyond": 5, "undated": 6}
    deadlines.sort(key=lambda x: (order.get(x["bucket"], 9),
                                  x["days_until"] if x["days_until"] is not None else 1e9))

    # Matters with NO statute of limitations anywhere on record within the scan
    # window. Only trustworthy if we could actually read the deadline sources.
    if deadline_sources_ok:
        missing_sol = [matter_label(mid) for mid in matters_by_id
                       if mid not in sol_matter_ids]
        missing_sol_reliable = True
    else:
        missing_sol = []
        missing_sol_reliable = False
        warnings.append("SOL-presence check skipped: could not read calendar entries "
                        "or tasks, so 'missing SOL' cannot be determined.")

    buckets = {}
    for d in deadlines:
        buckets.setdefault(d["bucket"], []).append(d)

    print(json.dumps({
        "status": "ok",
        "generated_at": now.isoformat(),
        "horizon_days": args.horizon_days,
        "sol_scan_days": args.sol_scan_days,
        "counts": {
            "open_matters": len(matters_by_id),
            "deadlines_in_horizon": len(deadlines),
            "overdue": len(buckets.get("overdue", [])),
            "matters_missing_sol": len(missing_sol),
            "missing_sol_reliable": missing_sol_reliable,
        },
        "deadlines": deadlines,
        "buckets": {k: buckets.get(k, []) for k in
                    ["overdue", "d30", "d60", "d90", "d180", "beyond", "undated"]},
        "matters_missing_sol": missing_sol,
        "warnings": warnings,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
