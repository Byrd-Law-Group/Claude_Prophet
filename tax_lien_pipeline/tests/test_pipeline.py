"""Regression tests for the tax-lien outreach pipeline.

The point of this suite is the compliance gate. Every outbound touch flows
through `compliance.can_contact`, and the README promises there are "no code
overrides for opt-outs or calling hours." These tests pin that promise down so
a future change can't silently open an unlawful contact path. The importer and
db tests cover the data-integrity invariants those compliance decisions rely on
(phone normalization must match between suppression and outreach; an enrichment
import must merge, not clobber).

Stdlib only. Run from the tax_lien_pipeline directory:
    python3 -m unittest discover -s tests
    python3 -m pytest tests            # also works if pytest is installed
"""
import datetime
import os
import sys
import tempfile
import unittest

# Make `import tlp` work no matter the cwd the runner uses.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tlp import compliance, config, db, importer  # noqa: E402


# A UTC instant that is inside 8am-9pm ET under both EST (UTC-5) and EDT (UTC-4),
# and one that is outside under both, so the tests don't depend on DST or on
# whether tzdata is installed (compliance falls back to a fixed UTC-5).
INSIDE_HOURS = datetime.datetime(2026, 6, 1, 18, 0, tzinfo=datetime.timezone.utc)   # ~13-14 ET
OUTSIDE_HOURS = datetime.datetime(2026, 6, 1, 6, 0, tzinfo=datetime.timezone.utc)   # ~01-02 ET


def make_lead(conn, **overrides):
    """Insert a lead and return it as a fully-eligible, approved sqlite Row.

    Individual tests override single fields to prove that flipping any one of
    them closes the gate.
    """
    lead = {
        "parcel_id": overrides.pop("parcel_id", "P-1"),
        "owner_name": "SMITH, JOHN",
        "situs_address": "412 Huffman Ave",
        "phone": overrides.pop("phone", "+19375550142"),
        "amount_owed": 6420.0,
        "assessed_value": 78500.0,
        "source": "test",
        "date_pulled": db.now(),
    }
    lead_id = db.upsert_lead(conn, lead)
    fields = {
        "channel_eligibility": "call_text",
        "approved": 1,
        "status": "scrubbed",
    }
    fields.update(overrides)
    db.update_lead(conn, lead_id, **fields)
    conn.commit()
    return db.get_lead(conn, lead_id)


class ComplianceGateTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.init_db(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_fully_eligible_lead_passes(self):
        lead = make_lead(self.conn)
        ok, reason = compliance.can_contact(self.conn, lead, "sms", when=INSIDE_HOURS)
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "ok")

    def test_opt_out_blocks(self):
        lead = make_lead(self.conn, opt_out=1)
        ok, reason = compliance.can_contact(self.conn, lead, "sms", when=INSIDE_HOURS)
        self.assertFalse(ok)
        self.assertEqual(reason, "opted_out_or_suppressed")

    def test_suppressed_phone_blocks_even_if_lead_not_flagged(self):
        lead = make_lead(self.conn)
        db.suppress(self.conn, lead["phone"], reason="opt_out")
        ok, reason = compliance.can_contact(self.conn, lead, "sms", when=INSIDE_HOURS)
        self.assertFalse(ok)
        self.assertEqual(reason, "opted_out_or_suppressed")

    def test_no_phone_blocks(self):
        lead = make_lead(self.conn, phone=None)
        ok, reason = compliance.can_contact(self.conn, lead, "sms", when=INSIDE_HOURS)
        self.assertFalse(ok)
        self.assertEqual(reason, "no_phone")

    def test_non_contact_eligibility_blocks(self):
        for elig in ("do_not_contact", "mail_only", "unscrubbed", None):
            lead = make_lead(self.conn, parcel_id="P-%s" % elig,
                             channel_eligibility=elig)
            ok, reason = compliance.can_contact(self.conn, lead, "sms", when=INSIDE_HOURS)
            self.assertFalse(ok, elig)
            self.assertEqual(reason, "not_contact_eligible:%s" % elig)

    def test_not_approved_blocks(self):
        lead = make_lead(self.conn, approved=0)
        ok, reason = compliance.can_contact(self.conn, lead, "sms", when=INSIDE_HOURS)
        self.assertFalse(ok)
        self.assertEqual(reason, "not_human_approved")

    def test_attempt_cap_blocks(self):
        lead = make_lead(self.conn)
        for _ in range(config.MAX_ATTEMPTS_PER_LEAD):
            db.add_touch(self.conn, lead["id"], channel="call",
                         direction="outbound", outcome="no_answer")
        self.conn.commit()
        ok, reason = compliance.can_contact(self.conn, lead, "call", when=INSIDE_HOURS)
        self.assertFalse(ok)
        self.assertEqual(reason, "attempt_cap_reached")

    def test_queued_touches_do_not_count_toward_cap(self):
        lead = make_lead(self.conn)
        for _ in range(config.MAX_ATTEMPTS_PER_LEAD + 2):
            db.add_touch(self.conn, lead["id"], channel="sms",
                         direction="outbound", outcome="queued")
        self.conn.commit()
        self.assertEqual(db.count_attempts(self.conn, lead["id"]), 0)
        ok, reason = compliance.can_contact(self.conn, lead, "sms", when=INSIDE_HOURS)
        self.assertTrue(ok, reason)

    def test_outside_calling_hours_blocks(self):
        lead = make_lead(self.conn)
        ok, reason = compliance.can_contact(self.conn, lead, "sms", when=OUTSIDE_HOURS)
        self.assertFalse(ok)
        self.assertEqual(reason, "outside_calling_hours")


class CallingHoursTest(unittest.TestCase):
    def test_inside_window(self):
        self.assertTrue(compliance.within_calling_hours(INSIDE_HOURS))

    def test_outside_window(self):
        self.assertFalse(compliance.within_calling_hours(OUTSIDE_HOURS))

    def test_naive_datetime_treated_as_utc(self):
        naive = INSIDE_HOURS.replace(tzinfo=None)
        self.assertTrue(compliance.within_calling_hours(naive))


class ScrubLeadTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.init_db(":memory:")

    def tearDown(self):
        self.conn.close()

    def _scrub(self, **overrides):
        lead = make_lead(self.conn, channel_eligibility="unscrubbed",
                         approved=0, **overrides)
        return compliance.scrub_lead(self.conn, lead)

    def test_opt_out_lead_is_do_not_contact(self):
        self.assertEqual(self._scrub(opt_out=1), "do_not_contact")

    def test_no_phone_is_mail_only(self):
        self.assertEqual(self._scrub(phone=None), "mail_only")

    def test_suppressed_number_is_mail_only(self):
        lead = make_lead(self.conn, channel_eligibility="unscrubbed", approved=0)
        db.suppress(self.conn, lead["phone"], reason="dnc_registry")
        self.assertEqual(compliance.scrub_lead(self.conn, lead), "mail_only")

    def test_unknown_dnc_without_consent_is_mail_only(self):
        # This is the crucial default: no live DNC check + no consent => no calls.
        self.assertEqual(self._scrub(), "mail_only")

    def test_consent_unlocks_call_text(self):
        self.assertEqual(self._scrub(consent_status="prior_business"), "call_text")
        self.assertEqual(
            self._scrub(parcel_id="P-2", consent_status="express_written"),
            "call_text",
        )


class OptOutTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.init_db(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_record_opt_out_suppresses_and_flags_lead(self):
        lead = make_lead(self.conn)
        compliance.record_opt_out(self.conn, lead["phone"], lead_id=lead["id"])
        refreshed = db.get_lead(self.conn, lead["id"])
        self.assertEqual(refreshed["opt_out"], 1)
        self.assertEqual(refreshed["channel_eligibility"], "do_not_contact")
        self.assertEqual(refreshed["status"], "opt_out")
        self.assertTrue(db.is_suppressed(self.conn, lead["phone"]))
        # And the gate is now closed.
        ok, _ = compliance.can_contact(self.conn, refreshed, "sms", when=INSIDE_HOURS)
        self.assertFalse(ok)

    def test_record_opt_out_finds_lead_by_phone(self):
        lead = make_lead(self.conn)
        # No lead_id passed -> it should reverse-look-up by phone.
        compliance.record_opt_out(self.conn, lead["phone"])
        refreshed = db.get_lead(self.conn, lead["id"])
        self.assertEqual(refreshed["opt_out"], 1)


class NormalizePhoneTest(unittest.TestCase):
    def test_ten_digit_gets_country_code(self):
        self.assertEqual(db.normalize_phone("937-555-0142"), "+19375550142")

    def test_already_e164(self):
        self.assertEqual(db.normalize_phone("+1 (937) 555-0142"), "+19375550142")

    def test_empty(self):
        self.assertEqual(db.normalize_phone(""), "")
        self.assertEqual(db.normalize_phone(None), "")

    def test_suppression_matches_regardless_of_formatting(self):
        conn = db.init_db(":memory:")
        db.suppress(conn, "(937) 555-0142", reason="manual")
        self.assertTrue(db.is_suppressed(conn, "9375550142"))
        self.assertTrue(db.is_suppressed(conn, "+19375550142"))
        conn.close()


class PriorityScoreTest(unittest.TestCase):
    def test_equity_drives_score(self):
        low = importer.priority_score({"amount_owed": 5000, "assessed_value": 10000})
        high = importer.priority_score({"amount_owed": 5000, "assessed_value": 90000})
        self.assertGreater(high, low)

    def test_phone_adds_reachability_points(self):
        base = {"amount_owed": 5000, "assessed_value": 50000}
        with_phone = dict(base, phone="+19375550142")
        self.assertEqual(
            importer.priority_score(with_phone) - importer.priority_score(base), 15
        )

    def test_completed_foreclosure_is_penalized(self):
        base = {"amount_owed": 5000, "assessed_value": 50000}
        gone = dict(base, foreclosure_status="completed")
        self.assertLess(
            importer.priority_score(gone), importer.priority_score(base)
        )

    def test_absentee_owner_scores_above_owner_occupied(self):
        base = {"amount_owed": 5000, "assessed_value": 50000}
        occupied = dict(base, owner_occupied=1)
        self.assertGreater(
            importer.priority_score(base), importer.priority_score(occupied)
        )


class ImportCsvTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.init_db(":memory:")
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        self.conn.close()

    def _write(self, name, text):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_generic_import_normalizes_phone_and_maps_aliases(self):
        path = self._write("g.csv",
            "parcel,owner,property address,amount due,value,phone\n"
            "R-1,\"DOE, JANE\",1 Main St,\"$3,200\",60000,937-555-0100\n")
        imported, skipped, _ = importer.import_csv(self.conn, path, source="unit")
        self.assertEqual((imported, skipped), (1, 0))
        row = db.list_leads(self.conn)[0]
        self.assertEqual(row["parcel_id"], "R-1")
        self.assertEqual(row["amount_owed"], 3200.0)
        self.assertEqual(row["phone"], "+19375550100")
        self.assertEqual(row["equity_estimate"], 56800.0)

    def test_enrichment_import_merges_without_clobbering(self):
        base = self._write("base.csv",
            "parcel,amount due,value\nR-9,1000,50000\n")
        importer.import_csv(self.conn, base, source="treasurer")
        before = db.list_leads(self.conn)[0]
        self.assertIsNone(before["phone"])
        score_before = before["priority_score"]

        enrich = self._write("enrich.csv",
            "parcel,owner,phone\nR-9,\"DOE, JOHN\",937-555-0199\n")
        importer.import_csv(self.conn, enrich, source="skiptrace")

        after = db.list_leads(self.conn)[0]
        self.assertEqual(after["phone"], "+19375550199")     # enriched
        self.assertEqual(after["owner_name"], "DOE, JOHN")   # enriched
        self.assertEqual(after["amount_owed"], 1000.0)       # preserved
        self.assertEqual(after["assessed_value"], 50000.0)   # preserved
        # Enrichment adds a reachable phone, so the score should not drop.
        self.assertGreaterEqual(after["priority_score"], score_before)
        self.assertEqual(len(db.list_leads(self.conn)), 1)   # merged, not duplicated

    def test_montgomery_native_format_derives_value_and_owner_occupied(self):
        path = self._write("mont.csv",
            "PARCELID,PARCELLOCATION,NETDELQ,TAXABLETOTAL,HLF1HMSD,CLASS\n"
            "R72-001,100 Elm St,\"2,000\",35000,500,R\n")
        imported, skipped, _ = importer.import_csv(self.conn, path)
        self.assertEqual((imported, skipped), (1, 0))
        row = db.list_leads(self.conn)[0]
        self.assertEqual(row["parcel_id"], "R72-001")
        self.assertEqual(row["amount_owed"], 2000.0)
        # 35000 taxable / 0.35 = 100000 estimated market value.
        self.assertEqual(row["assessed_value"], 100000.0)
        self.assertEqual(row["owner_occupied"], 1)           # homestead present
        self.assertEqual(row["source"], "Montgomery County Delinquent File")

    def test_row_without_parcel_or_address_is_skipped(self):
        path = self._write("bad.csv",
            "parcel,amount due,value\n,500,10000\n")
        imported, skipped, _ = importer.import_csv(self.conn, path)
        self.assertEqual((imported, skipped), (0, 1))


if __name__ == "__main__":
    unittest.main()
