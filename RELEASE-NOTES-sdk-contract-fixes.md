# workstudio (Python SDK): contract fixes - release notes

Branch `sdk-contract-fixes`, built on `sdk-run-by-name` (a043c94) with `release-next`
(fix-portal-run-reply, b4b9042) merged in. Not versioned, tagged or published: the version bump and
tag go to the owner for a GO. A `v*` tag publishes to PyPI.

## What was broken, and since when

Every broken call below dates from the SDK's first commit, 8e5086d (2026-05-06), and shipped in
**0.1.0** (tag `v0.1.0`, 2026-08-16). The server routes and shapes they should have matched already
existed then: base-common `PageResponse` (`data` + `pagination`) since before 2026-02, run
`WorkflowRunController` since 2025-12-26, trigger `WorkflowExecutionController` (`/execute`) since
2026-03-31. So in 0.1.0, as published:

| What a caller did | What happened |
|---|---|
| `workflows.run("<endpoint>")` | `PUT /portal/by-endpoint/{e}/run`: no such route, 404/405. |
| `workflows.run(<uuid>)` | `PUT /portal/{id}/run` started a run (the Designer test route: the **draft**, debug mode), then the reply `{runStatus, executionResult}` failed to parse as a `WorkflowRun`: **pydantic `ValidationError` after the run had started**. A caller that retried ran it twice. |
| `workflows.get_run()` / polling | The route exists, but `status: "FINISHED"` (and every other run-service status but RUNNING/PENDING/FAILED/CANCELLED) failed the parse. |
| `workflows.list()`, `list_runs()`, `agents.list()` | Always empty: the SDK read `content`/`pageInfo`; the platform sends `data`/`pagination`. |
| `agents.get(agent.id)` | 404: the catalog's `/{id}` takes the *global* id. |
| Ending a session | `POST /sessions/{id}/end` does not exist; the error was swallowed. No session was ever ended. |
| A guardrail-blocked or timed-out message | `MessageStatus` lacked `BLOCKED_BY_GUARDRAIL`/`TIMEOUT`: `ValidationError`. |
| `session.get_state()` totals | Always 0 (they live under `metrics`). |
| `run(..., external_id=...)` | Silently dropped. |
| `agents.list(status=...)` | Sent a parameter the platform ignores. |
| Python 3.9 | `import workstudio` raised `TypeError` (`UUID | str` annotations), though the package declares `>=3.9`. |

Interim fixes on the way (both unreleased): b4b9042 (2026-10-24) parsed the portal reply and mapped
statuses; a043c94 (2026-10-30) ran by name through `GET /portal/by-endpoint` + `PUT /portal/{id}/run`.
That second route choice fails for a customer key (`@TenantApiKeyOnly` on the lookup) and still ran
drafts, so this branch replaces it with `/execute`.

## Contract table (after this branch)

Server line numbers are origin/main on 2026-10-30. Prod routing: `api.work.studio`, paths
`/api/v1/workflow/...` with no `/{service}` prefix; the ALB sends `/api/v1/workflow/ai-runtime/*` to
ai-runtime (infrastructure `environments/monolith-prod/ecs-alb-routing.tf:52-69`) and everything
else to the monolith (`ecs-monolith.tf:146-162`), which embeds workflow-portal-backend,
workflow-run, workflow-trigger and workflow-catalog (spacevox-monolith `pom.xml`). The SDK sends
`X-API-Key` on every call (and `X-SCOPE-KEY` when `scope_id` is set); base-http
`ApiKeyPermissionInterceptor` admits a key only where the endpoint declares a key permission.

| method | route | exists? | request ok? | response ok? | auth ok? | evidence |
|---|---|---|---|---|---|---|
| `workflows.list` | GET /portal?page&size&search | yes | yes | was NO (content/pageInfo) - fixed | org key, `workflow:read` or `workflow:execute`; customer key 403 | portal `WorkflowPortalController.java:78-91` (`@TenantApiKeyOnly`), base-common `PageResponse.java` |
| `workflows.get` | GET /portal/{id} | yes | yes | partial (latestVersion, currentVersion.status, globalUniqueId unmapped) - fixed | as list; run-only key gets `WorkflowSummaryDto` | `WorkflowPortalController.java:125-133`, portal `WorkflowSummaryDto.java`, `WorkflowDto.java` |
| `workflows.get_by_endpoint` | GET /portal/by-endpoint/{e} | yes | name was not URL-encoded - fixed | as get | as get | `WorkflowPortalController.java:203-210` |
| `workflows.run(name)` | POST /execute/{endpoint}?async=true | yes | body = input object; `externalId` now in it | `WorkflowRouterRunStatusWithResultDto` mapped by `WorkflowRun.from_api` | any key with `workflow:execute`; a customer key runs for its bound scope | trigger `WorkflowExecutionController.java:87-104`, `:157-181`; `TriggerWorkflowUtil.java` executeWorkflowAsync (`externalId` read from input :570-577) |
| `workflows.run(uuid)` | POST /execute/id/{globalUniqueId}?async=true; on 404, GET /portal/{id} then retry with its global id | yes | as above | as above | as above; the row-id lookup needs an org key | `WorkflowExecutionController.java:122-137`, `WorkflowTriggerBindingService.java` executeByGlobalId |
| `run(sync=True)` wait | POST /run/{id}/wait?timeout=ms (<=110000) | yes | yes | `WorkflowRunDto`; 408 = still going, with the run | `workflow:read`/`run:read`/`workflow:execute`; execute-only key: its own runs | run `WorkflowRunController.java:473-498`, `RunReadAccess.java` |
| `workflows.get_run` | GET /run/{id} | yes | yes | was NO (statuses, `+0000`, finishedAt, inputData) - fixed | as wait | `WorkflowRunController.java:105-110`, run `service/dto/WorkflowRunDto.java`, `model/WorkflowRun.java:545-563` |
| `workflows.get_run_by_external_id` | GET /run/by-external-id/{x} | yes | id was not URL-encoded - fixed | as get_run; None only on 404 now | as wait | `WorkflowRunController.java:149-160` |
| `workflows.list_runs` | GET /run?page&size&workflowId | yes | yes | was NO (content/pageInfo) - fixed | as wait (narrowed to what the key may see) | `WorkflowRunController.java:84-102` |
| `agents.list` | GET /catalog/ai-agents?page&size&search&active | yes | `status` unsupported - deprecated, `active` added | was NO (content/pageInfo; systemPrompt/provider/toolCount unmapped) - fixed | org key, `catalog:read` | catalog `AIAgentUnifiedController.java:62` (`@TenantApiKeyOnly`), `:113-136`, `service/dto/AIAgentUnifiedDto.java` |
| `agents.get` | GET /catalog/ai-agents/by-id/{id}, fallback /{globalUniqueId} | yes | was wrong id kind - fixed | yes | as list | `AIAgentUnifiedController.java:92-110` |
| `agents.get_by_name` | list(search, size=50) | yes | page of 1 could miss the exact name - fixed | yes | as list | - |
| `agents.create_session` | POST /ai-runtime/agent-conversation/sessions | yes | `{agentId}` ok (row or global id) | `TestSessionResponse` ok | `agent:execute` | ai-runtime `AgentConversationController.java:54-73`, `dto/AgentTestDto.java` |
| `session.send_message` | POST .../sessions/{id}/messages | yes | `includeDebug` is not a field - no longer sent | was NO (`BLOCKED_BY_GUARDRAIL`, `TIMEOUT`, null lists, 404 reason) - fixed | `agent:execute` | `AgentConversationController.java:92-111`, `AgentTestDto.TestMessageResponse` |
| `session.get_state` | GET .../sessions/{id} | yes | yes | was NO (totals under `metrics`) - fixed | `agent:read` or `agent:execute` | `:130-151`, `AgentTestDto.TestSessionStateResponse` |
| `session.close` / `chat` | DELETE .../sessions/{id} | yes (was POST /end: **no**) - fixed | yes | 204 | `agent:execute` | `:162-178` |

## What callers must change

Nothing, for code that used the SDK's methods and models; the signatures are unchanged. Notes:

- `RunStatus` values are unchanged (`COMPLETED`, `WAITING`, ...). Compare with `RunStatus`, or read
  `run.raw_status` for the platform's word (`FINISHED`, `TERMINATED`).
- The result of a polled run is behind `run.final_output_url` (a short-lived link; fetch it without
  your API key). `run.outputs` is filled only when the platform hands the result back inline, which
  `run(sync=True)` usually gets from the wait.
- Run by endpoint name, or by the global id Designer shows under API. A customer key cannot run by
  row id (it may not read definitions to look the global id up).
- Replace `agents.list(status=...)` with `active=True/False`.

## Is any of this BREAKING?

- **For anyone who worked around the bugs by reading raw JSON** (calling the HTTP layer directly,
  or `client._http`): **not breaking.** No route they could have called changed, and the SDK's
  models were never a raw-dict API. Code that caught `pydantic.ValidationError` from `run()` and
  then looked the run up itself keeps working; it simply stops seeing the exception.
- **Behaviour changes that can surprise someone:**
  1. **`run()` now runs the published version, not the draft.** The 0.1 route ran the Designer's
     working draft in debug mode (portal `WorkflowService` debugMode=true = draft). A workflow never
     published is now refused. Anyone who relied on `run()` executing drafts (it did execute, before
     raising) sees different behaviour. Intended: this is the documented API behaviour.
  2. `get_run_by_external_id()` raises on a refused key or a server error, where 0.1 returned None.
  3. `WorkflowRun.workflow_id` is `Optional[UUID]` and `WorkflowRun.status` is
     `Union[RunStatus, str]` (an unknown status stays text). Type checkers may flag code that assumed
     neither could happen; at runtime nothing that worked before changes.
  4. Sessions are now actually ended on `close()`; code that reused a session id after closing it
     gets 404.
- **Python 3.9 users:** the package now imports. Not breaking.

## Ship gates (platform)

- Prod must include run 0821ab7 (2026-10-21, "API keys read the runs they started"): without it a
  key holding only `workflow:execute` cannot wait on or read its own runs, so `run(sync=True)` fails
  after starting the run. Confirm the live monolith contains it before tagging.
- public-docs branch `sdk-contract-fixes` updates the pages that say 0.1.x does not match the API;
  it ships with this release, never before.

## Tests

`tests/test_contract.py`: 29 contract tests, each fixture built from the server DTO it names. 28 of
them fail against a043c94. Full suite: 50 passed, 2 skipped (the opt-in integration tests, which
need `WORKSTUDIO_API_KEY` and are never run here).
