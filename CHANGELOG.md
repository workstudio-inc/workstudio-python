# Changelog

All notable changes to the work.studio Python SDK are recorded here.

## Unreleased

### Added

- `PermissionDeniedError`, a kind of `AuthenticationError`, for a 403. `missing_permission` is the permission the
  platform says the key lacks, and `code` says why when no permission would help (`TENANT_API_KEY_ONLY`,
  `API_KEY_NOT_ALLOWED`). Code that catches `AuthenticationError` keeps working.

### Fixed

- A 403 now says which permission to add. On most routes the platform has it only in `detail`, under the message
  "Permission denied", so that message was all the SDK reported.

### Docs

- The README lists what each call needs from a key.

## 0.2.0 - 2026-10-30

A contract audit of every public method against the platform's routes and reply shapes
(server code at origin/main, 2026-10-30). See `RELEASE-NOTES-sdk-contract-fixes.md` for the full
table, the evidence, and what is breaking.

### Fixed

- `workflows.run()` starts the run with `POST /api/v1/workflow/execute/{endpoint}` (an endpoint
  name) or `/execute/id/{globalUniqueId}` (a UUID), the platform's documented route for running a
  workflow from code, and follows it with `POST /run/{id}/wait`. In 0.1 it called
  `PUT /portal/by-endpoint/{endpoint}/run`, which does not exist, or the Designer's test route
  `PUT /portal/{id}/run`, and then failed to read the reply: every successful start raised a
  pydantic `ValidationError` after the run had already begun.
  - Running by endpoint name needs no definition read, so it works with a customer key (`svx_ck_`).
  - A workflow's row id (`Workflow.id`) still works with an organization key: the SDK looks up its
    global id and runs that.
  - `external_id` is sent (inside the input, where the platform reads it). 0.1 dropped it.
  - `sync=True` waits up to `timeout_seconds` with the long-poll wait (at most 110 s per call, so
    the load balancer never closes it); a run still going is returned as it stands.
- Run statuses: the run service's `FINISHED`, `WAITING_HUMAN`, `QUEUED`, `PARSING`, `TERMINATED`
  parse onto `RunStatus` (`COMPLETED`, `WAITING`, `PENDING`, `PENDING`, `CANCELLED`); the
  platform's word is kept in the new `WorkflowRun.raw_status`. An unknown status stays a string
  instead of failing the parse. In 0.1, `get_run()` failed on every finished run.
- `WorkflowRun` reads the run service's run: `finishedAt` (as `completed_at`), `inputData` (as
  `inputs`), the inline `value` (as `outputs`, when the platform sends it), `+0000` timestamps, and
  new fields `final_output_url`, `runtime_state_url`, `wait_info`, `workflow_global_unique_id`,
  `workflow_version`, `scope_key`, `trigger_type`, `parent_run_id`. `duration_ms` is computed when
  the platform does not send it. `workflow_id` is optional.
- `workflows.list()`, `workflows.list_runs()` and `agents.list()` read the platform's list shape
  (`data` + `pagination`). In 0.1 they always came back empty.
- `Workflow` reads `latestVersion` (as `version`) and the current version's status, and adds
  `global_unique_id`, `latest_version`, `inputs` and `owner_type`.
- `agents.get()` reads by the agent's row id (`/catalog/ai-agents/by-id/{id}`), falling back to the
  global id. In 0.1 it sent `Agent.id` to the global-id route and got 404.
- `Agent` reads the catalog's fields: `systemPrompt` (as `instructions`), `provider` (as
  `model_provider`), `toolCount` / `knowledgeBaseCount` (as `tools_enabled` /
  `knowledge_base_enabled`), and adds `global_unique_id`, `active`, `agent_status`.
- Ending a session (`LiveSession.close()`, the `with` block, `agents.chat()`) sends
  `DELETE /ai-runtime/agent-conversation/sessions/{id}`. 0.1 posted to `/sessions/{id}/end`, which
  does not exist, and ignored the error, so no session was ever ended.
- `MessageStatus` adds `BLOCKED_BY_GUARDRAIL` and `TIMEOUT`; a guardrail block no longer fails the
  parse. `MessageResponse` adds `guardrail_triggers`, `error_code`, `timestamp`.
- `session.get_state()` fills `total_turns`, `total_tokens`, `total_cost_usd` from the state's
  `metrics` (always 0 in 0.1); `created_at` is optional.
- `get_run_by_external_id()` URL-encodes the id and returns None only when there is no such run.
- `get()` / `get_by_endpoint()` URL-encode the endpoint name.
- Error messages come from the platform's reply (`message`, `errorMessage`), and a reply that is
  not a JSON object no longer raises `AttributeError`.
- Python 3.9: the package imports again (`UUID | str` annotations raised `TypeError`).

### Changed (behaviour callers may notice)

- `agents.list(status=...)` has no effect (the platform has no such filter; 0.1 sent a parameter it
  ignored) and warns. Use the new `active=True/False`.
- `get_run_by_external_id()` raises for errors other than 404 (a refused key, a server error);
  0.1 returned None for all of them.
- `send_message(include_debug=...)` is accepted and not sent; tool and knowledge-base details come
  back on every message.
- `run()` runs the workflow's **published** version, as the documented API call (`/execute`) does;
  a workflow with no published version is refused. 0.1 called the Designer's test route, which ran
  the working **draft** in debug mode.

### Needs on the platform

A key holding only *Run Automation* (`workflow:execute`) reads the runs it started, which
`run(sync=True)`, `get_run()` and `list_runs()` rely on, from the run-service change "API keys read
the runs they started" (run 0821ab7, 2026-10-21). Before that, such a key gets 404 on its own runs
unless it also holds *View Automation*.

## 0.1.0

First release.
