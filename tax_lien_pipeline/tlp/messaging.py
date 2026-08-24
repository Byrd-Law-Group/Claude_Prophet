"""Twilio SMS + click-to-dial, using only the stdlib (urllib).

No `twilio` package required. Every send routes through compliance.can_contact
first -- there is no path in this module that skips the gate. Actual
transmission only happens when Twilio credentials are set AND a human has
approved the lead (leads.approved = 1).

Voice: `initiate_call` uses click-to-dial -- Twilio rings YOUR phone first,
then bridges you to the homeowner. You are always live on the call; this is
manual, one-to-one dialing, not an autodialer or a robocall.
"""
import base64
import json
import urllib.parse
import urllib.request

from . import config, compliance, db, outreach

API_BASE = "https://api.twilio.com/2010-04-01"


class SendResult:
    def __init__(self, ok, detail, sid=None):
        self.ok = ok
        self.detail = detail
        self.sid = sid

    def __repr__(self):
        return "SendResult(ok=%s, detail=%r, sid=%r)" % (self.ok, self.detail, self.sid)


def _twilio_post(path, params):
    """POST form-encoded params to Twilio; return (ok, parsed_or_error)."""
    if not config.twilio.configured:
        return False, "twilio_not_configured"
    url = "%s/Accounts/%s/%s" % (API_BASE, config.twilio.account_sid, path)
    data = urllib.parse.urlencode(params).encode("utf-8")
    auth = base64.b64encode(
        ("%s:%s" % (config.twilio.account_sid, config.twilio.auth_token)).encode()
    ).decode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", "Basic %s" % auth)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read().decode())
        except Exception:
            return False, "http_error:%s" % e.code
    except Exception as e:  # network, timeout, etc.
        return False, "request_error:%s" % e


def send_sms(conn, lead, dry_run=False, approved_by="human"):
    """Send (or preview) a compliant SMS to a lead. Returns SendResult."""
    ok, reason = compliance.can_contact(conn, lead, "sms")
    if not ok:
        return SendResult(False, "blocked:%s" % reason)

    body = outreach.draft_sms(lead)
    to = db.normalize_phone(lead["phone"])

    if dry_run or not config.twilio.configured:
        db.add_touch(conn, lead["id"], "sms", "outbound", "queued",
                     message_body=body, approved_by=approved_by,
                     notes="dry_run" if dry_run else "twilio_not_configured")
        conn.commit()
        return SendResult(False if not config.twilio.configured else True,
                          "preview_only", None)

    sent_ok, result = _twilio_post(
        "Messages.json",
        {"To": to, "From": config.twilio.from_number, "Body": body},
    )
    if sent_ok:
        sid = result.get("sid")
        db.add_touch(conn, lead["id"], "sms", "outbound", "sent",
                     message_body=body, provider_sid=sid, approved_by=approved_by)
        db.update_lead(conn, lead["id"], status="contacted")
        conn.commit()
        return SendResult(True, "sent", sid)

    db.add_touch(conn, lead["id"], "sms", "outbound", "failed",
                 message_body=body, notes=str(result), approved_by=approved_by)
    conn.commit()
    return SendResult(False, "send_failed:%s" % result)


def initiate_call(conn, lead, dry_run=False, approved_by="human"):
    """Click-to-dial: ring the investor, then bridge to the homeowner."""
    ok, reason = compliance.can_contact(conn, lead, "call")
    if not ok:
        return SendResult(False, "blocked:%s" % reason)

    to = db.normalize_phone(lead["phone"])
    investor = config.twilio.investor_number

    if dry_run or not config.twilio.configured or not investor:
        db.add_touch(conn, lead["id"], "call", "outbound", "queued",
                     approved_by=approved_by,
                     notes="preview: would dial %s, bridge to %s" % (investor, to))
        conn.commit()
        return SendResult(False if not config.twilio.configured else True,
                          "preview_only", None)

    # Ring the investor first; on answer, TwiML dials the homeowner.
    twiml = "<Response><Say>Connecting your tax lien call.</Say><Dial>%s</Dial></Response>" % to
    sent_ok, result = _twilio_post(
        "Calls.json",
        {"To": investor, "From": config.twilio.from_number, "Twiml": twiml},
    )
    if sent_ok:
        sid = result.get("sid")
        db.add_touch(conn, lead["id"], "call", "outbound", "sent",
                     provider_sid=sid, approved_by=approved_by,
                     notes="click-to-dial bridged")
        db.update_lead(conn, lead["id"], status="contacted")
        conn.commit()
        return SendResult(True, "dialing", sid)

    db.add_touch(conn, lead["id"], "call", "outbound", "failed",
                 notes=str(result), approved_by=approved_by)
    conn.commit()
    return SendResult(False, "call_failed:%s" % result)
