---
name: clio-documents
description: "Upload, edit, replace, or revise documents in Clio Manage's document management, and list or download existing ones. Use this whenever the user wants to put a file into Clio or change a document's contents — 'upload the signed retainer to the Smith matter', 'save this PDF to Clio', 'attach the medical records to the matter', 'replace the demand letter with the new version', 'upload a revised draft of the complaint', 'rename this document in Clio', 'move the file to the Pleadings folder', or 'download the police report from matter 12345'. Handles Clio's 3-step upload flow (register the file, PUT the bytes to S3, finalize) as well as new-version uploads and metadata edits. This skill WRITES to Clio (it creates and updates documents), so confirm the target matter/document before uploading. For deadline/task analysis of a matter use clio-matter-analysis; for opening a new matter use clio-mva-new-matter; for arbitrary Clio API calls use the clio skill."
---

# Clio Documents

Upload files into Clio Manage's document management, replace a document's contents
with a new version, rename or move documents, and list or download existing ones.

This skill is self-contained: it talks to the Clio Manage API v4 through the Maton
gateway and does not depend on the base `clio` skill being loaded.

## Setup

All calls go through the Maton gateway and authenticate with your Maton API key:

```
Base URL:  https://gateway.maton.ai/clio/api/v4
Auth:      Authorization: Bearer $MATON_API_KEY
```

- Set `MATON_API_KEY` in the environment (get it at [maton.ai/settings](https://maton.ai/settings)).
- If you have multiple Clio connections, set `MATON_CONNECTION` to the connection id,
  or pass the `Maton-Connection` header. Otherwise the default (oldest) connection is used.
- **OAuth scope:** the `documents` endpoints require the Documents scope beyond the
  basic integration. If a write returns `403`, re-authorize the Clio connection at
  [ctrl.maton.ai](https://ctrl.maton.ai) with document permissions enabled.

## The helper script

`scripts/upload_document.py` performs the tricky multi-step upload/edit flows for you.
Prefer it over hand-rolling the S3 dance.

```bash
# Upload a NEW document to a matter
python scripts/upload_document.py --file ./retainer.pdf --matter 12345

# Upload into a specific folder, with a custom display name
python scripts/upload_document.py --file ./records.pdf --parent-id 987 \
    --parent-type Folder --name "Medical Records - Batch 1.pdf"

# EDIT a document's contents = upload a NEW VERSION of an existing document
python scripts/upload_document.py --file ./demand_v2.pdf --document 67890

# Rename / move an existing document (metadata only, no new bytes)
python scripts/upload_document.py --document 67890 --name "Final Demand.pdf"
python scripts/upload_document.py --document 67890 --parent-id 555 --parent-type Folder
```

Set `MATON_CONNECTION` to target a specific Clio connection.

## How uploading works (the 3-step flow)

Clio does not accept file bytes directly on its API. Uploading is three steps; the
helper script does all three, but here is the contract if you need to do it manually.

**Step 1 — register the file and get a one-time S3 URL.** Request the
`latest_document_version` fields so the response includes `put_url` and `put_headers`:

```bash
POST /clio/api/v4/documents.json?fields=id,latest_document_version{uuid,put_url,put_headers}
Content-Type: application/json

{
  "data": {
    "name": "retainer.pdf",
    "parent": {"id": 12345, "type": "Matter"}
  }
}
```

**Step 2 — PUT the raw bytes to S3.** Send the file to `put_url`, including **every**
header from `put_headers` exactly as returned. This request goes to **Amazon S3, not
the Maton gateway**, and must **NOT** include the `Authorization: Bearer $MATON_API_KEY`
header — the signed URL is its own authentication.

**Step 3 — finalize.** Mark the version complete using the `uuid` from step 1. Until
this runs, the document exists in Clio but has no downloadable content:

```bash
PATCH /clio/api/v4/documents/{id}.json
Content-Type: application/json

{
  "data": {"uuid": "<uuid-from-step-1>", "fully_uploaded": true}
}
```

## Editing a document (new version)

To replace a document's contents while keeping its history, run the same three steps
but make **step 1 a `PATCH`** to `/documents/{id}.json` (instead of `POST`); Clio
returns a fresh `put_url` for a new version and preserves the prior versions. The
helper handles this when you pass `--document <id>` together with `--file`.

## Rename / move (metadata only)

To change a document's name or move it to a different matter or folder without
uploading new content, PATCH the metadata (no bytes, no `fully_uploaded`):

```bash
PATCH /clio/api/v4/documents/{id}.json
Content-Type: application/json

{
  "data": {
    "name": "Final Demand.pdf",
    "parent": {"id": 555, "type": "Folder"}
  }
}
```

## Reading documents

```bash
# List documents (optionally filter by matter)
GET /clio/api/v4/documents?fields=id,name,content_type,size,updated_at,matter{id,description}
GET /clio/api/v4/documents?matter_id=12345&fields=id,name,content_type,size,updated_at

# Get one document's metadata
GET /clio/api/v4/documents/{id}?fields=id,name,content_type,size,created_at,updated_at

# Download the file bytes
GET /clio/api/v4/documents/{id}/download
```

## Deleting a document

```bash
DELETE /clio/api/v4/documents/{id}
```

## Notes & gotchas

- `parent.type` is `Matter` to file directly on a matter, or `Folder` for a subfolder.
- The S3 PUT (step 2) must omit the Maton Authorization header and include all `put_headers`.
- Always finalize (step 3). A document with no completed finalize shows in Clio but
  cannot be downloaded.
- Confirm the target matter/document with the user before uploading — this writes to Clio.
- Rate limit: 50 requests/min during peak hours (`429` with `Retry-After` when throttled).

## Resources

- [Clio Documents API](https://docs.developers.clio.com/api-reference/)
- [Clio Permissions](https://docs.developers.clio.com/api-docs/permissions/)
- Maton connections: [ctrl.maton.ai](https://ctrl.maton.ai)
