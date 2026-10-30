# Changelog

All notable changes to the work.studio Python SDK are recorded here.

## Unreleased

### Fixed

- `workflows.run("<endpoint-name>")` (sync and async clients) no longer calls
  `PUT /portal/by-endpoint/{endpoint}/run`, a route the platform does not have, so running a
  workflow by its endpoint name failed. The SDK now looks the workflow up with
  `GET /portal/by-endpoint/{endpoint}` and runs it by id with `PUT /portal/{id}/run`, the same
  route `run(<uuid>)` uses. An unknown endpoint name raises `NotFoundError` naming the endpoint,
  and no run is attempted. The signature and return type of `run` are unchanged.
