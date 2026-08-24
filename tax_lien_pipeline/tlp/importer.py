"""Import tax-delinquent leads from a CSV export and normalize them.

Montgomery County, OH publishes delinquent-tax data through the Treasurer and
property/owner data through the Auditor. Field names vary by export, so this
importer maps a set of common header aliases to our schema. Point it at a CSV
you exported (or downloaded) and it will normalize, score, and store the rows.

A live scraper for the county portals is intentionally NOT included -- their
pages and terms change, and public-record scraping should respect each site's
terms of use. Export to CSV (or wire an authorized data feed) and import here.
"""
import csv

from . import db

# Map our field -> list of accepted CSV header names (lowercased).
FIELD_ALIASES = {
    "parcel_id": ["parcel_id", "parcel", "parcel number", "parcelid", "parcel_no"],
    "situs_address": ["situs_address", "situs", "property address", "address",
                      "property_address"],
    "city": ["city", "situs city", "property city"],
    "state": ["state", "situs state"],
    "zip": ["zip", "zip code", "zipcode", "situs zip", "postal"],
    "owner_name": ["owner_name", "owner", "owner name", "taxpayer",
                   "taxpayer name"],
    "owner_mailing_address": ["owner_mailing_address", "mailing address",
                              "mailing_address", "owner address", "mail address"],
    "years_delinquent": ["years_delinquent", "years delinquent", "delinquent years",
                         "years"],
    "amount_owed": ["amount_owed", "amount", "total due", "delinquent amount",
                    "balance", "total_due", "amount due"],
    "assessed_value": ["assessed_value", "assessed", "market value", "appraised",
                       "value", "total value"],
    "owner_occupied": ["owner_occupied", "homestead", "owner occupied"],
    "mortgage_recorded": ["mortgage_recorded", "mortgage", "has mortgage"],
    "foreclosure_status": ["foreclosure_status", "foreclosure", "foreclosure status"],
    "phone": ["phone", "phone number", "telephone", "owner phone", "contact phone"],
    "email": ["email", "email address", "owner email"],
}

# Montgomery County, OH Treasurer "Delinquent File" native column names
# (see data\delq file layout.pdf). The delinquent file itself has no owner
# name / mailing / phone -- enrich those from the Taxroll file + skip-trace.
MONTGOMERY_ALIASES = {
    "parcel_id": ["parcelid"],
    "situs_address": ["parcellocation"],
    "amount_owed": ["netdelq"],              # net delinquent balance
}
# Montgomery taxable values are 35% of market; divide to estimate market value.
TAXABLE_ASSESSMENT_RATIO = 0.35

BOOL_FIELDS = {"owner_occupied", "mortgage_recorded"}
NUM_FIELDS = {"years_delinquent", "amount_owed", "assessed_value"}


def _to_float(value):
    if value is None:
        return None
    s = str(value).strip().replace("$", "").replace(",", "")
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_bool(value):
    if value is None:
        return 0
    return 1 if str(value).strip().lower() in ("1", "y", "yes", "true", "t") else 0


def _build_header_map(headers):
    """Map actual CSV headers to our field names using the alias tables.

    Generic aliases win; Montgomery-native names fill any field still unmapped,
    so a raw county Delinquent File imports without renaming its columns.
    """
    lowered = {h.lower().strip(): h for h in headers}
    mapping = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                mapping[field] = lowered[alias]
                break
    for field, aliases in MONTGOMERY_ALIASES.items():
        if field in mapping:
            continue
        for alias in aliases:
            if alias in lowered:
                mapping[field] = lowered[alias]
                break
    return mapping


def _is_montgomery(headers):
    lowered = {h.lower().strip() for h in headers}
    return "parcelid" in lowered and ("netdelq" in lowered or "taxabletotal" in lowered)


def _apply_montgomery(lead, row, lowered_row):
    """Derive fields specific to the county Delinquent File format."""
    # Market value estimate from 35% taxable total.
    taxable_total = _to_float(lowered_row.get("taxabletotal"))
    if taxable_total and not lead.get("assessed_value"):
        lead["assessed_value"] = round(taxable_total / TAXABLE_ASSESSMENT_RATIO, 2)
    # Homestead reduction present => owner-occupied.
    hmsd = _to_float(lowered_row.get("hlf1hmsd")) or _to_float(lowered_row.get("hlf1hmrb"))
    if hmsd and hmsd > 0:
        lead["owner_occupied"] = 1
    # Parcel class: keep only residential-ish for outreach context (note only).
    cls = (lowered_row.get("class") or "").strip().upper()
    if cls:
        lead["_class"] = cls
    return lead


def _sniff_reader(fh):
    """Return a csv.DictReader with a sniffed delimiter (comma/pipe/tab)."""
    sample = fh.read(4096)
    fh.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",|\t")
    except csv.Error:
        dialect = csv.excel  # default comma
    return csv.DictReader(fh, dialect=dialect)


def priority_score(lead):
    """Rank leads by how attractive + actionable they are.

    Higher = better: meaningful equity, a reachable owner, and enough
    delinquency to motivate a sale -- but not so far into foreclosure that
    it's already gone.
    """
    amount = lead.get("amount_owed") or 0
    value = lead.get("assessed_value") or 0
    equity = (value - amount) if value else 0
    score = 0.0
    # Equity is the core of the deal.
    if equity > 0:
        score += min(equity / 1000.0, 100)          # up to 100 pts
    # Some delinquency motivates; cap so ancient debt doesn't dominate.
    score += min((lead.get("years_delinquent") or 0) * 5, 20)
    # Reachability matters -- a phone we can (later) scrub beats mail-only.
    if lead.get("phone"):
        score += 15
    # Absentee owners tend to be easier sellers than owner-occupants.
    if not lead.get("owner_occupied"):
        score += 10
    # Already-completed foreclosure = the opportunity is gone.
    if (lead.get("foreclosure_status") or "").lower() in ("completed", "sold"):
        score -= 50
    return round(score, 2)


def normalize_row(row, header_map, source):
    lead = {"source": source, "date_pulled": db.now()}
    for field, header in header_map.items():
        raw = row.get(header)
        if field in NUM_FIELDS:
            lead[field] = _to_float(raw)
        elif field in BOOL_FIELDS:
            lead[field] = _to_bool(raw)
        else:
            lead[field] = (raw or "").strip() if isinstance(raw, str) else raw
    # Store phones normalized (E.164-ish) so suppression + reverse lookups
    # from the inbound webhook match reliably.
    if lead.get("phone"):
        lead["phone"] = db.normalize_phone(lead["phone"])
    value = lead.get("assessed_value")
    amount = lead.get("amount_owed")
    if value is not None and amount is not None:
        lead["equity_estimate"] = round(value - amount, 2)
    return lead


def import_csv(conn, path, source="Montgomery County CSV"):
    """Import a CSV file. Returns (imported, skipped, warnings)."""
    imported, skipped, warnings = 0, 0, []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = _sniff_reader(fh)
        headers = reader.fieldnames or []
        header_map = _build_header_map(headers)
        montgomery = _is_montgomery(headers)
        if montgomery:
            source = "Montgomery County Delinquent File"
        if "parcel_id" not in header_map:
            warnings.append(
                "No 'parcel_id' column found; using situs_address as the key. "
                "Provide a parcel/parcel number column for reliable de-duping."
            )
        for row in reader:
            lead = normalize_row(row, header_map, source)
            if montgomery:
                lowered_row = {(k or "").lower().strip(): v for k, v in row.items()}
                _apply_montgomery(lead, row, lowered_row)
                # recompute equity now that value may have been derived
                if lead.get("assessed_value") is not None and lead.get("amount_owed") is not None:
                    lead["equity_estimate"] = round(lead["assessed_value"] - lead["amount_owed"], 2)
            lead.pop("_class", None)  # not a stored column
            if not lead.get("parcel_id"):
                # Fall back to address as a stable-ish key.
                lead["parcel_id"] = lead.get("situs_address") or None
            if not lead.get("parcel_id"):
                skipped += 1
                continue
            lead_id = db.upsert_lead(conn, lead)
            # Score from the MERGED stored row, not the (possibly partial)
            # incoming row -- an enrichment import must not wipe the score.
            merged = dict(db.get_lead(conn, lead_id))
            db.update_lead(conn, lead_id, priority_score=priority_score(merged))
            imported += 1
    conn.commit()
    return imported, skipped, warnings
