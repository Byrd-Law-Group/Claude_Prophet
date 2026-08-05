#!/usr/bin/env python3
"""Upload a file to Clio's document management, or replace an existing document
with a new version.

Clio document upload is a 3-step flow that this script handles for you:

  1. POST (new doc) or PATCH (new version) to Clio to register the file and
     receive a one-time AWS S3 ``put_url`` plus the exact ``put_headers`` that
     must accompany the upload.
  2. PUT the raw file bytes *directly to S3* using those headers. This request
     goes to Amazon, NOT through the Maton gateway, and must NOT carry the
     Maton/Clio Authorization header.
  3. PATCH the document back on Clio with ``fully_uploaded: true`` and the
     version ``uuid`` to finalize it. Until this step runs the document exists
     but has no usable content.

All Clio calls go through the Maton gateway (``https://gateway.maton.ai/clio``)
and authenticate with ``MATON_API_KEY``. The S3 PUT is unauthenticated except
for the signed URL and the returned headers.

Usage
-----
Upload a brand-new document to a matter:

    python upload_document.py --file ./demand_letter.pdf --matter 12345

Upload with an explicit display name and a folder as the parent:

    python upload_document.py --file ./records.pdf --parent-id 987 \
        --parent-type Folder --name "Medical Records - Batch 1.pdf"

Replace an existing document with a new version (edit the file contents):

    python upload_document.py --file ./demand_letter_v2.pdf --document 67890

Rename / move an existing document (metadata only, no new bytes):

    python upload_document.py --document 67890 --name "Final Demand.pdf"
    python upload_document.py --document 67890 --parent-id 555 --parent-type Folder
"""
import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

GATEWAY = "https://gateway.maton.ai/clio/api/v4"
UPLOAD_FIELDS = "id,name,latest_document_version{uuid,put_url,put_headers}"


def _api_key():
    key = os.environ.get("MATON_API_KEY")
    if not key:
        sys.exit("ERROR: MATON_API_KEY is not set. See the clio skill for setup.")
    return key


def _connection_header(req):
    conn = os.environ.get("MATON_CONNECTION")
    if conn:
        req.add_header("Maton-Connection", conn)


def clio_request(method, path, body=None, fields=None):
    """Call the Clio API through the Maton gateway. Returns parsed JSON."""
    url = f"{GATEWAY}{path}"
    if fields:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}fields={fields}"
    data = json.dumps({"data": body}).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_api_key()}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    _connection_header(req)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        sys.exit(f"ERROR: Clio {method} {path} -> HTTP {e.code}\n{detail}")


def s3_put(put_url, put_headers, file_bytes):
    """PUT raw bytes straight to S3. No Maton/Clio auth header here."""
    req = urllib.request.Request(put_url, data=file_bytes, method="PUT")
    # put_headers is a list of {"name": ..., "value": ...} objects.
    for h in put_headers or []:
        req.add_header(h["name"], h["value"])
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        sys.exit(f"ERROR: S3 upload PUT failed -> HTTP {e.code}\n{detail}")


def register(args, file_name):
    """Step 1: create the doc (POST) or a new version (PATCH); get the put_url."""
    body = {"name": file_name}
    if args.document:
        # New version of an existing document.
        resp = clio_request("PATCH", f"/documents/{args.document}.json",
                             body=body, fields=UPLOAD_FIELDS)
    else:
        # Brand-new document. parent is the matter (or a folder within it).
        parent_id = args.parent_id or args.matter
        if not parent_id:
            sys.exit("ERROR: provide --matter (or --parent-id) for a new document.")
        body["parent"] = {"id": int(parent_id), "type": args.parent_type}
        resp = clio_request("POST", "/documents.json",
                            body=body, fields=UPLOAD_FIELDS)
    return resp["data"]


def finalize(doc_id, uuid):
    """Step 3: mark the version fully uploaded."""
    resp = clio_request("PATCH", f"/documents/{doc_id}.json",
                        body={"uuid": uuid, "fully_uploaded": True},
                        fields="id,name,content_type,size,updated_at,"
                               "latest_document_version{version_number,fully_uploaded}")
    return resp["data"]


def metadata_only(args):
    """No new file: just PATCH name and/or parent."""
    body = {}
    if args.name:
        body["name"] = args.name
    if args.parent_id:
        body["parent"] = {"id": int(args.parent_id), "type": args.parent_type}
    if not body:
        sys.exit("ERROR: nothing to update. Pass --name and/or --parent-id, "
                 "or pass --file to upload content.")
    resp = clio_request("PATCH", f"/documents/{args.document}.json", body=body,
                        fields="id,name,content_type,size,updated_at")
    return resp["data"]


def main():
    p = argparse.ArgumentParser(description="Upload or edit a Clio document.")
    p.add_argument("--file", help="Local path to the file to upload.")
    p.add_argument("--matter", help="Matter ID to file a NEW document under.")
    p.add_argument("--parent-id",
                   help="Explicit parent ID (Matter or Folder) for a new doc, "
                        "or the new parent when moving a doc.")
    p.add_argument("--parent-type", default="Matter",
                   choices=["Matter", "Folder"],
                   help="Parent type for --parent-id (default: Matter).")
    p.add_argument("--document",
                   help="Existing document ID: upload a new version (with --file) "
                        "or edit metadata (with --name/--parent-id).")
    p.add_argument("--name",
                   help="Display name for the document (defaults to the file name).")
    args = p.parse_args()

    # Metadata-only edit: existing doc, no new bytes.
    if not args.file:
        if not args.document:
            sys.exit("ERROR: provide --file to upload, or --document with "
                     "--name/--parent-id to edit metadata.")
        result = metadata_only(args)
        print(json.dumps(result, indent=2))
        return

    if not os.path.isfile(args.file):
        sys.exit(f"ERROR: file not found: {args.file}")
    file_name = args.name or os.path.basename(args.file)
    with open(args.file, "rb") as fh:
        file_bytes = fh.read()

    # Step 1 — register and get the signed S3 URL.
    doc = register(args, file_name)
    doc_id = doc["id"]
    version = doc["latest_document_version"]
    put_url = version["put_url"]
    put_headers = version.get("put_headers") or []

    # Clio may omit Content-Type; add a sensible default so downloads open right.
    if not any(h.get("name", "").lower() == "content-type" for h in put_headers):
        guessed = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        put_headers.append({"name": "Content-Type", "value": guessed})

    # Step 2 — upload the bytes straight to S3.
    s3_put(put_url, put_headers, file_bytes)

    # Step 3 — finalize.
    result = finalize(doc_id, version["uuid"])
    action = "new version uploaded" if args.document else "document uploaded"
    print(f"OK: {action} (document id {doc_id})")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
