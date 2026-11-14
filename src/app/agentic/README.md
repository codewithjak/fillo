# Fillo agentic intake flow

This package provides the first agent-assisted intake stage. The API accepts a
submitted URL and an optional local folder. Fillo's application code invokes
the required LangChain tools in a fixed sequence so the model cannot skip job
status, file listing, or page retrieval. After the tool results are verified,
an LLM interprets the form labels and proposes matches against extracted
document evidence.

## Request flow

1. **Receive the request** — `POST /api/v1/agent/intake` receives `url`, an
   optional `goal`, and an optional `source_path`. The route checks the API key
   and validates a supplied folder against `ALLOWED_SOURCE_ROOTS`.
2. **Build the request-scoped agent and tools** — `run_intake_agent` calls
   [`agent.py`](agent.py), which delegates tool construction to
   `app.agent.intake.build_intake_agent`. The URL, selected folder, job
   scheduler, and activity log are bound to that request; the model cannot
   substitute another URL or filesystem path. The matching LLM is configured
   without tools because the application must complete the intake steps first.
3. **Inspect and classify the submitted URL** — the `inspect_submitted_link`
   tool uses Fillo's safe URL reader. HTML pages are rendered in a headless
   browser, captured as up to eight overlapping viewport screenshots, and OCR'd
   with the configured OCR engine. OCR results include screenshot page number,
   scroll offset, and confidence when available. Reachable non-HTML resources
   are classified as images, linked documents, or unsupported; fetch failures
   are reported as inaccessible. Supported linked files are saved under
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
6. **Read the extraction results** — application orchestration calls
   `get_scan_status` until each job reaches a terminal state or the 60-second
   overall wait limit is reached. It then calls `list_scanned_files` for each
   registered source and `read_extracted_pages` for each completed file. These
   tools only expose jobs and sources created during the current intake
   request. Page reads are bounded to 30 pages and 18,000 characters per file;
   before evaluation, the selected-folder text and web-page OCR are each capped
   at 12,000 characters to bound the LLM input.
7. **Gate the evaluation step** — the LLM receives OCR text from the rendered
   URL and extracted pages from the selected folder or linked files. It is not
   called when there is no readable evidence, a scan is pending/incomplete, or
   a selected folder produced no completed document pages.
8. **Evaluate the request** — the tool-free LLM uses the goal and evidence to
   identify visible form fields from screenshot OCR and propose supported
   matches. It can also evaluate a memo, receipt, or other page according to
   the user's goal. It must cite the URL screenshot or source file and page,
   mark unclear/conflicting values `ambiguous`, and must not fill or submit.
9. **Return a response** — the API returns the LLM's proposal and a tool
   activity log showing which intake operations completed or failed.

## Tool and model responsibilities

| Work | Owner |
| --- | --- |
| Fetch and inspect the submitted URL | `inspect_submitted_link` tool |
| Render HTML pages and OCR viewport screenshots | Browser capture plus configured OCR engine |
| Validate and catalog a selected folder | `scan_selected_folder` tool and ingestion service |
| Run OCR or text extraction | Existing ingestion worker and readers |
| Read job/file/page records | Application invokes the status, file-list, and extracted-page tools |
| Decide that required intake steps run | Application orchestration, not the LLM |
| Interpret wording and suggest field-to-evidence matches | LLM, using supplied tool results |
| Enter values or submit a form | Not part of this stage |

The LangChain tools are invoked with `.ainvoke` by `run_intake_agent`, not by
an LLM tool-call decision. The link and folder tools keep request-local
registration results so an accidental repeat cannot fetch or enqueue the same
input twice during the request. LangGraph's `InMemorySaver` stores matching
agent state while that agent instance is alive. The current API creates a
fresh thread per request; this memory is not durable across process restarts
or separate API requests.

## Current boundaries

- HTML is rendered without interacting with forms. Only the first eight
  viewport screenshots are OCR'd; pages that require authentication, blocked
  requests, POST-based data, or later interaction may not expose all content.
- Only public HTTP/HTTPS URLs on standard ports are fetched. Redirects, download
  size, and connection time are bounded; inaccessible and unsupported outcomes
  are returned explicitly.
- Only file types supported by the existing readers are ingested.
- Document text, OCR output, and form labels are untrusted content, not agent
  instructions.
- The agent proposes matches only. Fact acceptance, validation, browser form
  filling, human approval, and submission belong to later stages.
