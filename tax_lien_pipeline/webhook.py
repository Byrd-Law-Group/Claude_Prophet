#!/usr/bin/env python3
"""Inbound-SMS webhook (stdlib http.server) — auto-honors STOP / replies.

Point your Twilio number's "A MESSAGE COMES IN" webhook at:
    https://<your-host>/sms   (HTTP POST)

Any inbound message whose text is a recognized opt-out keyword (STOP, STOPALL,
UNSUBSCRIBE, CANCEL, END, QUIT) permanently suppresses that number and marks
the matching lead opted out. Every other inbound message is logged against the
lead so you see replies. This keeps opt-out honoring automatic and provable.

Run:  python3 webhook.py --port 8080
Expose it with your own TLS/reverse proxy or a tunnel; Twilio must reach it.
"""
import argparse
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from tlp import db, compliance

OPT_OUT_KEYWORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}


class Handler(BaseHTTPRequestHandler):
    def _twiml(self, message=None):
        body = "<Response>%s</Response>" % (
            "<Message>%s</Message>" % message if message else "")
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self):
        if self.path.split("?")[0] != "/sms":
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode() if length else ""
        params = urllib.parse.parse_qs(raw)
        from_number = (params.get("From", [""])[0]).strip()
        text = (params.get("Body", [""])[0]).strip()

        conn = db.init_db()
        try:
            if text.lower() in OPT_OUT_KEYWORDS:
                compliance.record_opt_out(conn, from_number)
                self.log_message("Opt-out honored for %s", from_number)
                self._twiml("You've been removed and won't be contacted again.")
                return
            # Log any other reply against the matching lead.
            norm = db.normalize_phone(from_number)
            row = conn.execute(
                "SELECT id FROM leads WHERE phone = ? OR phone = ?",
                (from_number, norm)).fetchone()
            if row:
                db.add_touch(conn, row["id"], "sms", "inbound", "reply",
                             message_body=text)
                conn.commit()
            self.log_message("Inbound reply from %s: %r", from_number, text)
            self._twiml()
        finally:
            conn.close()

    def log_message(self, fmt, *args):  # quieter, prefixed logging
        print("[webhook] " + (fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    srv = HTTPServer(("0.0.0.0", args.port), Handler)
    print("Inbound SMS webhook listening on :%d/sms  (Ctrl-C to stop)" % args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
