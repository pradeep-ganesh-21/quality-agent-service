# Quality agent POC design

## 1. Purpose and authority

This document is the executable specification for coding agents that build the quality agent proof of concept. Implement the behavior stated here. Do not infer missing behavior from nearby files.

The existing `requirements.txt` is a prose problem statement, not a Python dependency file. The existing `run.json` is a legacy aggregate example. `Mongo Schema.txt` is a stale, non-JSON draft. `quality-agent-architecture.drawio` describes a production direction. `noc-agent.drawio` is also legacy context. Keep all five files unchanged.

This document supersedes those sources when they conflict. It does not claim that the API, browser app, deployment files, commands, or tests already exist. Everything described here is to be built.

Build toward this complete repository shape. Files listed here are planned outputs, not current implementation claims:

```text
.env.example
.gitignore
AGENTS.md
DESIGN.md
docker-compose.yml
docker-compose.test.yml
api/
  Dockerfile
  pyproject.toml
  app/
    __init__.py
    main.py
    config.py
    dependencies.py
    domain.py
    errors.py
    exception_handlers.py
    controllers/
      __init__.py
      sessions.py
      runs.py
      health.py
    services/
      __init__.py
      session_service.py
      run_service.py
      mapping.py
    repositories/
      __init__.py
      protocols.py
      mongo_runtime.py
      mongo_session_repository.py
      mongo_run_repository.py
      indexes.py
    schemas/
      __init__.py
      sessions.py
      runs.py
  tests/
    unit/
    integration/
web/
  Dockerfile
  server/
    pyproject.toml
    app/
      __init__.py
      main.py
      config.py
      errors.py
      routes.py
    tests/
  frontend/
    package.json
    package-lock.json
    index.html
    src/
    tests/
nginx/
  nginx.conf
mongo/
  init-app-user.js
scripts/
  smoke.py
```

The POC has four service containers on one host and one shared Docker network:

1. `nginx`
2. `api`
3. `web`
4. `mongo`

Only NGINX publishes a host port: `0.0.0.0:8080:80`. MongoDB uses a named volume. The Mongo initialization script runs in the existing `mongo` container. It is not a fifth service.

## 2. Scope and exclusions

Build these capabilities:

- Store session documents and run documents in separate MongoDB collections.
- Accept session creation, run creation, and open-session partial updates.
- List sessions and return one session with its runs.
- Render session lists and details in a client-side React application.
- Put a Python FastAPI webserver BFF between the browser and the API.
- Route public traffic through NGINX.
- Supply automated tests for validation, persistence, concurrency, the BFF, the UI, and the composed HTTP path.

Do not add the following:

- HTTP authentication, authorization, tokens, TLS, certificates, or HTTPS redirects
- request body size caps in NGINX or either FastAPI application
- CORS middleware as a security control
- server-side rendering
- pagination, result limits, silent truncation, filters, or search
- retries, queues, sweepers, caches, Redis, or cross-collection transactions
- idempotency keys, replay deduplication, optimistic counters, or alternate ID lookup
- `PUT`, delete endpoints, generic CRUD bases, an ODM, Motor, or a separate business or domain layer
- a dependency injection container, provider auto-registration, or speculative extension folders
- automatic computation or verification of outcome counts

The API is intentionally unauthenticated. Any host that can reach port 8080 can read and write `/v1/*`. Unlimited request and response bodies can consume application memory, network capacity, and disk. Do not reduce these risks by changing the approved POC contract. Document them in deployment instructions and keep production use out of scope.

MongoDB still limits each final BSON document to 16 MiB. A session `PATCH` can cross this limit as metadata grows. Return `413` when that happens.

## 3. Architecture and request flow

The request paths are:

```text
quality agent -> NGINX /v1/* -> API -> MongoDB
browser -> NGINX /* -> web BFF -> API -> MongoDB
browser -> NGINX /ui/api/* -> web BFF -> API -> MongoDB
```

The browser fetches only relative BFF URLs:

```text
/ui/api/sessions
/ui/api/sessions/{session_id}
```

The BFF calls `http://api:8000/v1/...`. It does not aggregate counts, reinterpret fields, cache responses, or retry requests. Quality agents call the public `/v1/*` endpoints through NGINX. The BFF is a presentation boundary, not a security boundary. The same-origin API remains publicly reachable at `/v1/*`.

React renders JSON in the browser. There is no SSR. Node 22 is used only in a multistage image build for the Vite bundle. The final `web` image runs Python, FastAPI, and Uvicorn. It contains the built static assets but no Node runtime.

### Production diagram deviations

| Topic | Frozen production diagram or legacy source | POC contract |
| --- | --- | --- |
| Transport and identity | HTTPS and authenticated agents | HTTP, no HTTP authentication |
| Step identity | Run IDs | Step names in `last_step_executed` |
| Session updates | Completion-oriented | Open partial `PATCH` while status is `IN_PROGRESS` |
| Endpoints | Four original endpoints | Five `/v1` endpoints plus internal health routes |
| Legacy IDs | Agent UUIDs and aggregate batch shape | Server-generated MongoDB ObjectIds and one run per request |
| `recorded_by` | Authenticated root field | No synthetic root field; supplied identity objects are unverified extras |
| Versioning | Separate version field | Only server-generated `schema_version: 1` |
| Initial outcome | Incomplete draft values | `execution_outcome: null`, never fake zeros |
| Run timestamp | `at` in the sample | `occurred_at` on storage and response; `at` accepted only as an input alias |

The production diagram already permits Web to API communication. The POC makes the React SPA and Python BFF concrete, so the BFF is not necessarily a production deviation.

## 4. API code structure and dependency direction

Use Python 3.12, FastAPI, Pydantic v2, Uvicorn, and the official PyMongo `AsyncMongoClient`. Use PyMongo `>=4.15,<5` initially, then lock an exact compatible version during implementation. Lock exact compatible versions for FastAPI, Pydantic v2, Uvicorn, and HTTPX as part of implementation. Do not claim compatibility until the lock and tests exist.

Use these dependencies:

```text
controllers -> services -> repository protocols
repositories -> PyMongo and BSON
main/dependencies -> concrete construction
exception_handlers -> FastAPI and application exceptions
```

Controllers own HTTP routing and translate validated inputs into service calls. Services own business rules and depend on narrow repository protocols. Repository adapters own persistence details. `domain.py` contains only shared enums, currently session status. Do not create a separate domain or business package.

`ObjectId`, `bson`, MongoDB clients, cursors, filters, update operators, and pipeline syntax must stay in repository adapter files. `indexes.py` may contain MongoDB index definitions. Repository protocols may use primitive ID strings, dictionaries used as DTOs, and timezone-aware `datetime` values. They must not expose MongoDB clients, filters, cursors, or BSON IDs.

The protocols are real test seams. They let service tests use small fakes without importing MongoDB. Keep each protocol limited to operations the service currently needs. Do not introduce generic repositories. Define these exact operations in `protocols.py`:

```python
from typing import Any, Mapping, Protocol, TypeAlias

SessionRecord: TypeAlias = dict[str, Any]
RunRecord: TypeAlias = dict[str, Any]

class SessionRepository(Protocol):
    async def create(self, values: Mapping[str, Any]) -> str: ...
    async def exists(self, session_id: str) -> bool: ...
    async def get(self, session_id: str) -> SessionRecord | None: ...
    async def list_all(self) -> list[SessionRecord]: ...
    async def patch_open_session(
        self,
        session_id: str,
        known: Mapping[str, Any],
        extras: Mapping[str, Any],
    ) -> str: ...

class RunRepository(Protocol):
    async def create(
        self,
        session_id: str,
        values: Mapping[str, Any],
    ) -> str: ...
    async def list_for_session(self, session_id: str) -> list[RunRecord]: ...
```

The record dictionaries are application DTOs. Their IDs are strings and their timestamps are Python datetimes. They never contain ObjectIds, clients, cursors, filters, or MongoDB operators.

Use this call mapping:

| Router operation | Service operation | Repository operations |
| --- | --- | --- |
| Create session | `SessionService.create_session` | `SessionRepository.create` |
| Create run | `RunService.create_run` | `SessionRepository.exists`, then `RunRepository.create` |
| Patch session | `SessionService.patch_session` | `SessionRepository.patch_open_session` |
| List sessions | `SessionService.list_sessions` | `SessionRepository.list_all` |
| Get session detail | `SessionService.get_session` | `SessionRepository.get`, then `RunRepository.list_for_session` |

Services and `mapping.py` validate and partition values. Services set `schema_version`, initial status fields, and `received_at`. `RunService.create_run` checks parent existence before insertion, regardless of parent status. Repositories generate ObjectIds, copy inputs, issue database operations, apply read sorting, and map stored BSON to application DTOs. Do not duplicate business checks in adapters.

`repositories/mongo_runtime.py` owns the PyMongo client, database handle, ping, index startup, and shutdown. Its factory constructs the client exactly as follows, using values from settings:

```python
AsyncMongoClient(
    uri,
    tz_aware=True,
    tzinfo=timezone.utc,
    serverSelectionTimeoutMS=5000,
    socketTimeoutMS=30000,
)
```

The adapter factory returns initialized session and run repository objects plus an async close operation. `main.py` calls this factory from lifespan. This keeps `AsyncMongoClient`, the database handle, BSON, and index calls inside repository adapter files.

`dependencies.py` contains plain FastAPI providers. Lifespan stores the initialized repository objects on `app.state`. Providers read those repositories and construct lightweight services. They do not expose a database handle to services and do not create a client per request.

`main.py` exposes an application factory and a lifespan context. Lifespan must:

1. Call the repository adapter factory once for the event loop. Never create resources at import time.
2. Let that factory ping MongoDB and create the exact indexes in section 10.
3. Store initialized repository objects on `app.state`.
4. Await the adapter close operation during shutdown.

Startup must fail with a nonzero process exit if ping or index creation fails. Do not use developer reload in containers. Run one Uvicorn worker by default. A compose startup gate does not guarantee later availability.

PyMongo async `find()` returns an async cursor synchronously. Do not await `find()`. Await network operations such as `insert_one`, `update_one`, `find_one`, cursor `to_list`, database `command`, and client close according to the pinned driver API. Do not share an async client across event loops or threads.

## 5. Storage model

Use two collections named `sessions` and `runs` in `MONGO_DB_NAME`.

### Session fields

| Field | Stored BSON type | API JSON type and mapping |
| --- | --- | --- |
| `_id` | ObjectId generated by the repository | `session_id`, 24-character lowercase hexadecimal string |
| `schema_version` | 32-bit integer with value `1` | JSON integer with value `1` |
| `started_at` | BSON UTC datetime | RFC 3339 UTC string with milliseconds |
| `received_at` | BSON UTC datetime | RFC 3339 UTC string with milliseconds |
| `status` | String | JSON string |
| `completion_time` | BSON UTC datetime or null | RFC 3339 UTC string with milliseconds or null |
| `last_step_executed` | Array of strings | JSON array of strings |
| `execution_outcome` | Document or null | JSON object or null |
| `metadata` | Document | JSON object |

The session document has only `_id` as its identifier. Do not store a duplicate `session_id` field. The ObjectId is a BSON value, never a string in storage.

### Run fields

| Field | Stored BSON type | API JSON type and mapping |
| --- | --- | --- |
| `_id` | ObjectId generated by the repository | `run_id`, 24-character lowercase hexadecimal string |
| `session_id` | Parent ObjectId parsed from URL | `session_id`, 24-character lowercase hexadecimal string |
| `schema_version` | 32-bit integer with value `1` | JSON integer with value `1` |
| `step` | String | JSON string |
| `command` | String | JSON string |
| `verdict` | String | JSON string |
| `occurred_at` | BSON UTC datetime | RFC 3339 UTC string with milliseconds |
| `received_at` | BSON UTC datetime | RFC 3339 UTC string with milliseconds |
| `details` | Document | JSON object |

The run `_id` is its own server-generated ObjectId. The stored `session_id` is the parent session ObjectId parsed from the URL. Do not store a duplicate `run_id`.

On output, convert ObjectIds explicitly to 24-character lowercase hexadecimal strings. Rename session `_id` to `session_id` and run `_id` to `run_id`. Do not emit `storage_id` or Extended JSON.

`schema_version` is always the server-generated integer `1`. `received_at` is generated by the server in UTC. Store all accepted timestamps as timezone-aware UTC Python datetimes, truncated to BSON millisecond precision.

`metadata` and `details` are server-generated wrappers. Every unrecognized top-level request field is moved into the relevant wrapper as its parsed JSON value. Promotion consumes recognized fields, so a promoted value is not copied into extras.

If a session input contains a flat field literally named `metadata`, treat it as an ordinary extra. Store it at `metadata.metadata`. If a run input contains a flat field literally named `details`, store it at `details.details`. Clients cannot submit a prewrapped storage object.

`recorded_by` and `invoked_by` are distinct names. If supplied, both are unverified identity extras. Session extras go under `metadata`; run extras go under `details`. Do not synthesize `recorded_by`, authenticate either value, or promote either to the root.

Unknown nested values may contain objects, arrays, dots in key names, dollar-prefixed key names, nulls, numbers, booleans, and strings. Preserve the parsed structure at every depth. Never flatten, rewrite, evaluate, index, sort, filter, or use unknown values for business logic. Return them for display and tolerate their absence.

Reject any NUL character in a JSON object key at any depth. A NUL in a string value is allowed if BSON encoding accepts it. A nested `_id` is an unknown nested key and is allowed. Only listed top-level reserved fields are rejected.

Copy documents before passing them to the driver so driver-side mutation cannot alter caller-owned data. Catch BSON representability errors without changing values. Do not convert large integers to Decimal128, round values, or use `model_dump(mode="json")` for persistence. HTTP response serialization may use JSON mode.

### Schema version changes

Keep recognized and consumed field sets centralized in `mapping.py`. A future approved stored-shape change must increment `schema_version`. It must also define either a deliberate data backfill or a backward-reader contract before code lands. Do not add a migration framework or version dispatch now. Never reinterpret extras or rewrite legacy documents automatically.

## 6. JSON parsing and validation

Accept request bodies only when the media type is `application/json`, with an optional charset parameter. Return `415` for other media types.

The body must be one JSON object. Return `400` for malformed JSON, an empty body, arrays, scalars, or null. Map `RecursionError` from JSON parsing to `400`.

Configure JSON parsing to reject non-finite constants. Also recursively inspect the parsed value because a number such as `1e999` can become infinity without using a named `Infinity` token. Reject NaN and positive or negative infinity with `non_finite_number`.

Reject arbitrary JSON integers outside signed 64-bit range with `value_out_of_range`. Do not log the invalid value. BSON encoding failures for other unsupported representations use `invalid_field` or a more specific validation code where available.

Duplicate JSON object keys are not preserved. The parser keeps the last occurrence. The contract preserves parsed JSON semantics, not source whitespace, numeric spelling, key order guarantees, or duplicate-key history.

MongoDB permits no more than 100 BSON nesting levels. Count the final stored root document as level 1. Every contained object or array adds one level. Scalars add no level. The `metadata` or `details` container is level 2. An object or array held directly by one of its fields starts at level 3. Root `last_step_executed` and a non-null root `execution_outcome` start at level 2. Objects or arrays nested inside the outcome increment from there.

Use an iterative stack walk, not recursive application code, to compute depth. This avoids an application recursion failure during validation. A final level of 100 is accepted. A final level of 101 is rejected with `400 payload_too_deep`. Do not add a separate product limit such as 50 levels, a 256-character string cap, or an HTTP body cap.

For create requests, partition and validate the body, then construct the structural shape of the final stored envelope. Use scalar placeholders for the future ObjectIds and server timestamps because scalars do not change depth. Walk that shape before repository insertion.

For patch requests, validate each supplied known value at its actual root depth and each extra at its actual depth under `metadata`. No pre-read is needed. A one-level metadata merge replaces or adds top-level metadata values and cannot deepen retained values that were already validated. This rule does not permit read-modify-write.

Process requests in this order:

1. Verify media type.
2. Parse JSON with non-finite constant rejection. Map parser `RecursionError` to `invalid_json`.
3. Verify the root is an object.
4. Iteratively inspect the full raw object for NUL keys, non-finite numbers, and signed 64-bit integer range.
5. Reject endpoint-specific forbidden top-level fields.
6. On run creation, detect the `at` and `occurred_at` collision before model validation.
7. Pass the whole raw object to the endpoint's strict Pydantic model with `extra="allow"`.
8. Extract typed known values. Separately copy extras from the original parsed object by excluding the endpoint's consumed-key set.
9. Build the final structural envelope, or patch candidate values, and apply the exact depth rule.

Passing the whole body keeps `extra="allow"` meaningful. Never serialize the entire model as the persistence document. The mapper must retain a verbatim deep copy of every parsed extra. Consumed keys are removed from extras. For a run, both timestamp alias names belong to the consumed set. Supplying both still fails before mapping. Unknown keys inside `execution_outcome` are copied into the replacement outcome object, while known counts come from strict typed validation.

Known numeric and string fields are strict. Do not coerce numbers to strings, strings to integers, or booleans to integers.

If parsed text cannot be encoded as valid BSON UTF-8, return `400 invalid_field`. Do not replace invalid Unicode or silently drop it. NUL remains allowed in string values when BSON accepts it.

Timestamp validators must receive an RFC 3339 string with an explicit offset, such as `Z` or `+02:00`. Reject Unix numbers and naive timestamps. Parse to UTC and truncate to milliseconds. Serialize timestamps as RFC 3339 UTC strings with exactly milliseconds and a `Z` suffix:

```text
2026-10-01T09:07:04.000Z
```

## 7. Write endpoint contracts

### `POST /v1/sessions`

Request:

```json
{
  "started_at": "2026-10-01T09:07:04Z",
  "boundary": "example-service",
  "recorded_by": {
    "name": "Example agent",
    "email": "agent@example.invalid"
  },
  "invoked_by": {
    "name": "Example operator",
    "email": "operator@example.invalid"
  }
}
```

Response, `201 Created`:

```json
{
  "session_id": "68df8b00aef4d8537282f001"
}
```

Reject these top-level fields with `400 forbidden_field` before Pydantic:

```text
_id
session_id
received_at
schema_version
status
completion_time
last_step_executed
execution_outcome
```

Require `started_at` as an aware RFC 3339 string. All other top-level fields are extras under `metadata`.

Initialize server-owned root fields exactly as follows:

```json
{
  "status": "IN_PROGRESS",
  "completion_time": null,
  "last_step_executed": [],
  "execution_outcome": null
}
```

A legacy top-level `run_id` is not reserved. If supplied, store it as `metadata.run_id`. It has no lookup, identity, uniqueness, or deduplication meaning. Updated agents must omit legacy IDs and use the returned `session_id`.

### `POST /v1/sessions/{session_id}/runs`

Request to `POST /v1/sessions/68df8b00aef4d8537282f001/runs`:

```json
{
  "step": "pair-actions",
  "command": "actions-pairer",
  "verdict": "PASS",
  "at": "2026-10-01T09:17:58Z",
  "args": [
    "consumer-actions.json",
    "provider-actions.json"
  ]
}
```

Response, `201 Created`:

```json
{
  "run_id": "68df8b00aef4d8537282f002"
}
```

Reject these top-level fields with `400 forbidden_field` before Pydantic:

```text
_id
run_id
session_id
received_at
schema_version
```

Require nonempty strict strings for `step`, `command`, and `verdict`. Do not define an enum or an arbitrary maximum length for these fields.

Require exactly one of `at` or `occurred_at`. Both are aware RFC 3339 timestamp strings. If both appear, return `400 timestamp_conflict`, even when their values are equal. Promote the accepted value to stored `occurred_at` and remove the input name from extras.

All other fields, including `args`, go under `details`.

The parent session must exist. A malformed 24-character ObjectId path is treated like an unknown ID and returns `404 session_not_found`. Do not perform alternate ID lookup.

Run insertion is allowed after the parent is terminal. The agent should normally upload all runs before finishing the session, but the server does not freeze runs. There is no cross-collection transaction or invariant that promises a run and parent snapshot.

### `PATCH /v1/sessions/{session_id}`

Request to `PATCH /v1/sessions/68df8b00aef4d8537282f001`:

```json
{
  "status": "COMPLETED",
  "completion_time": "2026-10-01T09:18:04Z",
  "last_step_executed": [
    "pair-actions"
  ],
  "execution_outcome": {
    "defect_count": 2,
    "gap_count": 1,
    "contract_ingredient_count": 14
  }
}
```

Response, `200 OK`:

```json
{
  "session_id": "68df8b00aef4d8537282f001"
}
```

This is an open partial update. It succeeds only while the stored session status is `IN_PROGRESS`.

Reject these top-level fields with `400 forbidden_field` before Pydantic:

```text
_id
session_id
received_at
schema_version
```

Recognize and validate these root fields:

| Field | Rule |
| --- | --- |
| `started_at` | Mutable while open. Non-null aware RFC 3339 string. |
| `status` | Non-null. If supplied, only `COMPLETED` or `FAILED`. |
| `completion_time` | Aware RFC 3339 string or explicit null. |
| `last_step_executed` | Non-null list of strict step-name strings. Replace the whole list. |
| `execution_outcome` | Outcome object or explicit null. Replace the whole value. |

An outcome object has three optional strict signed 64-bit integer fields. Each supplied count must be nonnegative:

```text
defect_count
gap_count
contract_ingredient_count
```

Unknown outcome keys are preserved in that object. Do not deep-merge counts. Do not fill omitted counts with zero. Do not compute or cross-check counts against runs.

There is no required coupling between terminal status, `completion_time`, `last_step_executed`, and `execution_outcome`. A status-only terminal update is valid and may leave the time null and the outcome unknown. There is no automatic completion timestamp.

Omitted fields remain unchanged. Explicit null for a nullable field is stored as null. There is no payload operation that deletes a field. `last_step_executed` contains display names only. Do not check run existence, append to the existing list, or turn names into run links.

Unknown top-level fields are shallow-merged one level into `metadata`. Existing values with the same top-level metadata key are replaced. For example:

```json
{"invoked_by":{"name":"New name"}}
```

replaces an existing `metadata.invoked_by` object in full. An existing `email` inside that object is lost.

An empty object is a valid no-op only while the session is open. It still executes the guarded update. It returns `200` when the `_id` and open status match. The same payload returns `409 session_not_open` for a terminal session.

#### Required atomic update

The Mongo session repository must use one pipeline update. Do not use read-modify-write. Do not add replay detection, terminal reopening, an optimistic version, or another compare-and-set field.

Build known root assignments only from supplied known fields after `model_dump(exclude_unset=True)`. Keep Python datetime values. Wrap every known root value in `$literal`, including strings, datetimes, arrays, and objects.

Always include one metadata assignment, even when extras are empty:

```python
async def patch_open_session(session_id: str, known: dict, extras: dict) -> str:
    object_id = ObjectId(session_id)
    set_spec = {
        key: {"$literal": copy.deepcopy(value)}
        for key, value in known.items()
    }
    set_spec["metadata"] = {
        "$mergeObjects": [
            {"$ifNull": ["$metadata", {"$literal": {}}]},
            {"$literal": copy.deepcopy(extras)},
        ]
    }
    result = await collection.update_one(
        {"_id": object_id, "status": "IN_PROGRESS"},
        [{"$set": set_spec}],
        upsert=False,
    )
    if result.matched_count == 1:
        return session_id
    existing = await collection.find_one({"_id": object_id}, {"_id": 1})
    if existing is None:
        raise SessionNotFound()
    raise SessionNotOpen()
```

This snippet belongs in a repository adapter, where `ObjectId` is allowed. The implementation must validate malformed IDs before entering this function or map them to `SessionNotFound` in the adapter.

`matched_count`, not `modified_count`, determines success. An identical update still matched the guarded document. A zero match requires one ID-only lookup to distinguish `404` from `409`.

Wrapping whole values with `$literal` prevents input such as `"$status"` or `{"$set":{"x":1}}` from being evaluated as a MongoDB expression. Wrapping the whole extras object also preserves dotted and dollar-prefixed nested keys as data. `$mergeObjects` applies last-value-wins replacement at the top metadata level.

The filter makes the status guard atomic with root and metadata changes. Concurrent terminal patches can both validate, but only one may match the open document.

## 8. Read endpoint contracts

### `GET /v1/sessions`

Request:

```text
GET /v1/sessions
```

Response after the worked lifecycle above, `200 OK`:

```json
[
  {
    "session_id": "68df8b00aef4d8537282f001",
    "schema_version": 1,
    "started_at": "2026-10-01T09:07:04.000Z",
    "received_at": "2026-10-01T09:07:05.123Z",
    "status": "COMPLETED",
    "completion_time": "2026-10-01T09:18:04.000Z",
    "last_step_executed": [
      "pair-actions"
    ],
    "execution_outcome": {
      "defect_count": 2,
      "gap_count": 1,
      "contract_ingredient_count": 14
    },
    "metadata": {
      "boundary": "example-service",
      "recorded_by": {
        "name": "Example agent",
        "email": "agent@example.invalid"
      },
      "invoked_by": {
        "name": "Example operator",
        "email": "operator@example.invalid"
      }
    }
  }
]
```

An empty result is a `200 OK` response with this body:

```json
[]
```

There is no pagination, limit, continuation token, or truncation. Sort by `started_at` descending, then `_id` descending.

Each summary contains this root allowlist and no `runs` field:

```text
session_id
schema_version
started_at
received_at
status
completion_time
last_step_executed
execution_outcome
metadata
```

### `GET /v1/sessions/{session_id}`

Request:

```text
GET /v1/sessions/68df8b00aef4d8537282f001
```

Response after the worked lifecycle above, `200 OK`:

```json
{
  "session_id": "68df8b00aef4d8537282f001",
  "schema_version": 1,
  "started_at": "2026-10-01T09:07:04.000Z",
  "received_at": "2026-10-01T09:07:05.123Z",
  "status": "COMPLETED",
  "completion_time": "2026-10-01T09:18:04.000Z",
  "last_step_executed": [
    "pair-actions"
  ],
  "execution_outcome": {
    "defect_count": 2,
    "gap_count": 1,
    "contract_ingredient_count": 14
  },
  "metadata": {
    "boundary": "example-service",
    "recorded_by": {
      "name": "Example agent",
      "email": "agent@example.invalid"
    },
    "invoked_by": {
      "name": "Example operator",
      "email": "operator@example.invalid"
    }
  },
  "runs": [
    {
      "run_id": "68df8b00aef4d8537282f002",
      "session_id": "68df8b00aef4d8537282f001",
      "schema_version": 1,
      "step": "pair-actions",
      "command": "actions-pairer",
      "verdict": "PASS",
      "occurred_at": "2026-10-01T09:17:58.000Z",
      "received_at": "2026-10-01T09:17:59.456Z",
      "details": {
        "args": [
          "consumer-actions.json",
          "provider-actions.json"
        ]
      }
    }
  ]
}
```

Return `404 session_not_found` for an unknown or malformed ObjectId. Otherwise return the same session root allowlist plus `runs`. A session with no runs contains `"runs": []`.

Sort runs by `occurred_at` ascending, then `_id` ascending. Each run contains exactly:

```text
run_id
session_id
schema_version
step
command
verdict
occurred_at
received_at
details
```

Use two queries: one for the session and one for its runs. Do not use `$lookup` or materialize a joined BSON document. A joined document could hit the 16 MiB document limit.

The two reads are not a snapshot. A run can be inserted after the session query, after terminal completion, or after a detail response. This is deliberate.

Both read endpoints are unbounded. They can consume significant API, BFF, browser, and network memory. Do not add implicit limits or hide omitted results.

## 9. Errors and HTTP binding

Application exceptions live in `errors.py` and have no FastAPI imports. `exception_handlers.py` binds them to HTTP.

Every application API error uses one object:

```json
{
  "error": {
    "code": "invalid_field",
    "message": "A request field is invalid."
  }
}
```

Codes are stable lower snake case. Messages must be safe and specific enough to correct the request. Do not include secrets, raw invalid values, stack traces, MongoDB commands, or driver exception text.

Use these codes where applicable:

| Status | Code | Safe message | Use |
| --- | --- | --- | --- |
| 400 | `invalid_json` | `Request body is not valid JSON.` | Malformed JSON or parser recursion failure |
| 400 | `invalid_body` | `Request body must be a JSON object.` | JSON root is not an object |
| 400 | `forbidden_field` | `Request contains a reserved top-level field.` | Reserved top-level input field |
| 400 | `missing_field` | `A required field is missing.` | Required field absent |
| 400 | `invalid_field` | `A request field is invalid.` | Known field fails validation or BSON representation |
| 400 | `timestamp_conflict` | `Provide exactly one of at or occurred_at.` | Both run timestamp aliases supplied |
| 400 | `invalid_key` | `Object keys must not contain NUL.` | NUL found in an object key |
| 400 | `payload_too_deep` | `The stored document would exceed 100 nesting levels.` | Final BSON nesting would exceed 100 levels |
| 400 | `non_finite_number` | `Numbers must be finite.` | NaN or infinity found |
| 400 | `value_out_of_range` | `An integer is outside the supported range.` | Integer is outside signed 64-bit range |
| 404 | `route_not_found` | `Route not found.` | Framework route does not exist |
| 404 | `session_not_found` | `Session not found.` | Parent or requested session absent, including malformed ObjectId |
| 405 | `method_not_allowed` | `Method not allowed.` | Framework route exists but method is unsupported |
| 409 | `session_not_open` | `Session is not open for updates.` | Any valid patch targets a terminal session |
| 413 | `document_too_large` | `The stored document would exceed the MongoDB size limit.` | Insert or update exceeds final BSON document size |
| 415 | `unsupported_media_type` | `Content-Type must be application/json.` | Request media type is not JSON |
| 500 | `internal_error` | `The server could not complete the request.` | Sanitized unexpected server or database failure |
| 502 | `upstream_unavailable` | `The upstream API is unavailable.` | BFF transport failure, malformed JSON, or upstream `5xx` |
| 504 | `upstream_timeout` | `The upstream API timed out.` | BFF HTTPX timeout |

Override FastAPI `RequestValidationError` to `400`, mapped to a stable application envelope. Choose `missing_field` when the first deterministic validation issue is an absent required field. Use `invalid_field` for other model validation failures.

Rewrite `StarletteHTTPException` into the same envelope while preserving its status. Use distinct codes such as `route_not_found`, `method_not_allowed`, and `unsupported_media_type`. Preserve the `Allow` header on `405`. Do not turn every framework exception into `400`.

Representative errors:

`400 Bad Request`:

```json
{
  "error": {
    "code": "timestamp_conflict",
    "message": "Provide exactly one of at or occurred_at."
  }
}
```

`404 Not Found`:

```json
{
  "error": {
    "code": "session_not_found",
    "message": "Session not found."
  }
}
```

`409 Conflict`:

```json
{
  "error": {
    "code": "session_not_open",
    "message": "Session is not open for updates."
  }
}
```

`413 Content Too Large`:

```json
{
  "error": {
    "code": "document_too_large",
    "message": "The stored document would exceed the MongoDB size limit."
  }
}
```

`500 Internal Server Error`:

```json
{
  "error": {
    "code": "internal_error",
    "message": "The server could not complete the request."
  }
}
```

`502 Bad Gateway` from the BFF:

```json
{
  "error": {
    "code": "upstream_unavailable",
    "message": "The upstream API is unavailable."
  }
}
```

`504 Gateway Timeout` from the BFF:

```json
{
  "error": {
    "code": "upstream_timeout",
    "message": "The upstream API timed out."
  }
}
```

Catch MongoDB and BSON exceptions in this order:

1. `pymongo.errors.DocumentTooLarge` to `413 document_too_large`
2. `bson.errors.InvalidDocument` to `400 invalid_field`
3. `OperationFailure` or `WriteError` with pinned, integration-tested oversize codes `10334` or `17419` to `413 document_too_large`
4. Other database operation failures to sanitized `500 internal_error`

`DocumentTooLarge` is a subclass of `InvalidDocument`, so order is required. The server-side oversize code mapping is not assumed universal. Pin MongoDB and test both insertion and cumulative patch growth against that version.

Do not blanket-map MongoDB operation failures to `413`. An oversize update must be atomic and leave the previous document unchanged.

## 10. MongoDB indexes

After a successful startup ping, create only these indexes through `repositories/indexes.py`:

```python
sessions_started_desc_idx = [("started_at", -1), ("_id", -1)]
runs_session_occurred_idx = [("session_id", 1), ("occurred_at", 1), ("_id", 1)]
```

Create them idempotently with the exact names:

```text
sessions_started_desc_idx
runs_session_occurred_idx
```

MongoDB supplies the unique `_id` indexes. Do not add indexes on extras, agent IDs, status, or other fields. Do not add uniqueness for legacy IDs.

An index definition change requires a deliberate migration or a new name. Startup must not automatically drop or replace an existing index.

## 11. Web BFF and React application

Use separate Python packaging for the webserver so `api/app` and `web/server/app` do not collide on import paths:

```text
web/
  server/
    pyproject.toml
    app/
      __init__.py
      main.py
      config.py
      errors.py
      routes.py
    tests/
  frontend/
    package.json
    src/
    tests/
```

The webserver runs FastAPI and Uvicorn on container port 8080. Its lifespan creates one `httpx.AsyncClient` with this default configuration:

```text
base URL: http://api:8000
connect timeout: 5 seconds
read timeout: 30 seconds
write timeout: 30 seconds
pool timeout: 5 seconds
```

Close the client at shutdown. Register API and health routes before static assets and UI fallback routes.

Map BFF GET routes one-to-one:

```text
GET /ui/api/sessions              -> GET /v1/sessions
GET /ui/api/sessions/{session_id} -> GET /v1/sessions/{session_id}
```

Pass upstream JSON payloads through without changing response field names. Pass upstream `4xx` status and error envelope through. Map failures as follows:

| Failure | BFF result |
| --- | --- |
| `httpx.TimeoutException` | `504 upstream_timeout` |
| Connection or transport failure | `502 upstream_unavailable` |
| Upstream `5xx` | `502 upstream_unavailable` |
| Malformed upstream JSON | `502 upstream_unavailable` |

Use the same application envelope. A generic shape example is valid JSON:

```json
{
  "error": {
    "code": "upstream_unavailable",
    "message": "The upstream API is unavailable."
  }
}
```

Do not send browser credentials or tokens.

Accept an inbound `X-Request-ID` only if it is a canonical UUID string within a fixed small length. Otherwise generate a UUID. Propagate the selected value to the API and echo it in the response. Treat it as observability data, never identity. Bound it and prevent log injection.

Do not log raw request or response bodies, MongoDB URI values, passwords, or arbitrary field key names. Unknown keys and identity objects may contain personal data. Log the request ID, method, normalized route template, status, elapsed time, and safe exception category.

The React app provides:

- a session list
- a session detail view
- loading, empty, and error states
- UTC timestamp display
- read-only expandable JSON for `metadata` and each run's `details`

Render null counts as `unknown`, never `0`. Render unrecognized verdict strings as plain text. Render `last_step_executed` as names, not links. Show `recorded_by` and `invoked_by` separately when present, and tolerate either being absent.

Render all data as text. Do not use `dangerouslySetInnerHTML` for errors or stored JSON.

Serve `index.html` only for known UI GET paths:

```text
/
/sessions/{session_id}
```

An unknown BFF route returns `404`, not the SPA. A missing `/assets/*` resource returns `404`, not `index.html`. Any other unknown UI route returns `404`. The internal web health route is registered before fallback.

## 12. NGINX and composed deployment

Place these directives inside the port 80 `server` block in `nginx/nginx.conf`:

```nginx
client_max_body_size 0;

location = /healthz {
    return 404;
}

location /v1/ {
    proxy_pass http://api:8000;
    proxy_read_timeout 60s;
}

location / {
    proxy_pass http://web:8080;
    proxy_read_timeout 60s;
}
```

Keep the exact-match health block before the prefix locations. Preserve the full URI. In particular, do not strip `/v1` from API requests. The read timeout is an idle read timeout, not a hard request wall clock. A long trickle response can take longer than 60 seconds.

NGINX explicitly blocks the edge health path. A host request to `GET /healthz` matches `location = /healthz` and returns an NGINX `404` without proxying to the webserver. API and web health checks remain container-internal.

The API and webserver each expose an internal health endpoint. Request on the appropriate container port:

```text
GET /healthz
```

Response, `200 OK`:

```json
{
  "status": "ok"
}
```

These are process liveness checks. They do not query MongoDB and do not claim database readiness. A later database outage causes normal API requests to return sanitized `500` errors.

Use Python `urllib` for API and web container health checks so no extra command-line HTTP client is required:

```text
API: http://localhost:8000/healthz
web: http://localhost:8080/healthz
```

Use `mongosh` with root credentials for the MongoDB ping health check. Pass credentials without printing them in logs or process setup output where avoidable.

Compose requirements:

- `mongo` has a named volume and a health check.
- `api` depends on healthy `mongo`.
- `web` may start without API availability, but declare a health-aware API dependency for deterministic POC startup.
- `nginx` depends on healthy `api` and `web`.
- All services use `restart: unless-stopped`.
- `api`, `web`, and `mongo` may use `expose` but no host `ports`.
- Only `nginx` maps `0.0.0.0:8080:80`.

NGINX forwards standard proxy headers for observability. Forwarded headers are not trusted identity and do not change the security model.

The JSON error envelope is guaranteed for application API and BFF responses. NGINX-generated edge errors, including some `404`, `502`, and `504` responses, may be HTML. Do not claim a JSON envelope at the edge.

Do not add a 443 listener, TLS material, an HTTP redirect, a body cap, or an unauthenticated MongoDB URI fallback.

## 13. Configuration and credentials

Commit `.env.example` with placeholders. Ignore `.env`. Never commit actual secrets.

| Variable | Scope | Default | Purpose |
| --- | --- | --- | --- |
| `MONGO_URI` | API | Required, none | Credentialed application URI with `authSource` set to the application database |
| `MONGO_DB_NAME` | API and Mongo bootstrap | `quality_agent` | Application database and role target |
| `MONGO_APP_USERNAME` | Mongo bootstrap | Required, none | Application user name |
| `MONGO_APP_PASSWORD` | Mongo bootstrap | Required, none | Application user password |
| `MONGO_INITDB_ROOT_USERNAME` | Mongo bootstrap and health check | Required, none | First-start root user name |
| `MONGO_INITDB_ROOT_PASSWORD` | Mongo bootstrap and health check | Required, none | First-start root password |
| `API_BASE_URL` | web BFF | `http://api:8000` | Upstream API base URL |
| `HTTPX_CONNECT_TIMEOUT_SECONDS` | web BFF | `5` | BFF connect timeout |
| `HTTPX_READ_TIMEOUT_SECONDS` | web BFF | `30` | BFF read timeout |
| `HTTPX_WRITE_TIMEOUT_SECONDS` | web BFF | `30` | BFF write timeout |
| `HTTPX_POOL_TIMEOUT_SECONDS` | web BFF | `5` | BFF pool acquisition timeout |
| `LOG_LEVEL` | API and web | `INFO` | Application log level |
| `TEST_MONGO_URI` | API integration tests only | Required for integration tests, none | Privileged test-deployment URI whose default database is exactly `quality_agent_test` and whose `authSource` is `admin` |
| `TEST_MONGO_BASE_DB_NAME` | API integration tests only | `quality_agent_test` | Fixed base used to create one isolated fixture database named `quality_agent_test_<uuid4hex>` |

Keep NGINX `proxy_read_timeout 60s` and MongoDB client timing in static configuration. Use a 5-second server selection timeout and sensible 30-second socket timing. Do not expose every internal setting as an environment variable.

The frontend base URL is relative and needs no environment variable. Never put secrets in Vite variables because the bundle is visible to the browser.

MongoDB authentication is distinct from HTTP authentication. Use the maintained MongoDB 8.0 release for the POC. MongoDB 5 or newer is required for the approved special-key behavior, but the pinned integration target is MongoDB 8.0.

Use `MONGO_INITDB_ROOT_USERNAME` and `MONGO_INITDB_ROOT_PASSWORD` only for MongoDB bootstrap and its authenticated health check. A `mongo/init-app-user.js` script must read `MONGO_APP_USERNAME`, `MONGO_APP_PASSWORD`, and `MONGO_DB_NAME` from the process environment. It switches to the application database and calls `db.createUser` with a `readWrite` role scoped to that database. Pass values as JavaScript variables. Do not interpolate shell text into JavaScript source.

URL-encode the application username and password when constructing `MONGO_URI`. The API URI must authenticate against the application database. Never log the URI or its credentials.

MongoDB initialization scripts run only when the data directory is first initialized. Editing `.env` does not rotate a user in an existing named volume. Document an explicit credential rotation procedure if one is later needed. Do not suggest `docker compose down -v` as a normal fix because it destroys stored data.

`TEST_MONGO_URI` belongs only to tests. It uses a separately provisioned privileged test user on a test MongoDB deployment. That user authenticates against `admin` and may create and drop isolated test databases. Do not grant those privileges to the runtime application user. Do not use the runtime application database for integration tests.

## 14. Tests and verification

The primary API integration suite uses pytest against a real pinned MongoDB instance and an isolated test database. Mark these tests `integration`.

The fixture requires `TEST_MONGO_URI`. Its URI default database must be exactly `quality_agent_test`, its `authSource` must be `admin`, and the URI must not equal runtime `MONGO_URI`. `TEST_MONGO_BASE_DB_NAME` must equal the fixed value `quality_agent_test`. The fixture appends an underscore and a new lowercase UUID4 hexadecimal value, producing a database name that matches `^quality_agent_test_[0-9a-f]{32}$`.

The fixture records the one database name it created. Cleanup may drop only that recorded name and only when it matches the guard expression. It never drops `MONGO_DB_NAME`, the URI default database, a user-supplied database name, or any database it did not create. Tests override API settings with the generated test database and `TEST_MONGO_URI`.

If integration tests are explicitly selected without `TEST_MONGO_URI`, fail with a clear configuration error. Pure unit tests run without MongoDB through `pytest -m 'not integration'`. A test deployment or the compose test overlay must provision the privileged test user. Do not publish the application MongoDB service port only to support tests.

Use pure unit tests for mapping and validation. Use small protocol fakes for service branches where useful. Do not build a large third test tier that reproduces MongoDB behavior in memory.

### API tests

Cover at least these cases:

- POST endpoints generate server ObjectIds and never accept reserved root IDs.
- Nested `_id` remains allowed as unknown data.
- Dotted keys, dollar-prefixed keys, arrays, nulls, literal `"$status"`, and operator-shaped objects round-trip under `metadata` or `details` without expression evaluation.
- A flat input `metadata` becomes `metadata.metadata`; a flat input `details` becomes `details.details`.
- Timestamps are real BSON datetimes, timezone-aware on mapping, normalized to UTC, and serialized with milliseconds.
- Missing and explicit null remain distinct on patch.
- `at` and `occurred_at` together return `timestamp_conflict`.
- Empty patch returns `200` through `matched_count == 1`, even when `modified_count == 0`.
- Omitted patch fields remain unchanged.
- `invoked_by` replacement is exactly one-level shallow and loses omitted nested keys.
- Step arrays replace the whole prior array.
- Outcomes store only supplied values and preserved unknown keys. They never aggregate runs or impute zeros.
- Known and unknown patch updates occur atomically.
- Two concurrent terminal patches produce one `200` and one `409`.
- Any valid patch, including `{}`, returns `409` once the session is terminal.
- Malformed session IDs return `404`.
- A real oversize insert returns `413`.
- Cumulative metadata growth by patch returns `413` and leaves the prior document unchanged.
- Non-finite numbers, huge integers, NUL keys, parse recursion, and final depth over 100 return `400` with the intended code.
- Session lists are unbounded and send no hidden pagination query.
- Detail reads use separate queries and make no snapshot claim.
- Late run insertion into a terminal session succeeds.

The MongoDB integration suite pins these behaviors against the chosen image and PyMongo lock:

- insert oversize maps to `413`
- cumulative patch oversize maps to `413` with no partial change
- empty patch returns `200` based on `matched_count`
- server-side oversize codes used by the pinned MongoDB version map correctly

### BFF tests

Mock HTTPX at the transport boundary. Cover exact upstream paths, `4xx` passthrough, `5xx` mapping, connection failure, malformed JSON, timeout mapping, request ID validation and propagation, and one client per lifespan with shutdown close.

### UI tests

Use Vitest and the React testing library. Cover loading, empty, and error states; unknown count rendering; UTC timestamps; unrecognized verdict text; missing identity values; expandable metadata and details; HTML-like stored text escaping; and the absence of direct browser calls to `/v1`.

### Composed smoke tests

Run HTTP smoke tests through NGINX. Verify `/v1` routing, known UI routes, unknown route behavior, missing assets, public host binding, and that API and web health routes are internal while edge `/healthz` is `404`.

Do not set an arbitrary coverage percentage. No live MongoDB tests or application tests were run because the application code is not implemented. Do not claim tests passed until they have run in the implementation environment.

## 15. Build, run, and implementation sequence

These are command contracts to create during implementation. They have not been executed yet.

Default composed workflow from the repository root:

```bash
docker compose build
docker compose up -d --wait
```

The default runtime images must not include developer reload. They may omit test dependencies. `docker-compose.test.yml` defines the explicit development image target, a test MongoDB deployment or connection, and test-only credentials. Once implemented, run integration tests on its internal network without publishing MongoDB to the host:

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm api python -m pytest
```

Local API unit test workflow:

```bash
python3.12 -m venv api/.venv
api/.venv/bin/python -m pip install -e 'api[dev]'
cd api
.venv/bin/python -m pytest -m 'not integration'
```

Local API integration test workflow requires a separately provisioned test MongoDB user. Replace every uppercase placeholder and percent-encode its credentials:

```bash
export TEST_MONGO_URI='mongodb://TEST_USER:TEST_PASSWORD@TEST_HOST:27017/quality_agent_test?authSource=admin'
export TEST_MONGO_BASE_DB_NAME='quality_agent_test'
cd api
.venv/bin/python -m pytest -m integration
```

Local BFF test workflow uses a separate environment to avoid the two `app` packages colliding:

```bash
python3.12 -m venv web/server/.venv
web/server/.venv/bin/python -m pip install -e 'web/server[dev]'
cd web/server
.venv/bin/python -m pytest
```

Frontend workflow:

```bash
cd web/frontend
npm ci
npm test
npm run build
```

Define `npm test` as the nonwatch command `vitest run`. Pin a Vite-compatible Node 22 builder image and commit `package-lock.json`. `requirements.txt` at the repository root remains prose and must never be passed to `pip`.

After the composed application and `scripts/smoke.py` exist, run the root smoke command:

```bash
python scripts/smoke.py --base-url http://localhost:8080
```

Implement in small, reversible stages:

1. Add API packaging, configuration, parsing, schemas, mapping, and unit tests.
2. Add MongoDB repositories, indexes, lifespan, and real-Mongo integration tests.
3. Add controllers and endpoint tests through FastAPI.
4. Add the Python BFF, route tests, and request correlation.
5. Add the React list and detail views with Vitest coverage.
6. Add Mongo initialization, container builds, compose wiring, NGINX, and HTTP smoke tests.
7. Run the complete pinned test set and record the versions actually verified.

Keep tests with each stage. Do not defer validation, repository, or routing tests until the end. Roll back code and configuration changes without deleting the MongoDB named volume or user data.

## 16. Practical SOLID rules

- Give controllers, services, mapping, and repository adapters one clear reason to change.
- Add behavior through the narrow seam that owns it. Do not force every change through a generic base class.
- Keep protocol implementations substitutable by specifying return values and application errors, not MongoDB mechanics.
- Split protocols when a consumer needs only a smaller operation set.
- Make services depend on protocols and construct concrete adapters at the application edge.

These are design checks, not a ban on editing an existing file. Prefer the smallest coherent change over extra abstraction.

## 17. References

- [MongoDB `$literal`](https://www.mongodb.com/docs/manual/reference/operator/aggregation/literal/)
- [MongoDB `$mergeObjects`](https://www.mongodb.com/docs/manual/reference/operator/aggregation/mergeObjects/)
- [MongoDB updates with an aggregation pipeline](https://www.mongodb.com/docs/manual/tutorial/update-documents-with-aggregation-pipeline/)
- [PyMongo update result counts](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/update/)
- [MongoDB field names with periods and dollar signs](https://www.mongodb.com/docs/manual/core/dot-dollar-considerations/)
- [MongoDB BSON document size](https://www.mongodb.com/docs/manual/core/document/)
- [MongoDB nesting limit](https://www.mongodb.com/docs/v8.2/reference/limits/)
- [PyMongo errors](https://pymongo.readthedocs.io/en/stable/api/pymongo/errors.html)
- [PyMongo async migration reference](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/)
- [Motor deprecation notice](https://www.mongodb.com/docs/drivers/motor/)

Use PyMongo Async, not deprecated Motor. Check the pinned library documentation while implementing details that depend on an exact driver release.
