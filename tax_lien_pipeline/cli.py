#!/usr/bin/env python3
"""Tax-lien acquisition outreach pipeline — command-line interface.

Workflow:
  1. init                      create the database
  2. import <csv>              load + normalize + score delinquent leads
  3. scrub                     DNC/suppression scrub -> set channel eligibility
  4. list [status]            review leads (ranked by priority)
  5. draft <id>               preview the call script + SMS for a lead
  6. approve <id>             human sign-off to allow sending (the gate)
  7. send-sms <id> / call <id>  send/dial (preview unless Twilio is configured)
  8. log <id> <outcome>       record what happened on a call/text
  9. optout <id|phone>        permanently suppress a contact
 10. followups                leads due for another touch

Nothing sends without: approve (human) + Twilio credentials + passing the
compliance gate. Without credentials, sends produce a preview and log a
'queued' touch so you can send manually.
"""
import argparse
import sys

from tlp import db, compliance, importer, outreach, messaging, config


def _fmt_money(v):
    return "${:,.0f}".format(v) if v else "-"


def cmd_init(args, conn):
    db.init_db()
    print("Initialized database at %s" % config.DB_PATH)


def cmd_import(args, conn):
    imported, skipped, warnings = importer.import_csv(conn, args.csv, source=args.source)
    for w in warnings:
        print("WARN: %s" % w)
    print("Imported/updated %d leads (%d skipped)." % (imported, skipped))
    print("Next: run `scrub` to set contact eligibility.")


def cmd_scrub(args, conn):
    leads = conn.execute(
        "SELECT * FROM leads WHERE status IN ('new','scrubbed')"
    ).fetchall()
    counts = {}
    for lead in leads:
        elig = compliance.scrub_lead(conn, lead)
        counts[elig] = counts.get(elig, 0) + 1
    conn.commit()
    print("Scrubbed %d leads:" % len(leads))
    for k, v in sorted(counts.items()):
        print("  %-15s %d" % (k, v))
    if counts.get("mail_only"):
        print("\nNote: 'mail_only' includes numbers with UNKNOWN DNC status. "
              "Set BLACKLIST_API_KEY so the DNC vendor can clear them (or add "
              "consent) to make them call/text eligible.")


def cmd_list(args, conn):
    leads = db.list_leads(conn, status=args.status)
    print("%-4s %-24s %-18s %8s %8s %6s %-11s %-8s %s" % (
        "ID", "Owner", "Address", "Owed", "Value", "Score", "Eligible",
        "Status", "Appr"))
    print("-" * 108)
    for l in leads:
        print("%-4s %-24s %-18s %8s %8s %6s %-11s %-8s %s" % (
            l["id"], (l["owner_name"] or "")[:24], (l["situs_address"] or "")[:18],
            _fmt_money(l["amount_owed"]), _fmt_money(l["assessed_value"]),
            l["priority_score"], (l["channel_eligibility"] or "")[:11],
            (l["status"] or "")[:8], "yes" if l["approved"] else "no"))
    print("\n%d leads." % len(leads))


def cmd_show(args, conn):
    l = db.get_lead(conn, args.id)
    if not l:
        print("No lead %s" % args.id); return
    for k in l.keys():
        print("  %-22s %s" % (k, l[k]))
    touches = conn.execute(
        "SELECT ts, channel, direction, outcome, notes FROM touches "
        "WHERE lead_id = ? ORDER BY ts", (args.id,)).fetchall()
    if touches:
        print("\n  Touches:")
        for t in touches:
            print("    %s  %s/%s  %s  %s" % (
                t["ts"], t["channel"], t["direction"], t["outcome"], t["notes"] or ""))


def cmd_draft(args, conn):
    l = db.get_lead(conn, args.id)
    if not l:
        print("No lead %s" % args.id); return
    print("=" * 70)
    print("SMS DRAFT (%d chars):" % len(outreach.draft_sms(l)))
    print("-" * 70)
    print(outreach.draft_sms(l))
    print("\n" + "=" * 70)
    print(outreach.draft_call_script(l))
    ok, reason = compliance.can_contact(conn, l, "sms")
    print("=" * 70)
    print("Send-eligible right now: %s (%s)" % ("YES" if ok else "NO", reason))


def cmd_consent(args, conn):
    l = db.get_lead(conn, args.id)
    if not l:
        print("No lead %s" % args.id); return
    db.update_lead(conn, args.id, consent_status=args.basis)
    # Re-scrub so eligibility reflects the new lawful basis.
    l = db.get_lead(conn, args.id)
    elig = compliance.scrub_lead(conn, l)
    conn.commit()
    print("Lead %s consent set to '%s' -> eligibility: %s" % (args.id, args.basis, elig))


def cmd_approve(args, conn):
    l = db.get_lead(conn, args.id)
    if not l:
        print("No lead %s" % args.id); return
    db.update_lead(conn, args.id, approved=1, status="queued")
    conn.commit()
    print("Lead %s (%s) approved for outreach." % (args.id, l["owner_name"]))


def cmd_send_sms(args, conn):
    l = db.get_lead(conn, args.id)
    if not l:
        print("No lead %s" % args.id); return
    res = messaging.send_sms(conn, l, dry_run=args.dry_run)
    print(res)
    if res.detail == "preview_only":
        print("\n(Preview only — Twilio not configured or --dry-run. "
              "Message logged as 'queued' so you can send it manually.)")
        print("\nTo: %s\n%s" % (l["phone"], outreach.draft_sms(l)))


def cmd_call(args, conn):
    l = db.get_lead(conn, args.id)
    if not l:
        print("No lead %s" % args.id); return
    res = messaging.initiate_call(conn, l, dry_run=args.dry_run)
    print(res)
    if res.detail == "preview_only":
        print("\n(Preview only. Call script:)\n")
        print(outreach.draft_call_script(l))


def cmd_log(args, conn):
    l = db.get_lead(conn, args.id)
    if not l:
        print("No lead %s" % args.id); return
    outcome = args.outcome
    db.add_touch(conn, args.id, channel=args.channel, direction="outbound",
                 outcome=outcome, notes=args.notes)
    status_map = {
        "interested": "interested", "not_interested": "not_interested",
        "opt_out": "opt_out", "callback": "interested",
    }
    if outcome in status_map:
        db.update_lead(conn, args.id, status=status_map[outcome])
    if outcome == "opt_out":
        compliance.record_opt_out(conn, l["phone"], lead_id=args.id)
    conn.commit()
    print("Logged '%s' on lead %s." % (outcome, args.id))


def cmd_optout(args, conn):
    ident = args.ident
    if ident.isdigit():
        l = db.get_lead(conn, int(ident))
        if not l:
            print("No lead %s" % ident); return
        compliance.record_opt_out(conn, l["phone"], lead_id=int(ident))
        print("Lead %s opted out and suppressed." % ident)
    else:
        compliance.record_opt_out(conn, ident)
        print("Number %s suppressed (opt-out)." % ident)


def cmd_followups(args, conn):
    leads = conn.execute(
        "SELECT * FROM leads WHERE status = 'interested' AND opt_out = 0 "
        "ORDER BY priority_score DESC").fetchall()
    print("Leads due for follow-up (interested, not opted out):")
    for l in leads:
        attempts = db.count_attempts(conn, l["id"])
        print("  #%s %-22s %s  attempts=%d/%d" % (
            l["id"], (l["owner_name"] or "")[:22], l["phone"] or "-",
            attempts, config.MAX_ATTEMPTS_PER_LEAD))
    print("\n%d to follow up." % len(leads))


def cmd_stats(args, conn):
    rows = conn.execute(
        "SELECT status, COUNT(*) n FROM leads GROUP BY status").fetchall()
    print("Lead pipeline:")
    for r in rows:
        print("  %-16s %d" % (r["status"], r["n"]))
    sup = conn.execute("SELECT COUNT(*) n FROM suppression").fetchone()["n"]
    print("Suppressed numbers: %d" % sup)


def build_parser():
    p = argparse.ArgumentParser(description="Tax-lien acquisition outreach pipeline")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the database")

    sp = sub.add_parser("import", help="import a delinquent-tax CSV")
    sp.add_argument("csv")
    sp.add_argument("--source", default="Montgomery County CSV")

    sub.add_parser("scrub", help="DNC/suppression scrub + set eligibility")

    sp = sub.add_parser("list", help="list leads")
    sp.add_argument("status", nargs="?", default=None)

    sp = sub.add_parser("show", help="show one lead + its touches")
    sp.add_argument("id", type=int)

    sp = sub.add_parser("draft", help="preview SMS + call script for a lead")
    sp.add_argument("id", type=int)

    sp = sub.add_parser("consent", help="record a lawful basis to contact")
    sp.add_argument("id", type=int)
    sp.add_argument("basis", choices=["express_written", "prior_business", "none"])

    sp = sub.add_parser("approve", help="human sign-off to allow sending")
    sp.add_argument("id", type=int)

    sp = sub.add_parser("send-sms", help="send/preview an SMS")
    sp.add_argument("id", type=int)
    sp.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser("call", help="click-to-dial/preview a call")
    sp.add_argument("id", type=int)
    sp.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser("log", help="log a contact outcome")
    sp.add_argument("id", type=int)
    sp.add_argument("outcome", choices=["no_answer", "interested", "not_interested",
                                        "opt_out", "callback", "left_voicemail"])
    sp.add_argument("--channel", default="call", choices=["call", "sms"])
    sp.add_argument("--notes", default=None)

    sp = sub.add_parser("optout", help="opt out a lead id or phone number")
    sp.add_argument("ident")

    sub.add_parser("followups", help="leads due for follow-up")
    sub.add_parser("stats", help="pipeline summary")
    return p


COMMANDS = {
    "init": cmd_init, "import": cmd_import, "scrub": cmd_scrub, "list": cmd_list,
    "show": cmd_show, "draft": cmd_draft, "approve": cmd_approve,
    "consent": cmd_consent,
    "send-sms": cmd_send_sms, "call": cmd_call, "log": cmd_log,
    "optout": cmd_optout, "followups": cmd_followups, "stats": cmd_stats,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    conn = db.init_db()
    try:
        COMMANDS[args.command](args, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
