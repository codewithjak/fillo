# Fillo agentic intake flow

This is Fillo's goal-planning and document-intake stage. The API accepts a
submitted URL and an optional local folder. An LLM turns the user's goal into a
structured plan, then a LangChain agent chooses and calls request-bound intake
tools. The agent can inspect the URL, decide whether the selected folder is
relevant, and choose the next status, file-list, or page-read call from the
results it receives.

## Request flow

1. **Receive the request** — `POST /api/v1/agent/intake` receives `url`, an
   optional `goal`, and an optional `source_path`. The route checks the API key
   and validates a supplied folder against `ALLOWED_SOURCE_ROOTS`.
2. **Plan the goal** — the configured LLM returns a validated `GoalPlan` with
   `action`, `target_record`, `needed_evidence`, and `expected_result`. Fillo
   returns this plan in the API response and gives it to the intake agent as
   intent context, not as document evidence.
3. **Build the request-bound agent** — `run_intake_agent` calls
   [`agent.py`](agent.py), which delegates tool construction to
   `app.agent.intake.build_intake_agent`. The submitted URL, selected folder,
   job scheduler, and activity log are bound to that request. Tools only accept
   source and job IDs created by the same request; the model cannot substitute
   another URL or filesystem path.
4. **Inspect the URL** — the agent starts with `inspect_submitted_link`. The
   tool uses Fillo's safe URL reader. HTML pages are rendered in a headless
   browser, captured as up to eight overlapping viewport screenshots, and OCR'd
   with the configured OCR engine. OCR results include screenshot page number,
   scroll offset, and confidence when available. Reachable non-HTML resources
   are classified as images, linked documents, or unsupported; fetch failures
   are reported as inaccessible. Supported linked files are saved under
   `REMOTE_SOURCE_ROOT` and registered with the existing ingestion service.
5. **Choose source-document work** — after seeing URL results, the agent calls
   `scan_selected_folder` when the goal needs information from the selected
   documents. That tool checks the configured allowed roots, catalogs files,
   creates job records, and schedules the existing worker. If the folder is
   irrelevant to the goal, the agent can skip it.
6. **Choose the next read steps** — from tool results, the agent calls
   `get_scan_status` for returned job IDs, then lists files after a terminal
   status, and reads relevant completed files. The tools reject unknown job or
   source IDs, require a listed file path before reading, and avoid repeating
   cached reads. Status checks stop after eight calls or 60 seconds per job.
   Page reads share a 12,000-character request budget and are limited to 50
   files per source. The agent loop is bounded to 24 graph steps.
7. **Evaluate from tool evidence** — the LLM responds to the user's goal using
   the tool results in its conversation. It should cite the URL screenshot or
   source file and page, mark unclear or conflicting values `ambiguous`, and
   avoid guessing. Tool outputs, document text, OCR, and form labels are
   untrusted content, not agent instructions.
8. **Return the result** — the API returns `goal_plan`, the agent's response,
   and `tool_activity`, including completed, failed, and cached operations.

## Tool and model responsibilities

| Work | Owner |
| --- | --- |
| Interpret the user's requested outcome | LLM goal planner |
| Choose and sequence intake tools | LangChain agent / LLM |
| Enforce allowed URL and folder access | Application and request-bound tools |
| Fetch a URL, render HTML, and run OCR | `inspect_submitted_link` tool, browser capture, configured OCR engine |
| Catalog a selected folder and enqueue a scan | `scan_selected_folder` tool and ingestion service |
| Run document OCR or text extraction | Existing ingestion worker and readers |
| Choose which job/file/page results to read next | LangChain agent / LLM, within tool checks and request limits |
| Interpret extracted evidence and propose values | LLM |
| Enter values, create records, or submit forms | Not part of this stage |

The agent receives the tools through LangChain's agent loop. The application
does not invoke status, listing, and page-reading tools in a fixed sequence.
Tool closures keep request-local results to prevent repeated URL fetches,
folder scans, file listings, and page reads. Each API request runs a fresh
agent invocation without a configured checkpointer; LangChain's agent runtime
uses LangGraph internally, but Fillo does not save graph checkpoints. Agent
state is limited to that invocation and is not available for later polling or
resumption.

## Current boundaries

- HTML is rendered without interacting with forms. Only the first eight
  viewport screenshots are OCR'd; pages that require authentication, blocked
  requests, POST-based data, or later interaction may not expose all content.
- Only public HTTP/HTTPS URLs on standard ports are fetched. Redirects, download
  size, and connection time are bounded; inaccessible and unsupported outcomes
  are returned explicitly.
- Only file types supported by the existing readers are ingested.
- The agent proposes and summarizes only. Fact acceptance, proposal
  validation, browser form filling, human approval, record creation, and
  submission belong to later stages.
