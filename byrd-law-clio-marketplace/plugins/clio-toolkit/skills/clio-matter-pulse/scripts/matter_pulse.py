#!/usr/bin/env python3
"""Firm-wide 'matter pulse' — find open matters going quiet.

For every open matter, compute the most recent 'touch' (activity/time entry, note,
or logged communication) and flag matters with no touch in N days, or none at all.
PI clients fire firms over silence; this catches the quiet ones before they churn.

Read-only. Emits JSON on stdout; the skill turns it into a report and can hand
stale matters to clio-client-update to draft check-in texts.

Usage:
    python matter_pulse.py [--stale-days 21] [--include-pending] [--connection <id>]
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://gateway.maton.ai/clio/api/v4"
RETRY_CODES = {401, 429, 500, 502, 503, 504}


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
    """Extract page_token from Clio's `next` URL. Following that URL directly hits
    app.clio.com and bypasses the Maton gateway's token injection (401); re-request
    through the gateway with the token instead."""
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


def _date(s):
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Date-only values parse as offset-naive; force UTC so arithmetic with an
    # aware `now` doesn't blow up.
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stale-days", type=int, default=21,
                    help="Flag matters with no touch in this many days (default 21).")
    ap.add_argument("--include-pending", action="store_true")
    ap.add_argument("--connection", default=None)
    args = ap.parse_args()
    conn = args.connection
    now = _now_utc()
    warnings = []

    statuses = ["open"] + (["pending"] if args.include_pending else [])
    matters = []
    for st in statuses:
        m, err = _safe_get("/matters", params={
            "fields": "id,display_number,description,status,open_date,updated_at,"
                      "client{id,name},responsible_attorney{id,name}",
            "status": st, "limit": 200,
        }, connection=conn)
        if err:
            warnings.append(f"matters({st}): {err}")
        matters.extend(m or [])
    by_id = {m["id"]: m for m in matters}
    # last_touch[mid] = (datetime, source)
    last_touch = {}

    def note_touch(mid, when, source):
        if mid not in by_id or not when:
            return
        cur = last_touch.get(mid)
        if cur is None or when > cur[0]:
            last_touch[mid] = (when, source)

    # Activities / time entries (may need extra scope).
    acts, err = _safe_get("/activities", params={
        "fields": "id,date,type,matter{id}", "limit": 200, "order": "date(desc)",
    }, connection=conn)
    if err:
        warnings.append(f"activities: {err}")
    for a in acts or []:
        note_touch((a.get("matter") or {}).get("id"), _date(a.get("date")), "activity")

    # Notes on matters.
    notes, err = _safe_get("/notes", params={
        "type": "Matter", "fields": "id,date,created_at,matter{id}", "limit": 200,
    }, connection=conn)
    if err:
        warnings.append(f"notes: {err}")
    for n in notes or []:
        note_touch((n.get("matter") or {}).get("id"),
                   _date(n.get("date")) or _date(n.get("created_at")), "note")

    # Logged communications (phone/email/text) — best 'client contact' signal; optional scope.
    comms, err = _safe_get("/communications", params={
        "fields": "id,date,type,matter{id}", "limit": 200, "order": "date(desc)",
    }, connection=conn)
    if err:
        warnings.append(f"communications: {err}")
    for c in comms or []:
        note_touch((c.get("matter") or {}).get("id"), _date(c.get("date")), "communication")

    rows = []
    for mid, m in by_id.items():
        touch = last_touch.get(mid)
        if touch:
            days = round((now - touch[0]).total_seconds() / 86400.0, 1)
            last_iso, source = touch[0].isoformat(), touch[1]
        else:
            # No touch at all — fall back to open_date age so it sorts sensibly.
            od = _date(m.get("open_date"))
            days = round((now - od).total_seconds() / 86400.0, 1) if od else None
            last_iso, source = None, "none"
        rows.append({
            "matter": {"id": mid, "display_number": m.get("display_number"),
                       "description": (m.get("description") or "").split("\n")[0][:80],
                       "client": (m.get("client") or {}).get("name"),
                       "attorney": (m.get("responsible_attorney") or {}).get("name"),
                       "status": m.get("status")},
            "last_touch": last_iso, "last_touch_source": source,
            "days_since_touch": days,
            "stale": (days is None) or (days >= args.stale_days),
        })

    rows.sort(key=lambda r: (r["days_since_touch"] is not None,
                             -(r["days_since_touch"] or 0)))
    stale = [r for r in rows if r["stale"]]

    print(json.dumps({
        "status": "ok",
        "generated_at": now.isoformat(),
        "stale_days": args.stale_days,
        "counts": {"open_matters": len(by_id), "stale": len(stale),
                   "no_contact_ever": sum(1 for r in rows if r["last_touch_source"] == "none")},
        "stale_matters": stale,
        "all_matters": rows,
        "warnings": warnings,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
