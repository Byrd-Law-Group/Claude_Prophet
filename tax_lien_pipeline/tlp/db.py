"""SQLite storage for leads, contact touches, and the suppression list.

Every lead carries a full compliance record: where it came from, DNC status,
consent status, per-channel eligibility, and opt-out state. Nothing is queued
for outreach unless that record is complete (enforced in compliance.py).
"""
import sqlite3
import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    parcel_id             TEXT UNIQUE,
    situs_address         TEXT,
    city                  TEXT,
    state                 TEXT,
    zip                   TEXT,
    owner_name            TEXT,
    owner_mailing_address TEXT,
    years_delinquent      REAL,
    amount_owed           REAL,
    assessed_value        REAL,
    owner_occupied        INTEGER DEFAULT 0,   -- 1 = homestead / owner-occupied
    mortgage_recorded     INTEGER DEFAULT 0,
    foreclosure_status    TEXT,                -- none / pending / completed
    equity_estimate       REAL,
    phone                 TEXT,
    email                 TEXT,
    source                TEXT,
    date_pulled           TEXT,
    dnc_status            TEXT DEFAULT 'unknown',   -- unknown / clear / listed
    dnc_checked_at        TEXT,
    consent_status        TEXT DEFAULT 'none',      -- none / prior_business / express_written
    channel_eligibility   TEXT DEFAULT 'unscrubbed',-- call / text / call_text / mail_only / do_not_contact / unscrubbed
    opt_out               INTEGER DEFAULT 0,
    opt_out_at            TEXT,
    priority_score        REAL DEFAULT 0,
    approved              INTEGER DEFAULT 0,        -- human sign-off to send
    status                TEXT DEFAULT 'new',       -- new/scrubbed/queued/contacted/interested/not_interested/opt_out/closed
    created_at            TEXT,
    updated_at            TEXT
);

CREATE TABLE IF NOT EXISTS touches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id      INTEGER NOT NULL,
    channel      TEXT,        -- sms / call
    direction    TEXT,        -- outbound / inbound
    ts           TEXT,
    outcome      TEXT,        -- queued/sent/no_answer/interested/not_interested/opt_out/callback/failed
    message_body TEXT,
    provider_sid TEXT,
    approved_by  TEXT,
    notes        TEXT,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS suppression (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    phone    TEXT UNIQUE,
    reason   TEXT,     -- opt_out / dnc_registry / manual
    added_at TEXT
);
"""


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def connect(db_path=None):
    conn = sqlite3.connect(db_path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert_lead(conn, lead):
    """Insert or update a lead keyed on parcel_id. Returns the row id."""
    cols = [
        "parcel_id", "situs_address", "city", "state", "zip", "owner_name",
        "owner_mailing_address", "years_delinquent", "amount_owed",
        "assessed_value", "owner_occupied", "mortgage_recorded",
        "foreclosure_status", "equity_estimate", "phone", "email", "source",
        "date_pulled",
    ]
    values = [lead.get(c) for c in cols]
    ts = now()
    existing = conn.execute(
        "SELECT id FROM leads WHERE parcel_id = ?", (lead.get("parcel_id"),)
    ).fetchone()
    if existing:
        # COALESCE-style: only overwrite a column when the incoming value is
        # non-null. This lets a second CSV (e.g. skip-traced owner/phone) enrich
        # a parcel without wiping fields it doesn't carry.
        assignments = ", ".join(f"{c} = COALESCE(?, {c})" for c in cols)
        conn.execute(
            f"UPDATE leads SET {assignments}, updated_at = ? WHERE parcel_id = ?",
            values + [ts, lead.get("parcel_id")],
        )
        return existing["id"]
    placeholders = ", ".join("?" for _ in cols)
    cur = conn.execute(
        f"INSERT INTO leads ({', '.join(cols)}, created_at, updated_at) "
        f"VALUES ({placeholders}, ?, ?)",
        values + [ts, ts],
    )
    return cur.lastrowid


def get_lead(conn, lead_id):
    return conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()


def update_lead(conn, lead_id, **fields):
    if not fields:
        return
    fields["updated_at"] = now()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE leads SET {assignments} WHERE id = ?",
        list(fields.values()) + [lead_id],
    )


def list_leads(conn, status=None, order_by="priority_score DESC, amount_owed DESC"):
    if status:
        return conn.execute(
            f"SELECT * FROM leads WHERE status = ? ORDER BY {order_by}", (status,)
        ).fetchall()
    return conn.execute(f"SELECT * FROM leads ORDER BY {order_by}").fetchall()


def add_touch(conn, lead_id, channel, direction, outcome,
              message_body=None, provider_sid=None, approved_by=None, notes=None):
    conn.execute(
        "INSERT INTO touches (lead_id, channel, direction, ts, outcome, "
        "message_body, provider_sid, approved_by, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (lead_id, channel, direction, now(), outcome, message_body,
         provider_sid, approved_by, notes),
    )


def count_attempts(conn, lead_id):
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM touches "
        "WHERE lead_id = ? AND direction = 'outbound' AND outcome != 'queued'",
        (lead_id,),
    ).fetchone()
    return row["n"]


def suppress(conn, phone, reason):
    if not phone:
        return
    conn.execute(
        "INSERT OR IGNORE INTO suppression (phone, reason, added_at) VALUES (?, ?, ?)",
        (normalize_phone(phone), reason, now()),
    )


def is_suppressed(conn, phone):
    if not phone:
        return False
    row = conn.execute(
        "SELECT 1 FROM suppression WHERE phone = ?", (normalize_phone(phone),)
    ).fetchone()
    return row is not None


def normalize_phone(phone):
    """Reduce to E.164-ish digits so comparisons are consistent."""
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits if digits else ""
