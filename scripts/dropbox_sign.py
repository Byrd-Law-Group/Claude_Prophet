#!/usr/bin/env python3
"""Send a document for e-signature via Dropbox Sign (formerly HelloSign), and
check/download the result once signed.

Clio's own API has no e-signature endpoint at all — its "Send for Signature"
button is a UI-only feature backed by Dropbox Sign under the hood, but that
integration isn't exposed for third parties to call. This script talks to
Dropbox Sign directly, using a *separate* Dropbox Sign account/API key of the
firm's own — it does not use, and cannot use, whatever account Clio's UI
button is wired to internally.

Requires a Dropbox Sign account with API access (developers.hellosign.com —
the free tier caps at 3 signature requests/month; production volume needs a
paid API plan) and its API key set as DROPBOX_SIGN_API_KEY, either already in
the environment or in telegram_bot/.env.

Verified 2026-09-08 against a live account: `send` and `status` both work as
written (a --test-mode send returned a real signature_request_id and correct
awaiting_signature state). `download` has not been exercised end-to-end since
that requires an actually-completed signature request — if it errors, check
the response against https://developers.hellosign.com/api/reference/.

Usage
-----
Send a document for signature:

    python3 scripts/dropbox_sign.py send --file ./hipaa_auth.pdf \
        --signer "Jane Doe:jane@example.com" \
        --title "HIPAA Authorization - Smith Matter" \
        --subject "Please sign: HIPAA Authorization" \
        --message "Please review and sign the attached authorization." \
        --test-mode

Check status:

    python3 scripts/dropbox_sign.py status --request-id <signature_request_id>

Download the final executed copy once every signer shows "signed":

    python3 scripts/dropbox_sign.py download --request-id <signature_request_id> \
        --out ./hipaa_auth_signed.pdf
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
import uuid

API_BASE = "https://api.hellosign.com/v3"


def _load_dotenv_fallback():
    """Mirror telegram_bot's own loadEnvFile fallback: if DROPBOX_SIGN_API_KEY
    isn't already in the environment, try telegram_bot/.env before giving up."""
    if os.environ.get("DROPBOX_SIGN_API_KEY"):
        return
    env_path = os.path.join(os.path.dirname(__file__), "..", "telegram_bot", ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "DROPBOX_SIGN_API_KEY" and value.strip():
                os.environ["DROPBOX_SIGN_API_KEY"] = value.strip().strip('"').strip("'")
                return


def _api_key():
    _load_dotenv_fallback()
    key = os.environ.get("DROPBOX_SIGN_API_KEY")
    if not key:
        sys.exit(
            "ERROR: DROPBOX_SIGN_API_KEY is not set. Get one from your firm's "
            "Dropbox Sign account at https://app.hellosign.com/home/myAccount#api "
            "(API dashboard), then set it in telegram_bot/.env or the environment."
        )
    return key


def _auth_header():
    token = base64.b64encode(f"{_api_key()}:".encode()).decode()
    return f"Basic {token}"


def _encode_multipart(fields, file_field, file_path):
    """Hand-rolled multipart/form-data body (no external deps, stdlib only,
    matching this repo's existing convention in scripts/clio's upload script)."""
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields:
        if value is None:
            continue
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    if file_path:
        filename = os.path.basename(file_path)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with open(file_path, "rb") as fh:
            file_bytes = fh.read()
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
            + file_bytes
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def _request(method, path, body=None, content_type=None):
    req = urllib.request.Request(f"{API_BASE}{path}", data=body, method=method)
    req.add_header("Authorization", _auth_header())
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        sys.exit(
            f"ERROR: Dropbox Sign {method} {path} -> HTTP {e.code}\n{detail}\n"
            "send/status are verified working as of 2026-09-08; if this is a "
            "download failure or something changed upstream, check "
            "https://developers.hellosign.com/api/reference/"
        )


def parse_signer(spec):
    """Parse 'Name:email@example.com' into (name, email)."""
    if ":" not in spec:
        sys.exit(f"ERROR: --signer must be 'Name:email@example.com', got: {spec}")
    name, _, email = spec.partition(":")
    if not name.strip() or not email.strip():
        sys.exit(f"ERROR: --signer must be 'Name:email@example.com', got: {spec}")
    return name.strip(), email.strip()


def send(args):
    if not os.path.isfile(args.file):
        sys.exit(f"ERROR: file not found: {args.file}")

    fields = [
        ("title", args.title),
        ("subject", args.subject),
        ("message", args.message),
        ("test_mode", "1" if args.test_mode else "0"),
    ]
    for i, spec in enumerate(args.signer):
        name, email = parse_signer(spec)
        fields.append((f"signers[{i}][name]", name))
        fields.append((f"signers[{i}][email_address]", email))
        fields.append((f"signers[{i}][order]", str(i)))

    body, content_type = _encode_multipart(fields, "file[0]", args.file)
    result = _request("POST", "/signature_request/send", body=body, content_type=content_type)

    sig_req = result.get("signature_request", {})
    print(f"OK: sent (test_mode={bool(args.test_mode)})")
    print(f"signature_request_id: {sig_req.get('signature_request_id')}")
    for sig in sig_req.get("signatures", []):
        print(f"  signer: {sig.get('signer_email_address')} -> {sig.get('status_code')}")
    print(json.dumps(result, indent=2))


def status(args):
    result = _request("GET", f"/signature_request/{args.request_id}")
    sig_req = result.get("signature_request", {})
    print(f"signature_request_id: {sig_req.get('signature_request_id')}")
    print(f"is_complete: {sig_req.get('is_complete')}")
    for sig in sig_req.get("signatures", []):
        print(f"  signer: {sig.get('signer_email_address')} -> {sig.get('status_code')}")
    print(json.dumps(result, indent=2))


def download(args):
    file_type = args.file_type
    req = urllib.request.Request(
        f"{API_BASE}/signature_request/files/{args.request_id}?file_type={file_type}",
        method="GET",
    )
    req.add_header("Authorization", _auth_header())
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        sys.exit(f"ERROR: download failed -> HTTP {e.code}\n{detail}")
    with open(args.out, "wb") as fh:
        fh.write(data)
    print(f"OK: saved final document to {args.out} ({len(data)} bytes)")
    print(
        "Next: upload this file to the matter in Clio via "
        "skills/clio/scripts/upload_document.py so the executed copy is on file."
    )


def main():
    p = argparse.ArgumentParser(description="Send/track/download Dropbox Sign signature requests.")
    sub = p.add_subparsers(dest="command", required=True)

    p_send = sub.add_parser("send", help="Send a document for signature.")
    p_send.add_argument("--file", required=True, help="Local path to the PDF/document to send.")
    p_send.add_argument("--signer", action="append", required=True,
                         help="'Name:email@example.com'. Repeat for multiple signers "
                              "(signing order follows the order given).")
    p_send.add_argument("--title", required=True, help="Internal title for the signature request.")
    p_send.add_argument("--subject", required=True, help="Email subject line sent to signers.")
    p_send.add_argument("--message", default="", help="Email body message sent to signers.")
    p_send.add_argument("--test-mode", action="store_true",
                         help="Send in Dropbox Sign test mode (no real signature, doesn't count "
                              "against the account's paid quota). Use this for the first live "
                              "test of this script.")
    p_send.set_defaults(func=send)

    p_status = sub.add_parser("status", help="Check a signature request's status.")
    p_status.add_argument("--request-id", required=True)
    p_status.set_defaults(func=status)

    p_download = sub.add_parser("download", help="Download the final executed document.")
    p_download.add_argument("--request-id", required=True)
    p_download.add_argument("--out", required=True, help="Local path to save the file to.")
    p_download.add_argument("--file-type", default="pdf", choices=["pdf", "zip"])
    p_download.set_defaults(func=download)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
