"""Configuration and lightweight .env loading (stdlib only)."""
import os

# Target market defaults (Montgomery County, Ohio / Dayton area)
DEFAULT_MARKET = "Montgomery County, OH"
LOCAL_TZ = "America/New_York"  # Eastern time governs calling hours here

# Legal calling/texting window in the recipient's local time.
CALL_WINDOW_START_HOUR = 8   # 8:00 AM
CALL_WINDOW_END_HOUR = 21    # 9:00 PM (exclusive)

# Cap contact attempts per lead to avoid harassment claims.
MAX_ATTEMPTS_PER_LEAD = 4

# Required opt-out language appended to every outbound SMS.
SMS_OPT_OUT_SUFFIX = "Reply STOP to opt out."

# DNC scrubbing vendor (The Blacklist Alliance). Leave the key unset to keep
# the pipeline in preview / mail-only mode -- numbers stay 'unknown' and are
# never auto-eligible for calls/texts without a recorded consent basis.
BLACKLIST_API_KEY = os.environ.get("BLACKLIST_API_KEY", "")
BLACKLIST_API_URL = os.environ.get(
    "BLACKLIST_API_URL", "https://api.blacklistalliance.net/lookup"
)

DB_PATH = os.environ.get(
    "TLP_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "leads.db"),
)


def _load_env_file(path):
    """Minimal KEY=VALUE .env parser so we don't need python-dotenv."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            # Do not clobber values already set in the real environment.
            os.environ.setdefault(key, val)


# Load repo-root .env if present (does not override real env vars).
_repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_load_env_file(os.path.join(_repo_root, ".env"))


class TwilioConfig:
    """Reads Twilio credentials from the environment when needed."""

    @property
    def account_sid(self):
        return os.environ.get("TWILIO_ACCOUNT_SID", "")

    @property
    def auth_token(self):
        return os.environ.get("TWILIO_AUTH_TOKEN", "")

    @property
    def from_number(self):
        # E.164, e.g. +19375551234
        return os.environ.get("TWILIO_FROM_NUMBER", "")

    @property
    def investor_number(self):
        # The human's phone; click-to-dial rings this first, then the lead.
        return os.environ.get("INVESTOR_PHONE_NUMBER", "")

    @property
    def configured(self):
        return bool(self.account_sid and self.auth_token and self.from_number)


twilio = TwilioConfig()

# How the caller identifies themselves. REQUIRED by TCPA / Ohio law — no spoofing.
CALLER_NAME = os.environ.get("CALLER_NAME", "[Your Name]")
COMPANY_NAME = os.environ.get("COMPANY_NAME", "[Your Company]")
CALLBACK_NUMBER = os.environ.get("CALLBACK_NUMBER", os.environ.get("TWILIO_FROM_NUMBER", "[Your Callback Number]"))
