# Fillo agentic intake flow

This package provides the first agent-assisted intake stage. The API accepts a
submitted URL and an optional local folder. Existing Fillo code handles link
inspection, folder validation, scanning, OCR, and page retrieval. LangChain
lets the model choose and call those tools; the model then proposes matches
between extracted document evidence and inspected form fields.

## Request flow

1. **Receive the request** — `POST /api/v1/agent/intake` receives `url`, an
   optional `goal`, and an optional `source_path`. The route checks the API key
   and validates a supplied folder against `ALLOWED_SOURCE_ROOTS`.
2. **Build the request-scoped agent** — `run_intake_agent` calls
   [`agent.py`](agent.py), which delegates tool construction to
   `app.agent.intake.build_intake_agent`. The URL, selected folder, job
   scheduler, and activity log are bound to that request; the model cannot
   substitute another URL or filesystem path.
3. **Inspect the submitted URL** — the `inspect_submitted_link` tool uses
   Fillo's safe URL reader. Static HTML pages return readable text and any
   accessible form fields. Supported linked documents are saved under
   `REMOTE_SOURCE_ROOT` and registered with the existing ingestion service.
4. **Register selected documents** — when the request includes a local folder,
   `scan_selected_folder` resolves it against the configured allowed roots and
   calls `register_source_root`. That function catalogs files, creates job
   records, and schedules the existing worker. It is also used by Fillo's
   source API.
5. **Scan and extract text** — Fillo's scheduled `process_source` worker reads
   supported files and runs the configured text extraction or OCR pipeline.
   It saves page text and per-file statuses to MongoDB. The agent does not run
   OCR itself and does not start a second job.
6. **Read the extraction results** — the agent can call `get_scan_status`,
   `list_scanned_files`, and `read_extracted_pages`. These tools only expose
   jobs and sources created during the current intake request. Page reads are
   bounded to 30 pages and 18,000 characters for the model.
7. **Propose field matches** — after it has form fields and document evidence,
   the LLM proposes a value for each field with source file, page, supporting
   text, and confidence. It marks unsupported fields `no_match` and uncertain
   matches `ambiguous`; it must not fill or submit the form.
8. **Return a response** — the API returns the agent's summary and a tool
   activity log showing which intake operations completed or failed.

## Tool and model responsibilities

| Work | Owner |
| --- | --- |
| Fetch and inspect the submitted URL | `inspect_submitted_link` tool |
| Validate and catalog a selected folder | `scan_selected_folder` tool and ingestion service |
| Run OCR or text extraction | Existing ingestion worker and readers |
| Read job/file/page records | Status, file-list, and extracted-page tools |
| Interpret wording and suggest field-to-evidence matches | LLM |
| Enter values or submit a form | Not part of this stage |

The tool results and prior messages are agent context. In addition,
`build_intake_agent` keeps the link and folder registration results in
request-local caches so repeated calls do not fetch or enqueue them again.
LangGraph's `InMemorySaver` stores state for the configured thread while that
agent instance is alive. The current API creates a fresh thread per request;
this memory is not durable across process restarts or separate API requests.

## Current boundaries

- HTML inspection is static; pages requiring JavaScript, authentication, or
  browser interaction may not expose their fields.
- Only file types supported by the existing readers are ingested.
- Document text, OCR output, and form labels are untrusted content, not agent
  instructions.
- The agent proposes matches only. Fact acceptance, validation, browser form
  filling, human approval, and submission belong to later stages.
