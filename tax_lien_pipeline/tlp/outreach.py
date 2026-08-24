"""Draft personalized, compliant call scripts and SMS messages from lead data.

Tone rules (baked in, per the agent spec and Ohio homeowner-protection law):
  * Lead with honesty and the homeowner's benefit.
  * Identify the caller by real name + company (no impersonating the county).
  * Use only verified facts; never invent an amount or a deadline.
  * No false urgency; encourage the owner to verify and get their own advice.
  * Every SMS is identified and carries an opt-out.
"""
from . import config


def _first_name(owner_name):
    if not owner_name:
        return "there"
    # Owner records are often "LAST FIRST" or "LAST, FIRST".
    name = owner_name.strip()
    if "," in name:
        parts = name.split(",")
        first = parts[1].strip().split(" ")[0] if len(parts) > 1 else parts[0]
    else:
        toks = name.split()
        first = toks[-1] if len(toks) > 1 else toks[0]
    return first.title() if first else "there"


def _amount_phrase(amount):
    if not amount:
        return "your back property taxes"
    return "about ${:,.0f} in back property taxes".format(amount)


def _short_address(lead):
    return lead["situs_address"] or "your property"


def draft_sms(lead):
    """Return a compliant SMS body (<= ~320 chars, opt-out appended)."""
    name = _first_name(lead["owner_name"])
    addr = _short_address(lead)
    body = (
        "Hi {name}, this is {caller} with {company}. I buy homes in the Dayton "
        "area and can pay off {amount} on {addr} so it doesn't go to tax sale. "
        "Would you consider selling? No pressure - happy to explain. {suffix}"
    ).format(
        name=name,
        caller=config.CALLER_NAME,
        company=config.COMPANY_NAME,
        amount=_amount_phrase(lead["amount_owed"]),
        addr=addr,
        suffix=config.SMS_OPT_OUT_SUFFIX,
    )
    return body


def draft_call_script(lead):
    """Return a warm, low-pressure phone script identifying the caller."""
    name = _first_name(lead["owner_name"])
    addr = _short_address(lead)
    amount = _amount_phrase(lead["amount_owed"])
    return """\
CALL SCRIPT  (identify yourself first - required by law)

Opener:
  "Hi, is this {name}? My name is {caller} with {company}. I'm a local real
   estate buyer here in the Dayton area - I'm not with the county or any
   government office. Do you have a quick minute?"

Purpose:
  "I came across public records showing {addr} has {amount} owed. I help
   owners in that spot by buying the property and paying off those back taxes,
   so it doesn't end up at a tax sale. I wanted to see if selling is something
   you'd even consider."

If interested:
  "Great - I'd want to confirm the exact payoff with the Treasurer and take a
   look at the property. I'll also suggest you run anything past your own
   attorney or tax advisor before you decide anything. What's the best way and
   time to follow up?"

If not / not now:
  "Totally understand - I appreciate the minute. If anything changes you can
   reach me at {callback}. Take care."

If they ask to stop contacting:
  "Of course - I'll take you off my list right now and won't reach out again."
  --> Log the opt-out immediately.

Never say: that the county sent you, that they'll lose the home by a specific
date, or that this is their only option. Use only verified numbers.
""".format(
        name=name,
        caller=config.CALLER_NAME,
        company=config.COMPANY_NAME,
        addr=addr,
        amount=amount,
        callback=config.CALLBACK_NUMBER,
    )
