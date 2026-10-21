# Changelog

## 0.2.0 - unreleased

Running a workflow from code now works the way the platform does it. In 0.1, `workflows.run()`
called a Designer test route (`PUT /portal/{id}/run`, and a `/portal/by-endpoint/{slug}/run` that
never existed), and every run came back as a validation error because the SDK expected statuses
(`COMPLETED`, `TIMED_OUT` ...) and fields (`outputs`) the platform does not send.

### Fixed

- `workflows.run()` starts the run with `POST /api/v1/workflow/execute/id/{globalUniqueId}`
  (a UUID) or `/execute/{slug}` (anything else), then waits for it and fetches its result.
- Run statuses are the platform's: `QUEUED`, `PARSING`, `PENDING`, `RUNNING`, `WAITING_HUMAN`,
  `FINISHED`, `FAILED`, `CANCELLED`, `TERMINATED`. `RunStatus.COMPLETED` and `RunStatus.WAITING`
  remain, as aliases of `FINISHED` and `WAITING_HUMAN`. A status the SDK does not know is kept as a
  string instead of failing the parse.
- `WorkflowRun` matches the run the API returns (`inputData`, `finishedAt`, `finalOutputUrl`,
  `waitInfo`, `scopeKey` ...; timestamps with a `+0000` offset parse). `workflow_id` is optional.
- The result of a run is fetched from `finalOutputUrl` and decoded - the stored JSON usually holds
  the result as a JSON string, sometimes twice - and an expired link is refreshed. The download
  never carries your API key.
- `list()`, `list_runs()` read the platform's list shape (`data` + `pagination`); in 0.1 they
  always came back empty.
- `get_run_by_external_id()` returns None only when there is no such run, instead of swallowing
  every error, and URL-encodes the id (it may hold `/`, spaces, `?`).
- A result link that is not an absolute http(s) URL raises `APIError` rather than an `httpx`
  exception.
- Python 3.9: the package no longer fails to import (`UUID | str` annotations).

### Added

- `workflows.start()` - start a run and return at once.
- `workflows.wait()` - wait for a run to end, by long-polling `/run/{id}/wait` (falls back to
  polling); `return_on_waiting=True` returns as soon as the run pauses.
- `workflows.get_output()`, `workflows.refresh_output_urls()`, `workflows.cancel()`.
- `run.output`, `run.succeeded`, `run.is_terminal`, `run.is_waiting`, `run.inputs`.
- `RunFailedError` (raised by `run()` for a run that ended without succeeding),
  `RunTimeoutError`, and `PermissionDeniedError` for 403 (a subclass of `AuthenticationError`).
- `scope_key=` per call and on the client, for TENANT keys acting for one customer.
- `transport=` on the clients, for tests and proxies.

### Changed

- `run(sync=False)` and `run(timeout_seconds=...)` still work but are deprecated: use `start()` and
  `run(timeout=...)`.
- `RunStatus.PENDING` is the platform's PENDING; `RunStatus.TIMED_OUT` is gone (the platform has
  no such status - a run it stops reads `TERMINATED`).
- `WorkflowRunRequest` is removed; it described a request the API does not take.

### Needs on the platform

A customer key (`svx_ck_`) with its default permission (*Execute Workflows*) can read the runs it
starts only on a platform that includes the run-service change "API keys read the runs they
started" (October 2026). Before that, `wait()` / `get_run()` answer 403 for such a key unless it is
also given *Read Workflows*.

## 0.1.0

First release.
