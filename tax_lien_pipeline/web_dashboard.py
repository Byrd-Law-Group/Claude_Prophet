#!/usr/bin/env python3
"""Local web dashboard to review, approve, and send tax-lien outreach.

Runs a small stdlib HTTP server (no framework). Bind is LOCALHOST ONLY because
this handles homeowner PII and can trigger real sends. Every send still passes
through the same compliance gate and the human-approval requirement as the CLI.

Run:  python3 web_dashboard.py --port 8000
Then open http://127.0.0.1:8000
"""
import argparse
import html
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from tlp import db, compliance, outreach, messaging, config

STYLE = """
body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1c1e21}
header{background:#1f2d3d;color:#fff;padding:14px 22px;display:flex;justify-content:space-between;align-items:center}
header h1{font-size:18px;margin:0}
header .env{font-size:12px;opacity:.8}
.wrap{max-width:1100px;margin:20px auto;padding:0 16px}
table{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)}
th,td{padding:9px 11px;text-align:left;border-bottom:1px solid #eee;font-size:14px}
th{background:#eef1f5;font-weight:600}
tr:hover td{background:#fafbfc}
a{color:#2a6bd4;text-decoration:none}a:hover{text-decoration:underline}
.pill{display:inline-block;padding:2px 8px;border-radius:11px;font-size:12px;font-weight:600}
.call_text{background:#d7f5dd;color:#146c2e}.mail_only{background:#fde8cf;color:#8a4b00}
.do_not_contact,.opt_out{background:#fbdcdc;color:#9b1c1c}.unscrubbed{background:#e3e6ea;color:#555}
.yes{color:#146c2e;font-weight:600}.no{color:#9b1c1c}
.card{background:#fff;border-radius:8px;padding:18px 20px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:18px}
.grid{display:grid;grid-template-columns:180px 1fr;gap:6px 14px;font-size:14px}
.grid div:nth-child(odd){color:#666}
pre{background:#f3f4f6;padding:12px;border-radius:6px;white-space:pre-wrap;font:13px/1.5 ui-monospace,Menlo,monospace}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:12px}
button{font:14px inherit;padding:8px 14px;border:0;border-radius:6px;cursor:pointer}
.primary{background:#2a6bd4;color:#fff}.approve{background:#146c2e;color:#fff}
.danger{background:#9b1c1c;color:#fff}.ghost{background:#e3e6ea;color:#222}
form.inline{display:inline}
.banner{padding:10px 14px;border-radius:6px;margin-bottom:14px;font-size:14px}
.ok{background:#d7f5dd;color:#146c2e}.warn{background:#fde8cf;color:#8a4b00}.err{background:#fbdcdc;color:#9b1c1c}
select,input,textarea{font:14px inherit;padding:6px;border:1px solid #ccc;border-radius:5px}
.filters a{margin-right:12px}
small{color:#777}
"""

STATUSES = ["all", "new", "scrubbed", "queued", "contacted", "interested",
            "not_interested", "opt_out"]


def esc(v):
    return html.escape("" if v is None else str(v))


def money(v):
    return "${:,.0f}".format(v) if v else "-"


def page(body, env_note):
    return ("<!doctype html><meta charset=utf-8><title>Tax-Lien Outreach</title>"
            "<style>%s</style>"
            "<header><h1>Tax-Lien Acquisition &mdash; Outreach Dashboard</h1>"
            "<span class=env>%s</span></header><div class=wrap>%s</div>"
            % (STYLE, env_note, body))


def env_note():
    if config.twilio.configured:
        return "LIVE: Twilio configured &mdash; sends will transmit"
    return "PREVIEW MODE: Twilio not configured &mdash; sends are logged as drafts"


def render_list(conn, status, msg=None):
    where = "" if status in (None, "all") else "WHERE status = ?"
    params = () if status in (None, "all") else (status,)
    rows = conn.execute(
        "SELECT * FROM leads %s ORDER BY priority_score DESC, amount_owed DESC" % where,
        params).fetchall()
    filt = " ".join(
        '<a href="/?status=%s"><b>%s</b></a>' % (s, s) if s == (status or "all")
        else '<a href="/?status=%s">%s</a>' % (s, s) for s in STATUSES)
    trs = []
    for l in rows:
        elig = l["channel_eligibility"] or "unscrubbed"
        trs.append(
            "<tr><td><a href='/lead?id=%s'>#%s</a></td><td>%s</td><td>%s</td>"
            "<td>%s</td><td>%s</td><td>%s</td><td><span class='pill %s'>%s</span></td>"
            "<td>%s</td><td class='%s'>%s</td></tr>" % (
                l["id"], l["id"], esc(l["owner_name"]), esc(l["situs_address"]),
                money(l["amount_owed"]), money(l["assessed_value"]),
                l["priority_score"], elig, elig, esc(l["status"]),
                "yes" if l["approved"] else "no", "yes" if l["approved"] else "no"))
    banner = "<div class='banner ok'>%s</div>" % msg if msg else ""
    return page(
        "%s<div class=filters style='margin:6px 0 14px'>%s</div>"
        "<table><tr><th>ID</th><th>Owner</th><th>Address</th><th>Owed</th>"
        "<th>Value</th><th>Score</th><th>Eligible</th><th>Status</th><th>Approved</th></tr>"
        "%s</table><p><small>%d leads. Ranked by priority.</small></p>"
        % (banner, filt, "".join(trs), len(rows)), env_note())


def render_lead(conn, lead_id, msg=None, msg_class="ok"):
    l = db.get_lead(conn, lead_id)
    if not l:
        return page("<p>No lead %s. <a href='/'>Back</a></p>" % lead_id, env_note())
    sms = outreach.draft_sms(l)
    script = outreach.draft_call_script(l)
    ok_sms, reason_sms = compliance.can_contact(conn, l, "sms")
    fields = ["parcel_id", "owner_name", "situs_address", "owner_mailing_address",
              "amount_owed", "assessed_value", "equity_estimate", "years_delinquent",
              "owner_occupied", "phone", "email", "dnc_status", "consent_status",
              "channel_eligibility", "opt_out", "status", "priority_score", "source"]
    grid = "".join("<div>%s</div><div>%s</div>" % (f, esc(l[f])) for f in fields)
    touches = conn.execute(
        "SELECT ts,channel,direction,outcome,notes FROM touches WHERE lead_id=? ORDER BY ts",
        (lead_id,)).fetchall()
    trows = "".join(
        "<tr><td>%s</td><td>%s/%s</td><td>%s</td><td>%s</td></tr>" % (
            esc(t["ts"])[:19], esc(t["channel"]), esc(t["direction"]),
            esc(t["outcome"]), esc(t["notes"])) for t in touches) or \
        "<tr><td colspan=4><small>No touches yet.</small></td></tr>"

    def hidden(): return "<input type=hidden name=id value=%s>" % lead_id
    approve_btn = ("<span class='pill call_text'>approved</span>" if l["approved"]
                   else "<form class=inline method=post action=/approve>%s"
                        "<button class=approve>Approve for outreach</button></form>" % hidden())
    consent_form = (
        "<form class=inline method=post action=/consent>%s"
        "<select name=basis><option value=prior_business>prior_business</option>"
        "<option value=express_written>express_written</option>"
        "<option value=none>none</option></select> "
        "<button class=ghost>Set consent</button></form>" % hidden())
    send_disabled = "" if ok_sms else "disabled title='%s'" % esc(reason_sms)
    send_forms = (
        "<form class=inline method=post action=/send-sms onsubmit=\"return confirm('Send/queue SMS to this homeowner?')\">%s"
        "<button class=primary %s>Send SMS</button></form>"
        "<form class=inline method=post action=/call onsubmit=\"return confirm('Start click-to-dial call?')\">%s"
        "<button class=primary %s>Click-to-dial</button></form>" % (
            hidden(), send_disabled, hidden(), send_disabled))
    log_form = (
        "<form class=inline method=post action=/log>%s"
        "<select name=outcome><option>no_answer</option><option>interested</option>"
        "<option>not_interested</option><option>callback</option>"
        "<option>left_voicemail</option><option>opt_out</option></select> "
        "<select name=channel><option>call</option><option>sms</option></select> "
        "<input name=notes placeholder='notes'> "
        "<button class=ghost>Log outcome</button></form>" % hidden())
    optout_form = (
        "<form class=inline method=post action=/optout onsubmit=\"return confirm('Permanently opt out this contact?')\">%s"
        "<button class=danger>Opt out (STOP)</button></form>" % hidden())

    banner = "<div class='banner %s'>%s</div>" % (msg_class, msg) if msg else ""
    gate = ("<span class='yes'>YES</span>" if ok_sms
            else "<span class='no'>NO (%s)</span>" % esc(reason_sms))
    return page(
        "%s<p><a href='/'>&larr; All leads</a></p>"
        "<div class=card><h2>%s &mdash; %s</h2><div class=grid>%s</div>"
        "<div class=actions>%s %s</div>"
        "<p><small>Send-eligible right now: %s</small></p></div>"
        "<div class=card><h3>SMS draft <small>(%d chars)</small></h3><pre>%s</pre>"
        "<h3>Call script</h3><pre>%s</pre>"
        "<div class=actions>%s</div></div>"
        "<div class=card><h3>Log a contact outcome</h3>%s</div>"
        "<div class=card><h3>Touch history</h3><table><tr><th>When</th><th>Channel</th>"
        "<th>Outcome</th><th>Notes</th></tr>%s</table></div>"
        % (banner, esc(l["owner_name"]), esc(l["situs_address"]), grid,
           approve_btn, consent_form, gate, len(sms), esc(sms), esc(script),
           send_forms, log_form, trows),
        env_note())


class Handler(BaseHTTPRequestHandler):
    def _send(self, body, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        conn = db.init_db()
        try:
            if parsed.path == "/":
                self._send(render_list(conn, qs.get("status", ["all"])[0],
                                       msg=qs.get("msg", [None])[0]))
            elif parsed.path == "/lead":
                self._send(render_lead(conn, int(qs.get("id", ["0"])[0]),
                                       msg=qs.get("msg", [None])[0],
                                       msg_class=qs.get("mc", ["ok"])[0]))
            else:
                self._send("<p>Not found. <a href='/'>Home</a></p>", 404)
        finally:
            conn.close()

    def _form(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode() if length else ""
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

    def do_POST(self):
        form = self._form()
        lead_id = int(form.get("id", "0"))
        conn = db.init_db()
        try:
            path = self.path
            msg, mc = None, "ok"
            l = db.get_lead(conn, lead_id)
            if not l:
                self._redirect("/"); return
            if path == "/approve":
                db.update_lead(conn, lead_id, approved=1, status="queued"); conn.commit()
                msg = "Approved for outreach."
            elif path == "/consent":
                db.update_lead(conn, lead_id, consent_status=form.get("basis", "none"))
                elig = compliance.scrub_lead(conn, db.get_lead(conn, lead_id)); conn.commit()
                msg = "Consent set; eligibility now: %s" % elig
            elif path == "/send-sms":
                res = messaging.send_sms(conn, l)
                msg = "SMS %s" % ("sent (%s)" % res.sid if res.ok and res.sid
                                  else res.detail)
                mc = "ok" if res.ok or res.detail == "preview_only" else "err"
            elif path == "/call":
                res = messaging.initiate_call(conn, l)
                msg = "Call %s" % (res.detail if not res.ok else "dialing (%s)" % res.sid)
                mc = "ok" if res.ok or res.detail == "preview_only" else "err"
            elif path == "/log":
                outcome = form.get("outcome", "no_answer")
                db.add_touch(conn, lead_id, channel=form.get("channel", "call"),
                             direction="outbound", outcome=outcome,
                             notes=form.get("notes") or None)
                smap = {"interested": "interested", "not_interested": "not_interested",
                        "opt_out": "opt_out", "callback": "interested"}
                if outcome in smap:
                    db.update_lead(conn, lead_id, status=smap[outcome])
                if outcome == "opt_out":
                    compliance.record_opt_out(conn, l["phone"], lead_id=lead_id)
                conn.commit()
                msg = "Logged '%s'." % outcome
            elif path == "/optout":
                compliance.record_opt_out(conn, l["phone"], lead_id=lead_id)
                msg = "Contact opted out and suppressed."; mc = "warn"
            else:
                self._redirect("/"); return
            self._redirect("/lead?id=%s&msg=%s&mc=%s" % (
                lead_id, urllib.parse.quote(msg or ""), mc))
        finally:
            conn.close()

    def log_message(self, *a):  # silence default noisy logging
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    db.init_db()
    # Localhost only: this exposes PII and can trigger sends.
    srv = HTTPServer(("127.0.0.1", args.port), Handler)
    print("Dashboard: http://127.0.0.1:%d  (%s)  Ctrl-C to stop"
          % (args.port, "LIVE" if config.twilio.configured else "PREVIEW"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
