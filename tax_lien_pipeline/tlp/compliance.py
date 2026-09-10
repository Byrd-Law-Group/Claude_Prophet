"""Compliance engine — the gate every outbound touch must pass.

This module is deliberately conservative. It would rather block a borderline
contact than expose you to a TCPA claim ($500-$1,500 per violation), a
Do-Not-Call penalty, or an Ohio homeowner-protection issue.

What it enforces:
  * Do-Not-Call / suppression scrubbing before a number is contact-eligible.
  * Calling/texting only 8:00 AM - 9:00 PM in the recipient's local time.
  * Per-lead attempt caps (anti-harassment).
  * Permanent opt-out honoring.

DNC scrubbing is delegated to a vendor (The Blacklist Alliance) via `tlp.dnc`.
Set BLACKLIST_API_KEY to enable it; without a key, or on any vendor error,
numbers resolve to 'unknown' and are NOT auto-eligible for calling/texting —
you must supply consent or a documented prior business relationship, or
contact by mail. This fail-safe means an outage can never open a contact path.
"""
import datetime

from . import config, db, dnc

try:
    from zoneinfo import ZoneInfo
    _LOCAL_TZ = ZoneInfo(config.LOCAL_TZ)
except Exception:  # pragma: no cover - fallback if tzdata unavailable
    _LOCAL_TZ = None


def within_calling_hours(when=None):
    """True if `when` (aware/naive UTC) falls inside the legal local window."""
    when = when or datetime.datetime.now(datetime.timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    if _LOCAL_TZ is not None:
        local = when.astimezone(_LOCAL_TZ)
    else:
        # Conservative fallback: approximate Eastern as UTC-5 (ignores DST).
        local = when.astimezone(datetime.timezone(datetime.timedelta(hours=-5)))
    return config.CALL_WINDOW_START_HOUR <= local.hour < config.CALL_WINDOW_END_HOUR


def scrub_number(conn, phone):
    """Return a DNC status for a phone number: 'listed', 'clear', or 'unknown'.

    Checks the local suppression list first (covers prior opt-outs and any
    DNC numbers you've imported) so a suppressed number never triggers a
    billable vendor lookup. If not locally suppressed, defers to the DNC
    vendor (`tlp.dnc.check`), which returns 'clear' / 'listed' / 'unknown'.
    'unknown' (no API key or a vendor error) fails safe -> mail_only.
    """
    if db.is_suppressed(conn, phone):
        return "listed"
    return dnc.check(phone)


def scrub_lead(conn, lead):
    """Compute dnc_status + channel_eligibility for a lead row and persist it.

    Returns the resulting channel_eligibility string.
    """
    lead_id = lead["id"]
    phone = lead["phone"]

    if lead["opt_out"]:
        db.update_lead(conn, lead_id, channel_eligibility="do_not_contact",
                       status="opt_out")
        return "do_not_contact"

    if not phone:
        db.update_lead(conn, lead_id, channel_eligibility="mail_only",
                       status="scrubbed")
        return "mail_only"

    status = scrub_number(conn, phone)
    checked_at = db.now()

    if status == "listed":
        db.update_lead(conn, lead_id, dnc_status="listed",
                       dnc_checked_at=checked_at,
                       channel_eligibility="mail_only", status="scrubbed")
        return "mail_only"

    consent = lead["consent_status"]
    if status == "clear" or consent in ("express_written", "prior_business"):
        # Clear DNC, or a lawful basis to contact despite unknown DNC.
        db.update_lead(conn, lead_id, dnc_status=status,
                       dnc_checked_at=checked_at,
                       channel_eligibility="call_text", status="scrubbed")
        return "call_text"

    # Unknown DNC and no consent -> do not auto-queue calls/texts; mail only.
    db.update_lead(conn, lead_id, dnc_status="unknown",
                   dnc_checked_at=checked_at,
                   channel_eligibility="mail_only", status="scrubbed")
    return "mail_only"


def can_contact(conn, lead, channel, when=None):
    """Gatekeeper: may we send `channel` ('sms'|'call') to this lead now?

    Returns (ok: bool, reason: str). Every send path must call this and
    respect a False -- there are no overrides in code for opt-outs or hours.
    """
    if lead["opt_out"] or db.is_suppressed(conn, lead["phone"]):
        return False, "opted_out_or_suppressed"

    if not lead["phone"]:
        return False, "no_phone"

    eligibility = lead["channel_eligibility"]
    if eligibility in ("do_not_contact", "mail_only", "unscrubbed", None):
        return False, "not_contact_eligible:%s" % eligibility

    if not lead["approved"]:
        return False, "not_human_approved"

    if db.count_attempts(conn, lead["id"]) >= config.MAX_ATTEMPTS_PER_LEAD:
        return False, "attempt_cap_reached"

    if not within_calling_hours(when):
        return False, "outside_calling_hours"

    return True, "ok"


def record_opt_out(conn, phone, lead_id=None):
    """Permanently opt a number out across all channels."""
    db.suppress(conn, phone, reason="opt_out")
    if lead_id is None:
        norm = db.normalize_phone(phone)
        row = conn.execute(
            "SELECT id FROM leads WHERE phone = ? OR phone = ?",
            (phone, norm),
        ).fetchone()
        lead_id = row["id"] if row else None
    if lead_id is not None:
        db.update_lead(conn, lead_id, opt_out=1, opt_out_at=db.now(),
                       channel_eligibility="do_not_contact", status="opt_out")
        db.add_touch(conn, lead_id, channel="sms", direction="inbound",
                     outcome="opt_out", notes="STOP / opt-out honored")
    conn.commit()
