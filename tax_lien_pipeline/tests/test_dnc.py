"""Tests for the DNC vendor scrub (The Blacklist Alliance integration).

Nothing here touches the network: `urllib.request.urlopen` is patched. The
priority is the fail-safe contract -- a missing key, an HTTP error, a network
exception, or an unrecognized payload must all resolve to 'unknown' so the
compliance gate keeps the number mail_only. A false 'clear' is the dangerous
failure; these tests exist to make it impossible to introduce one silently.

Run from tax_lien_pipeline/:  python3 -m unittest discover -s tests
"""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tlp import compliance, config, db, dnc  # noqa: E402


class _FakeResp:
    """Minimal stand-in for the urlopen context-manager response."""

    def __init__(self, body, status=200):
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status

    def getcode(self):
        return self.status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen_returning(body, status=200):
    return lambda *a, **k: _FakeResp(body, status)


class ClassifyTest(unittest.TestCase):
    """Pure payload -> verdict mapping; no key or network involved."""

    def test_good_is_clear(self):
        self.assertEqual(dnc.classify({"status": "success", "results": "good"}), "clear")

    def test_bad_is_listed(self):
        self.assertEqual(dnc.classify({"status": "success", "results": "bad"}), "listed")

    def test_status_success_is_not_read_as_verdict(self):
        # `status: success` means the API call worked, not that the number is
        # clean. With no recognizable `results`, that must be 'unknown'.
        self.assertEqual(dnc.classify({"status": "success"}), "unknown")

    def test_litigator_flag_forces_listed_even_if_results_good(self):
        self.assertEqual(
            dnc.classify({"results": "good", "litigator": True}), "listed"
        )

    def test_dnc_flag_truthy_string_forces_listed(self):
        self.assertEqual(dnc.classify({"results": "good", "dnc": "yes"}), "listed")

    def test_unrecognized_verdict_is_unknown(self):
        self.assertEqual(dnc.classify({"results": "maybe"}), "unknown")

    def test_non_dict_is_unknown(self):
        self.assertEqual(dnc.classify("good"), "unknown")
        self.assertEqual(dnc.classify(None), "unknown")


class CheckTest(unittest.TestCase):
    def test_no_api_key_returns_unknown_without_calling_network(self):
        with mock.patch.object(config, "BLACKLIST_API_KEY", ""), \
             mock.patch("tlp.dnc.urllib.request.urlopen") as urlopen:
            self.assertEqual(dnc.check("+19375550142"), "unknown")
            urlopen.assert_not_called()

    def test_empty_phone_returns_unknown(self):
        with mock.patch.object(config, "BLACKLIST_API_KEY", "k"):
            self.assertEqual(dnc.check(""), "unknown")

    def test_clear_number(self):
        body = json.dumps({"status": "success", "code": 200, "results": "good"})
        with mock.patch.object(config, "BLACKLIST_API_KEY", "k"), \
             mock.patch("tlp.dnc.urllib.request.urlopen", _urlopen_returning(body)):
            self.assertEqual(dnc.check("+19375550142"), "clear")

    def test_listed_number(self):
        body = json.dumps({"status": "success", "code": 200, "results": "bad"})
        with mock.patch.object(config, "BLACKLIST_API_KEY", "k"), \
             mock.patch("tlp.dnc.urllib.request.urlopen", _urlopen_returning(body)):
            self.assertEqual(dnc.check("+19375550142"), "listed")

    def test_http_error_status_is_unknown(self):
        with mock.patch.object(config, "BLACKLIST_API_KEY", "k"), \
             mock.patch("tlp.dnc.urllib.request.urlopen",
                        _urlopen_returning("{}", status=500)):
            self.assertEqual(dnc.check("+19375550142"), "unknown")

    def test_network_exception_is_unknown(self):
        def boom(*a, **k):
            raise OSError("connection reset")
        with mock.patch.object(config, "BLACKLIST_API_KEY", "k"), \
             mock.patch("tlp.dnc.urllib.request.urlopen", boom):
            self.assertEqual(dnc.check("+19375550142"), "unknown")

    def test_malformed_json_is_unknown(self):
        with mock.patch.object(config, "BLACKLIST_API_KEY", "k"), \
             mock.patch("tlp.dnc.urllib.request.urlopen",
                        _urlopen_returning("not json")):
            self.assertEqual(dnc.check("+19375550142"), "unknown")


class ScrubIntegrationTest(unittest.TestCase):
    """scrub_number / scrub_lead behavior with the vendor wired in."""

    def setUp(self):
        self.conn = db.init_db(":memory:")

    def tearDown(self):
        self.conn.close()

    def _lead(self, phone="+19375550142", **overrides):
        lead = {"parcel_id": "P-1", "owner_name": "SMITH, JOHN",
                "phone": phone, "amount_owed": 6420.0, "assessed_value": 78500.0,
                "source": "test", "date_pulled": db.now()}
        lead_id = db.upsert_lead(self.conn, lead)
        if overrides:
            db.update_lead(self.conn, lead_id, **overrides)
        self.conn.commit()
        return db.get_lead(self.conn, lead_id)

    def test_suppressed_number_short_circuits_before_vendor(self):
        lead = self._lead()
        db.suppress(self.conn, lead["phone"], reason="opt_out")
        with mock.patch("tlp.dnc.check") as vendor:
            self.assertEqual(compliance.scrub_number(self.conn, lead["phone"]), "listed")
            vendor.assert_not_called()  # no billable lookup for a known opt-out

    def test_vendor_clear_makes_lead_call_text(self):
        lead = self._lead()
        with mock.patch("tlp.dnc.check", return_value="clear"):
            self.assertEqual(compliance.scrub_lead(self.conn, lead), "call_text")

    def test_vendor_listed_makes_lead_mail_only(self):
        lead = self._lead()
        with mock.patch("tlp.dnc.check", return_value="listed"):
            self.assertEqual(compliance.scrub_lead(self.conn, lead), "mail_only")

    def test_vendor_unknown_without_consent_stays_mail_only(self):
        lead = self._lead()
        with mock.patch("tlp.dnc.check", return_value="unknown"):
            self.assertEqual(compliance.scrub_lead(self.conn, lead), "mail_only")

    def test_vendor_unknown_with_consent_is_call_text(self):
        lead = self._lead(consent_status="prior_business")
        with mock.patch("tlp.dnc.check", return_value="unknown"):
            self.assertEqual(compliance.scrub_lead(self.conn, lead), "call_text")


if __name__ == "__main__":
    unittest.main()
