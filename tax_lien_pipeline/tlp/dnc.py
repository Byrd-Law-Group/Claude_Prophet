"""Do-Not-Call scrubbing via a third-party vendor (The Blacklist Alliance).

Turns a phone number into a DNC verdict the compliance gate can trust:
  'listed'  -> on a suppression / DNC / known-litigator list; never call/text.
  'clear'   -> the vendor affirmatively cleared it; eligible for outreach
               (still subject to the rest of the compliance gate).
  'unknown' -> we could not get a trustworthy answer (no API key, network
               error, unexpected payload). This FAILS SAFE: the pipeline keeps
               'unknown' numbers mail_only until a lawful consent basis is
               recorded, so an outage can never open a contact path.

The Blacklist Alliance (https://www.blacklistalliance.com/) exposes a simple
GET lookup that returns a per-number JSON verdict covering the National + state
DNC registries, known TCPA-litigator lists, and wireless identification. Set
BLACKLIST_API_KEY in the environment to enable it; leave it unset to keep the
pipeline in preview / mail-only mode.

stdlib only (urllib), matching the rest of the pipeline. This module never
raises to its caller -- every failure path returns 'unknown'.
"""
import json
import urllib.parse
import urllib.request

from . import config

# Vendor `results` strings we treat as "do not contact".
_LISTED_RESULTS = {"bad", "dnc", "litigator", "blacklist", "listed"}
# Vendor `results` strings we treat as affirmatively clean.
_CLEAR_RESULTS = {"good", "clean", "clear", "safe"}
# Explicit per-list flags that force 'listed' regardless of the summary verdict.
_LISTED_FLAGS = ("litigator", "dnc", "is_dnc", "blacklisted", "federal_dnc",
                 "state_dnc")


def check(phone, *, timeout=10):
    """Query the vendor for `phone`. Returns 'listed' | 'clear' | 'unknown'.

    Never raises: any missing key, network error, or unexpected response
    returns 'unknown' so the caller fails safe.
    """
    if not config.BLACKLIST_API_KEY or not phone:
        return "unknown"
    params = urllib.parse.urlencode({
        "key": config.BLACKLIST_API_KEY,
        "phone": phone,
        "response": "json",
    })
    url = "%s?%s" % (config.BLACKLIST_API_URL, params)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if status != 200:
                return "unknown"
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return "unknown"
    return classify(payload)


def classify(payload):
    """Map a vendor JSON payload to our verdict, defensively.

    Note: the vendor's `status` field reports API-call success ("success"),
    NOT the number's verdict -- the verdict is `results` (e.g. "good"/"bad").
    We deliberately do not read `status` as a verdict. Anything we don't
    recognize returns 'unknown' (fail safe), never a false 'clear'.
    """
    if not isinstance(payload, dict):
        return "unknown"
    # An explicit litigator / DNC flag is decisive and beats the summary.
    for flag in _LISTED_FLAGS:
        if _truthy(payload.get(flag)):
            return "listed"
    verdict = None
    for key in ("results", "result"):
        val = payload.get(key)
        if isinstance(val, str):
            verdict = val.strip().lower()
            break
    if verdict in _LISTED_RESULTS:
        return "listed"
    if verdict in _CLEAR_RESULTS:
        return "clear"
    return "unknown"


def _truthy(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "t")
    return False
