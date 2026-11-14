# fillo

Fillo scans configured local folders, extracts text from supported documents, and
provides authenticated API endpoints for tracking ingestion jobs and reading the
extracted pages.

The initial LangChain intake agent can also inspect a user-provided public link.
It renders HTML pages in a headless browser, OCRs visible screenshots, and
queues supported linked documents through the existing ingestion worker. It
uses the URL and selected-folder evidence to evaluate the user's goal and
propose matches; it does not fill or submit forms.

## Requirements

- Python 3.12 or newer
- MongoDB
- Playwright Chromium for rendering web pages
- Tesseract OCR for scanned PDFs and images when `OCR_ENGINE=tesseract`
- `uv` to install and run the project

The current readers support PDF, JPG/JPEG, PNG, HEIC, DOCX, and TXT. Other file
types are listed as skipped. OCR uses local Tesseract by default. Setting
`OCR_ENGINE=claude` sends scanned page images to the Anthropic API and also
requires `ANTHROPIC_API_KEY`.

## Configuration

Copy `.env.example` to `.env` and set:

- `MONGO_URI`: MongoDB connection string.
- `PORT`: local HTTP port.
- `DB`: MongoDB database name.
- `API_KEY`: a long random secret required by every API endpoint. Send it in the
  `X-API-Key` request header.
- `ALLOWED_SOURCE_ROOTS`: a JSON array of absolute directories the service may
  scan. The requested folder must be one of these directories or a child of one.
- `OCR_ENGINE` and `OCR_LANG`: optional Tesseract settings. Set
  `OCR_ENGINE=claude` and `ANTHROPIC_API_KEY` to use Claude Vision OCR.
- `ANTHROPIC_API_KEY`: required by the intake agent; also required for Claude
  Vision OCR when selected.
- `AGENT_MODEL`: optional Anthropic model name for LangChain (defaults to
  `claude-sonnet-5`).
- `REMOTE_SOURCE_ROOT`: local managed directory for downloaded linked
  documents (defaults to `./data/remote-sources`).

Fillo binds to `127.0.0.1` when started with its command. Keep it on a trusted
machine; use an authenticated, TLS protected deployment if you intentionally
expose it over a network.

## Run

```sh
uv sync
uv run playwright install chromium
uv run fillo
```

The API documentation is available at `http://127.0.0.1:<PORT>/docs`.
Export the configured key for the example commands, replacing the value with
the same secret used for `API_KEY` in `.env`:

```sh
export FILLO_API_KEY='replace-with-a-long-random-secret'
```

## Ingestion API

Create a source by giving the service an absolute folder path on the service's
machine:

```sh
curl -X POST "http://127.0.0.1:8000/api/v1/sources" \
  -H "X-API-Key: $FILLO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"path":"/home/user/documents/application"}'
```

The response contains `source_id` and `job_id`. Poll the job:

```sh
curl "http://127.0.0.1:8000/api/v1/jobs/<job_id>" \
  -H "X-API-Key: $FILLO_API_KEY"
```

Job status is `pending`, `running`, `completed`, `partial_failure`, `failed`, or
`incomplete`. Per-file counts are returned in the `files` object.

List files, optionally filtering by status:

```sh
curl "http://127.0.0.1:8000/api/v1/sources/<source_id>/files?status=done" \
  -H "X-API-Key: $FILLO_API_KEY"
```

Read extracted pages by the file's `rel_path` from that listing:

```sh
curl --get "http://127.0.0.1:8000/api/v1/sources/<source_id>/pages" \
  --data-urlencode "rel_path=application/cnic.jpg" \
  -H "X-API-Key: $FILLO_API_KEY"
```

Jobs are stored in MongoDB and pending or interrupted jobs are resumed when the
service starts. Run one Fillo server process against a database at a time.

## Agentic intake

Give the intake agent a public web page or supported document link.
For an HTML link, Fillo renders the page in Playwright, captures up to eight
overlapping viewport screenshots, and OCRs the visible content. For a supported
document or image link, Fillo downloads the resource into `REMOTE_SOURCE_ROOT`
and queues the existing reader/OCR worker. You can also provide an allowed
local folder for scanning; the LLM evaluates the URL and extracted file
evidence against the request goal.

```sh
curl -X POST "http://127.0.0.1:8000/api/v1/agent/intake" \
  -H "X-API-Key: $FILLO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url":"https://example.org/purchase-order.pdf",
    "goal":"Inspect this purchase order and report what Fillo could read",
    "source_path":"/home/user/documents/application"
  }'
```

`source_path` is optional and must be inside `ALLOWED_SOURCE_ROOTS`. Application
orchestration invokes the LangChain tools to inspect the link, start scans,
check job status, list files, and read extracted pages. The response includes
the agent's evaluation and a tool activity list. Link and browser subresource
fetching is limited to public HTTP(S) hosts on standard ports, bounded redirects,
requests, screenshots, and download sizes. OCR text is sent to the configured
agent/OCR providers. Fillo does not configure LangSmith tracing. Downloaded
documents remain under `REMOTE_SOURCE_ROOT`, and extracted pages remain in
MongoDB; delete/retention controls are a later phase.

This is an intake-only agent: pages requiring sign-in, blocked requests, or
POST-based loading may not expose all content. The agent never fills or submits
a form in this phase. Install the Playwright browser after syncing dependencies:
`uv run playwright install chromium`.
