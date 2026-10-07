# Quality agent POC design

## 1. Purpose and authority

This document is the executable specification for coding agents that build the quality agent proof of concept. Implement the behavior stated here. Do not infer missing behavior from nearby files.

The living POC architecture diagram is `docs/architecture/quality-agent-architecture.drawio`. Keep its routes, flows, and deployment descriptions aligned with this document. Mark specified but unimplemented routes and flows as planned. Production-direction notes must be labelled as outside the POC, not as implemented behavior.

Earlier design notes referenced `requirements.txt`, `run.json`, `Mongo Schema.txt`, and `noc-agent.drawio`. Those files are not present in this repository and are not implementation sources.

This document defines the target POC contract and takes precedence over the diagram and implementation. The presence of a file or scaffold in the worktree does not establish that it conforms to this contract.

Build toward this complete repository shape. Files listed here are planned outputs, not current implementation claims:

```text
.env.example
.gitignore
AGENTS.md
DESIGN.md
docker-compose.yml
docker-compose.test.yml
docs/
  architecture/
    quality-agent-architecture.drawio
  deployment.md
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
      session_listing.py
      mapping.py
    repositories/
      __init__.py
      protocols.py
      mongo_runtime.py
      mongo_read_errors.py
      mongo_session_repository.py
      mongo_run_repository.py
      object_ids.py
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
      errors.py
      routes.py
    tests/
    image_tests/
      test_bundle.py
  frontend/
    package.json
    package-lock.json
    index.html
    tsconfig.json
    vite.config.ts
    src/
      main.tsx
      App.tsx
      SessionList.tsx
      SessionDetail.tsx
      SessionFilters.tsx
      sessionColumns.tsx
      sessionQuery.ts
      JsonBlock.tsx
      ReadNotice.tsx
      useApiRead.ts
      api.ts
      types.ts
      json.ts
      core-js-json.d.ts
      format.ts
      styles.css
    tests/
nginx/
  nginx.conf
mongo/
  init-app-user.js
scripts/
  smoke.py
  tests/
    test_smoke.py
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
- List sessions as filtered, cursor-paginated pages, and return one session with its runs.
- Render session lists and details in a client-side React application.
- Serve the built React application from a Python FastAPI webserver.
- Let React call the API directly through NGINX with same-origin relative URLs.
- Route public traffic through NGINX.
- Supply automated tests for validation, persistence, concurrency, the static webserver, the UI, and the composed HTTP path.

Do not add the following:

- HTTP authentication, authorization, tokens, TLS, certificates, or HTTPS redirects
- request body size caps in NGINX or either FastAPI application
- CORS middleware as a security control
- server-side rendering
- free-text search, filtering on arbitrary metadata paths, silent truncation, or implicit result limits (the named list filters and explicit cursor pagination in section 8 are required)
- offset or page-number pagination, jumping to an arbitrary page, or snapshot claims across page reads
- retries, queues, sweepers, caches, Redis, or cross-collection transactions
- idempotency keys, replay deduplication, optimistic counters, or alternate ID lookup
- `PUT`, delete endpoints, generic CRUD bases, an ODM, Motor, or a separate business or domain layer
- a dependency injection container, provider auto-registration, or speculative extension folders
- automatic computation or verification of outcome counts

The API is intentionally unauthenticated. Any host that can reach port 8080 can read and write `/v1/*`. Unlimited request and response bodies can consume application memory, network capacity, and disk. Session detail responses remain unbounded in the size of one session and its runs. List pages are bounded by the page size, but an unauthenticated caller can still walk every page and can request a case-insensitive substring filter that the server evaluates without a supporting index. Do not reduce these risks by changing the approved POC contract. Document them in deployment instructions and keep production use out of scope.

MongoDB still limits each final BSON document to 16 MiB. A session `PATCH` can cross this limit as metadata grows. Return `413` when that happens.

## 3. Architecture and request flow

The request paths are:

```text
quality agent -> NGINX /v1/* -> API -> MongoDB
browser -> NGINX /* -> web -> built React HTML, JavaScript, and CSS
React in browser -> NGINX /v1/* -> API -> MongoDB
```

React fetches only these relative API paths:

```text
/v1/sessions
/v1/sessions/{session_id}
```

List requests may append repeated `fields` query parameters and the single-valued filter and paging parameters defined in section 8. Selection, filtering, and paging use the query string, not a GET request body.

NGINX sends `/v1/*` to the API on container port 8000. It sends UI and asset requests to the web container on port 8080. The web container serves static React assets and its internal liveness route only. It does not call the API or MongoDB.

The UI and API share the NGINX origin, so browser reads require no CORS configuration. The absence of CORS is not a security control. The unauthenticated `/v1/*` endpoints are public to every host that can reach NGINX.

Direct browser calls are the smaller POC design because the UI needs no server-held API credentials, response aggregation, or view-model transformation. Do not add a BFF, server rendering, or `/ui/api/*` data routes. Do not use the Docker hostname `api`, hardcode its internal port, or introduce `API_BASE_URL` in browser code.

React renders JSON in the browser. There is no SSR. Node 22 is used only in a multistage image build for the Vite bundle. The final `web` image runs Python, FastAPI, and Uvicorn. It contains the built static assets but no Node runtime.

`web/Dockerfile` builds the frontend with a digest-pinned Node 22 image using `npm ci`, `npm test`, and `npm run build`. Copy only the resulting `dist/` into `/app/static` in the Python runtime stage. Keep the Compose build target named `runtime`. Host `frontend/dist`, `node_modules`, and environment files are excluded from the build context; a local frontend build is neither required nor used for image packaging. The build must fail if frontend verification fails or the resulting index/assets directory is missing.

### Differences from the original production proposal

| Topic | Original production proposal | POC contract |
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

These comparisons are historical context, not claims about the current diagram. The living POC diagram follows this contract, including direct React-to-API reads through NGINX and HTTP without authentication. It distinguishes the four implemented `/v1` routes from the planned run-creation route. The target remains five `/v1` endpoints; section 15 records the remaining implementation work.

## 4. API code structure and dependency direction

Use Python 3.12, FastAPI, Pydantic v2, Uvicorn, and the official PyMongo `AsyncMongoClient`. Use PyMongo `>=4.15,<5` initially, then lock an exact compatible version during implementation. Lock exact compatible versions for FastAPI, Pydantic v2, and Uvicorn as part of implementation. HTTPX is allowed as a test dependency for in-process ASGI tests. Neither runtime application uses it to call another service. Do not claim compatibility until the lock and tests exist.

Use these dependencies:

```text
controllers -> services -> repository protocols
repositories -> PyMongo and BSON
main/dependencies -> concrete construction
exception_handlers -> FastAPI and application exceptions
```

Controllers own HTTP routing and translate validated inputs into service calls. Services own business rules and depend on narrow repository protocols. Repository adapters own persistence details. `domain.py` contains only shared enums, currently session status. Do not create a separate domain or business package.

`ObjectId`, `bson`, MongoDB clients, cursors, filters, update operators, and pipeline syntax must stay in repository adapter files. `indexes.py` may contain MongoDB index definitions. Repository protocols may use primitive ID strings, dictionaries used as DTOs, frozen dataclasses whose fields are primitives or other such dataclasses, and timezone-aware `datetime` values. They must not expose MongoDB clients, filters, cursors, projections, query operators, or BSON IDs.

Repository identifier arguments are strings. An adapter must confirm that an identifier is a string before converting it, because `ObjectId(None)` generates a new identifier instead of failing and would silently target an unrelated document. `ObjectId` also accepts 12-byte values and existing `ObjectId` instances, which the string identifier contract does not allow. Keep this one conversion helper in `repositories/object_ids.py` and use it for every identifier the adapters parse. Treat any non-string value, including `None`, exactly like a malformed identifier string: session reads return no record, and session patch and run listing raise `session_not_found`. Reject the value before issuing any MongoDB operation.

The protocols are real test seams. They let service tests use small fakes without importing MongoDB. Keep each protocol limited to operations the service currently needs. Do not introduce generic repositories. Define these exact operations in `protocols.py`:

```python
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, TypeAlias

SessionRecord: TypeAlias = dict[str, Any]
RunRecord: TypeAlias = dict[str, Any]

PageDirection: TypeAlias = Literal["next", "previous"]

@dataclass(frozen=True, slots=True)
class SessionFilters:
    status: str | None = None
    started_from: datetime | None = None
    started_before: datetime | None = None
    boundary_contains: str | None = None
    invoked_by_email: str | None = None

@dataclass(frozen=True, slots=True)
class PagePosition:
    started_at: datetime
    session_id: str
    direction: PageDirection

@dataclass(frozen=True, slots=True)
class SessionListQuery:
    fields: tuple[str, ...]
    page_size: int
    filters: SessionFilters = field(default_factory=SessionFilters)
    position: PagePosition | None = None

@dataclass(frozen=True, slots=True)
class PageAnchor:
    started_at: datetime
    session_id: str

@dataclass(frozen=True, slots=True)
class SessionPage:
    items: list[SessionRecord]
    total_count: int
    newest: PageAnchor | None = None
    oldest: PageAnchor | None = None
    has_newer: bool = False
    has_older: bool = False

class SessionRepository(Protocol):
    async def create(self, values: Mapping[str, Any]) -> str: ...
    async def exists(self, session_id: str) -> bool: ...
    async def get(self, session_id: str) -> SessionRecord | None: ...
    async def list_page(self, query: SessionListQuery) -> SessionPage: ...
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

The record dictionaries are application DTOs. Their IDs are strings and their timestamps are Python datetimes. They never contain ObjectIds, clients, cursors, filters, or MongoDB operators. `SessionFilters` text values are literal search values, never patterns or expressions; the adapter escapes them.

`PageAnchor` reports the sort key of a returned record separately from the record itself, because the sort key is not necessarily a selected response field. `has_newer` and `has_older` report only whether a further page exists in each direction at read time.

For list reads, the service validates every query parameter before calling `list_page`. It resolves the default fields or normalizes supplied field paths, normalizes filters into `SessionFilters`, resolves the page size, and decodes any supplied cursor into a `PagePosition`. The `fields` tuple contains application field paths, not a database projection, and always includes `session_id`. Only the adapter maps this ID to `_id`, constructs the inclusion projection, and builds filter, boundary, and sort expressions.

Use this call mapping:

| Router operation | Service operation | Repository operations |
| --- | --- | --- |
| Create session | `SessionService.create_session` | `SessionRepository.create` |
| Create run | `RunService.create_run` | `SessionRepository.exists`, then `RunRepository.create` |
| Patch session | `SessionService.patch_session` | `SessionRepository.patch_open_session` |
| List sessions | `SessionService.list_sessions` | `SessionRepository.list_page` |
| Get session detail | `SessionService.get_session` | `SessionRepository.get`, then `RunRepository.list_for_session` |

Services and `mapping.py` validate and partition values. `session_listing.py` owns list query validation, page size resolution, the cursor codec, and the result envelope assembly; it holds no MongoDB syntax. Services set `schema_version`, initial status fields, and `received_at`. `RunService.create_run` checks parent existence before insertion, regardless of parent status. Repositories generate ObjectIds, copy inputs, issue database operations, build filter, boundary, and sort expressions, escape literal filter text, and map stored BSON to application DTOs. Do not duplicate business checks in adapters.

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

Write concern is deployment configuration, not application code. Collections inherit the client and database write concern that `MONGO_URI` and the server supply. Do not hardcode a write concern on a collection, because that silently discards a configured durability or journaling setting. Writes must be acknowledged: the create path returns a server-generated identifier and the patch path decides `404`, `409`, and success from `matched_count`, neither of which an unacknowledged write reports. Startup must therefore reject an unacknowledged write concern, such as `w=0`, before the ping and index step, close the client, and fail with a nonzero process exit. Keep that startup message fixed and free of URI or credential text. Do not add a write-concern environment variable.

`dependencies.py` contains plain FastAPI providers. Lifespan stores the initialized repository objects on `app.state`. Providers read those repositories and construct lightweight services. They do not expose a database handle to services and do not create a client per request.

`main.py` exposes an application factory and a lifespan context. Lifespan must:

1. Call the repository adapter factory once for the event loop. Never create resources at import time.
2. Let that factory reject an unacknowledged write concern, ping MongoDB, and create the exact indexes in section 10.
3. Store initialized repository objects on `app.state`.
4. Await the adapter close operation during shutdown.

Startup must fail with a nonzero process exit if the write concern is unacknowledged or if ping or index creation fails. Do not use developer reload in containers. Run one Uvicorn worker by default. A compose startup gate does not guarantee later availability.

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

Unknown nested values may contain objects, arrays, dots in key names, dollar-prefixed key names, nulls, numbers, booleans, and strings. Preserve the parsed structure at every depth. Never flatten, rewrite, evaluate, index, sort, use unknown values to filter records, or use them for business logic. List field selection may retrieve subtrees for display without changing stored data. Return selected values in their nested structure and tolerate their absence.

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

Require `started_at` as an aware RFC 3339 string. The root session `started_at` is set only during session creation. All other top-level fields are extras under `metadata`.

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
started_at
received_at
schema_version
```

`started_at` is creation-only. Reject every patch that contains it at the top level, including an identical value, null, or a malformed timestamp. The raw JSON value checks in section 6, including NUL keys, non-finite numbers, signed 64-bit integer range, and UTF-8 validity, still run first. If those checks pass, return `400 forbidden_field` before Pydantic validation, value partitioning, or any repository operation. Reject the entire patch, including any otherwise valid fields in the same body. Do not read the session first.

A nested `started_at` remains unknown data. For example, `{"metadata":{"started_at":"value"}}` treats the top-level `metadata` name as an ordinary extra and stores the object at `metadata.metadata`. It does not target the root field.

Recognize and validate these root fields:

| Field | Rule |
| --- | --- |
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

This snippet belongs in a repository adapter, where `ObjectId` is allowed. The implementation must validate malformed IDs before entering this function or map them to `SessionNotFound` in the adapter. The real adapter also rejects a non-string identifier through the shared helper in section 4 before constructing the filter, so `ObjectId(None)` can never generate an identifier here.

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
{
  "items": [
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
      }
    }
  ],
  "page_size": 25,
  "total_count": 1,
  "next_cursor": null,
  "previous_cursor": null
}
```

An empty result is a `200 OK` response with this body:

```json
{
  "items": [],
  "page_size": 25,
  "total_count": 0,
  "next_cursor": null,
  "previous_cursor": null
}
```

Every list response is this envelope. It has exactly these five fields and no others. `items` is the page, in `started_at` descending then `_id` descending order. This replaces the previous unpaginated array response; a client that expects a bare JSON array must be updated.

Sort by `started_at` descending, then `_id` descending, always. There is no client-selectable sort field or direction.

With no `fields` parameter, each item contains only this root allowlist. Exclude both `metadata` and `runs`:

```text
session_id
schema_version
started_at
received_at
status
completion_time
last_step_executed
execution_outcome
```

Use this allowlist as the default MongoDB projection so unqualified list requests do not load metadata.

#### Optional field selection

Repeat the `fields` query parameter to select response paths. Do not use a GET body or a comma-separated field list:

```text
GET /v1/sessions?fields=started_at&fields=status&fields=metadata.invoked_by.email&fields=metadata.boundary
```

Example response, `200 OK`:

```json
{
  "items": [
    {
      "session_id": "68df8b00aef4d8537282f001",
      "started_at": "2026-10-01T09:07:04.000Z",
      "status": "COMPLETED",
      "metadata": {
        "invoked_by": {"email": "operator@example.invalid"},
        "boundary": "example-service"
      }
    }
  ],
  "page_size": 25,
  "total_count": 1,
  "next_cursor": null,
  "previous_cursor": null
}
```

- Always return `session_id`, including for `?fields=session_id`, which returns ID-only records.
- Select any root field in the default allowlist, `metadata`, or a nested path below `metadata` or `execution_outcome`. Never select `runs` on the list endpoint.
- Selecting a parent returns its complete subtree without coercing values or dropping arbitrary keys. Dots in a selector denote nesting. To retrieve a key containing a literal dot or a dollar prefix, select its parent instead.
- Reject unknown roots, descendants of non-container root fields, empty selectors or path components, NUL, invalid UTF-8, and dollar-prefixed path components with `400 invalid_field`. Validate all selectors before deduplication or collapsing parent/child overlaps; a valid parent must not conceal an invalid child.
- Deduplicate paths and collapse descendants when their parent is selected. The response contains no unrequested root fields other than the mandatory ID. Do not add application defaults for omitted fields. Preserve empty objects already returned by the database projection, such as `metadata: {}` when a selected leaf is absent.
- Use MongoDB's nested inclusion-projection semantics for arrays and missing or non-object intermediate values; do not implement a second projection engine in application code. A missing selected leaf is not synthesized. A selected value that is explicitly null stays null.
- Selection changes neither membership nor ordering. The same filtered set is returned in the same `started_at` descending, `_id` descending order, even when the sort fields are not selected.
- Always project the sort key so a cursor can be minted, and remove it from the returned record when it was not selected. An ID-only page must not leak `started_at`.
- Validate and serialize only the fields present in a projected response. Present non-nullable root fields remain strict and non-nullable. Serialize selected root timestamps with exactly milliseconds and `Z`, as in the default response. Keep default-summary and full-detail validation strict and independent.

Keep the full detail projection fixed and separate from request-specific list projections. Do not inherit nested selections into the detail projection: selecting both `metadata` and one of its descendants can cause a database path collision. Field selection changes only reads and responses, not the stored shape, indexes, or `schema_version`.

Selecting full `metadata` substantially increases memory use and response size for each page. The page size bounds one response but not the number of pages a caller may walk. The existing unauthenticated-access risk still applies; do not introduce hidden limits to compensate.

#### Filtering

Every filter is a single-valued query parameter. Repeating one is a request error, not a set of alternatives. Supplied filters combine conjunctively.

| Parameter | Rule |
| --- | --- |
| `status` | Exactly `IN_PROGRESS`, `COMPLETED`, or `FAILED`. |
| `started_from` | Aware RFC 3339 string. Matches `started_at` greater than or equal to it. |
| `started_before` | Aware RFC 3339 string. Matches `started_at` strictly less than it. |
| `boundary` | Literal text. Matches `metadata.boundary` containing it, ignoring case. |
| `invoked_by_email` | Literal text. Matches `metadata.invoked_by.email` exactly, including case. |

Validation rules:

- Reject an unknown status value, an unparseable timestamp, empty filter text, NUL, invalid UTF-8, and filter text longer than 256 characters with `400 invalid_field`. The bound keeps an oversized value a request error rather than a database expression limit. It applies only to these query parameters and does not cap any stored value.
- The timestamp range is start-inclusive and end-exclusive so adjacent windows neither overlap nor skip. Reject a supplied `started_from` that is greater than or equal to a supplied `started_before`.
- Either timestamp bound may be supplied alone. Normalize both to UTC milliseconds using the same parser as request bodies.
- Reject any unknown query parameter with `400 invalid_field`. Do not ignore it. A misspelled filter must not silently return a wider page.
- Validate every filter in the service before any repository call.

Metadata filter semantics:

- `boundary` and `invoked_by_email` are the only metadata paths that may be filtered. Do not add filtering on other metadata paths, on arbitrary client-supplied paths, or on `execution_outcome`.
- Filter text is a literal value, never a pattern. The adapter escapes it before building any regular expression, so `.`, `*`, and `$` match themselves.
- A supplied text filter matches only a genuine scalar string at the path. A missing value, null, number, object, or array never matches. MongoDB would otherwise match an array element through ordinary path traversal, so the adapter additionally requires a non-array value at `metadata.boundary`, at `metadata.invoked_by`, and at `metadata.invoked_by.email`.
- Filtering reads stored values; it does not evaluate, index, rewrite, or reinterpret them. Supplying a filter value such as `$status` matches that literal text. Filtering does not change the stored shape or `schema_version`.

#### Pagination

Paging is cursor-based and always on. Navigation is next and previous only; there is no page number, offset, or jump to an arbitrary page.

| Parameter | Rule |
| --- | --- |
| `page_size` | Integer from 1 through 100. Defaults to 25. Strict digits only; reject padding, signs, separators, and decimals. |
| `cursor` | An opaque continuation value returned by a previous response. |

```text
GET /v1/sessions?status=COMPLETED&boundary=payments&page_size=25
GET /v1/sessions?status=COMPLETED&boundary=payments&page_size=25&cursor=djF8bmV4dHwx
```

- `items` contains at most `page_size` records.
- `page_size` echoes the effective page size.
- `total_count` is the exact number of records matching the filters, independent of the cursor and the returned page. It comes from a separate count read, so the count and the page can disagree while sessions are being written. This is not a snapshot.
- `next_cursor` continues toward older sessions. `previous_cursor` returns toward newer sessions. Either is null when no further page exists in that direction at read time.
- The page boundary is the `(started_at, _id)` sort key of the first or last returned record and is exclusive. Read one record beyond the page size to decide whether the travelled direction continues. Determine the opposite direction with its own existence check rather than assuming it, because the anchored record may no longer match the filters.
- Reading backward sorts ascending from the boundary and then restores the response to newest-first order.
- A cursor is a continuation value, not a credential. It is not signed and carries no secret. It encodes a version, the direction, the boundary sort key, and a fingerprint of the filters and page size. Reject a cursor with an unexpected alphabet, length, structure, version, direction, or identifier shape, and reject one whose fingerprint does not match the current request, all with `400 invalid_field`. Validate the cursor before issuing any database operation. A different `fields` selection is allowed with the same cursor because selection changes neither membership nor ordering.
- The `(started_at, _id)` sort key does not change after creation. Editing a value used by a filter can change membership between page reads. A forward traversal can omit a session that leaves the result set or begins matching after its tuple has already been passed. It cannot repeat an already returned tuple because page boundaries are exclusive. Accept this live, non-snapshot behavior; do not add snapshots, server-side cursor state, or compensating locks.
- A valid cursor whose remaining matches have disappeared returns an empty `items` array, both cursors null, and the current `total_count`. Do not return `404` and do not silently restart from the first page.

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

Return `404 session_not_found` for an unknown or malformed ObjectId. Otherwise return the same session root allowlist plus `metadata` and `runs`. A session with no runs contains `"runs": []`.

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

The detail endpoint is unbounded in the size of one session and its runs. It has no pagination, field selection, or implicit limit. It can consume significant API, browser, and network memory. Do not add implicit limits or hide omitted runs.

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
| 400 | `invalid_field` | `A request field is invalid.` | Known field fails validation or BSON representation, or a list query parameter is unknown, repeated, or invalid |
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

Override FastAPI `RequestValidationError` to `400`, mapped to a stable application envelope. Choose `missing_field` when the first deterministic validation issue is an absent required field. Use `invalid_field` for other model validation failures.

List query parameters reuse `invalid_field`. Do not add a separate code for an invalid filter, page size, or cursor, and never echo the supplied value or say which parameter failed in a way that reflects input text back to the caller.

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

`sessions_started_desc_idx` also serves list pagination: it covers the sort order and the `(started_at, _id)` boundary comparison. List filters are deliberately unindexed. At the POC scale of fewer than ten thousand sessions a filtered page is a scan over the sorted index, and a case-insensitive substring filter could not use an ordinary index anyway. Measure representative queries before proposing a new index, and treat any addition as a deliberate index change under the rule below.

An index definition change requires a deliberate migration or a new name. Startup must not automatically drop or replace an existing index.

## 11. Static web server and React application

Use separate Python packaging for the webserver so `api/app` and `web/server/app` do not collide on import paths:

```text
web/
  server/
    pyproject.toml
    app/
      __init__.py
      main.py
      errors.py
      routes.py
    tests/
    image_tests/
  frontend/
    package.json
    package-lock.json
    index.html
    tsconfig.json
    vite.config.ts
    src/
    tests/
```

The webserver runs FastAPI and Uvicorn on container port 8080. It serves the built React files and exposes the existing internal `GET /healthz` liveness route. It has no API client, MongoDB client, upstream API URL, relay route, response mapping, retry, cache, authentication, or aggregation behavior.

`create_app(static_root: Path | None = None)` accepts a path override for tests. By default it resolves `static/` alongside the Python `app` package, which is `/app/static` in the runtime image. That directory is a generated image artifact, not a tracked source folder. A missing build still returns `404` on UI requests while process liveness succeeds; image verification and composed smoke checks, not health checks, prove that the frontend is packaged.

Add `web/server/app/config.py` only when local webserver settings, such as `LOG_LEVEL`, need it. Do not retain an empty settings module or add new runtime configuration knobs. HTTPX belongs only in test dependencies for the in-process test client. The web runtime has no upstream HTTPX client, `API_BASE_URL`, upstream timeout settings, or relay routes.

The API accepts an inbound `X-Request-ID` only when it is a canonical 36-character UUID string. Otherwise it generates a UUID. The API echoes the selected value in the response `X-Request-ID` header. Treat it as observability data, never identity. NGINX forwards the request header normally. The browser may omit the header or provide it for correlation.

Do not log raw request or response bodies, MongoDB URI values, passwords, credentials, arbitrary field key names, or raw invalid values. Unknown keys and identity objects may contain personal data. Log the request ID, method, normalized route template, status, elapsed time, and safe exception category.

The React app provides:

- a session list
- a session detail view
- loading, empty, and error states
- browser-local timestamp display, with the resolved time zone named in each view
- read-only expandable JSON for `metadata` and each run's `details`

### Session table and requests

The list view fetches `GET /v1/sessions` and reads rows from the response `items` array. It requires the five-field page envelope from section 8 and rejects a bare array.

The table configuration lives in `web/frontend/src/sessionColumns.tsx`:

| Column | Requested field | Display |
| --- | --- | --- |
| Started at | `started_at` | Browser-local date and time |
| Status | `status` | Raw API status token |
| Invoked by | `metadata.invoked_by.email` | Email value, or `Not provided` when absent |
| Boundary | `metadata.boundary` | Boundary value, or `Not provided` when absent |

The list request repeats `fields` for these paths. It expects only the selected paths plus `session_id`; selected metadata is not a complete metadata document. Column selection is code configuration. It is not stored in the browser URL, and `fields` is not an accepted browser view parameter.

Changing the table columns requires a frontend rebuild. It does not require a new API endpoint or a runtime column picker. Keep projected-list validation separate from strict default-summary and full-detail validation.

The detail view fetches `GET /v1/sessions/{session_id}` and receives full `metadata` and `runs`, independently of the list selection. Encode the session ID as one URL path segment. Preserve backend field names and JSON types. Do not compute a frontend `execution_outcome` from runs.

### Filters and drafts

The filter panel maps its controls to the section 8 query parameters:

| Control | Parameter | Browser behavior and API matching |
| --- | --- | --- |
| Status | `status` | Shows `All statuses`, `In progress`, `Completed`, and `Failed`. `All statuses` omits the parameter; the other choices send `IN_PROGRESS`, `COMPLETED`, or `FAILED`. |
| Boundary | `boundary` | Sends nonblank text verbatim. Matches a literal substring without regard to case. |
| Invoked by email | `invoked_by_email` | Sends nonblank text verbatim. Matches the complete value exactly and case-sensitively. It does not validate email syntax. |
| Started from | `started_from` | Uses a local date and time input. Matches `started_at` greater than or equal to the resulting instant. |
| Started before | `started_before` | Uses a local date and time input. Matches `started_at` strictly before the resulting instant. |

Text filters accept at most 256 code points. Blank and whitespace-only form values are omitted. A nonblank value keeps surrounding spaces because the API treats them as literal text. An explicitly empty parameter in a restored URL is an error rather than an omitted filter.

Selected metadata values are not restricted to strings. The table renders non-string values as JSON text and uses `Not provided` only when the selected path is absent.

Input edits are drafts. They do not change the URL or issue a request until the user selects **Apply filters** or submits the form with Enter. Hiding the panel keeps the draft mounted. The filter badge counts applied filters, not draft values.

**Clear filters** clears the draft and applied filters. It keeps the selected page size and drops the cursor, which returns the list to its newest page. A page-size change takes effect immediately and also drops the cursor. Paging continues with the applied filters when the panel contains an unsubmitted draft.

For restored browser URLs, reject unknown, repeated, or explicitly empty parameters. Also reject unsupported status or page-size values, filter text that violates the supported bounds, timestamp text that fails the supported RFC 3339 parsing, and an invalid timestamp range without issuing a request. This keeps those errors from widening the list silently. Do not claim that the browser validates a cursor. It passes a nonempty cursor through unchanged so the API can validate its shape and filter and size fingerprint. Display a safe API error if the API rejects it.

### Pagination and URL state

The browser offers page sizes `25`, `50`, and `100`, with `25` as the default. This is a UI choice. The API range remains `1` through `100` as specified in section 8. The browser always sends the effective size to the API, but omits the default size from its own URL.

The list uses `next_cursor` and `previous_cursor` from the page envelope. Cursors are opaque. There are no page numbers or offsets. The UI resends the applied filters and page size with a cursor.

Applied filters, a nondefault page size, and the current cursor live in the browser query string. Refresh, shared links, and browser history restore those applied parameters. Draft inputs are not URL state. Filter values, including `invoked_by_email`, are visible in the address bar, shared links, and browser history. They may also appear in HTTP access logs. This POC adds no privacy protection for query parameters.

`total_count` is the live count for the applied filters, not the number of rows on the current page. The count and rows come from separate reads and are not a snapshot. New sessions and edits to filtered values can change membership between reads, so next and previous pages are not snapshots of one fixed result set.

When `items` is empty, the view distinguishes these cases:

- `total_count` is zero with no filters: no sessions have been recorded.
- `total_count` is zero with filters: no sessions match the filters.
- `items` is empty while `total_count` is positive: the cursor page changed. Offer **Return to newest sessions** and do not restart automatically.

A same-tab row click or link carries the current list path in router state. **All sessions** uses that state to return to the applied filters, page size, and cursor. When router state is absent, as with a direct detail URL or a new-tab detail view, **All sessions** falls back to `/`.

### Local time display and input

Render session and run timestamps in the browser time zone. Name the resolved zone once in each view. Keep the API timestamp text in `dateTime` attributes and raw JSON disclosures.

The date filters use native local date and time inputs with one-second steps. Convert an edited local value to one UTC RFC 3339 instant before adding it to the request. Do not parse a formatted table or detail value back into a request. Reject a local time skipped by a daylight saving clock change rather than shifting it.

Storage and API response timestamps remain UTC. Local display does not rewrite them. Raw JSON and `dateTime` values keep the API text.

Frontend `json.ts` parses integer source tokens outside the safe JavaScript number range into `bigint` and serializes them back as unquoted JSON numbers for display. Preserve ordinary floating-point semantics and leave numeric strings as strings. Use the exact-number formatter for metadata, outcomes, run details, and the full-response disclosure; do not pass these records to native `JSON.stringify` or coerce large integers to `number`.

Render null counts as `unknown`, never `0`. Treat absent counts as unknown. Render unrecognized verdict strings as plain text. Render `last_step_executed` as names, not links. In the detail view, show `recorded_by` and `invoked_by` separately when present, and tolerate either being absent.

Render all data as text. Do not use `dangerouslySetInnerHTML` for errors or stored JSON.

Browser `fetch` does not reject its promise for HTTP `4xx` or `5xx`. Check `response.ok` and verify the response `Content-Type` before treating a body as JSON. Application API errors use the envelope in section 9. NGINX can return HTML for `502` and `504`, and network failures have no HTTP body. Show a safe UI error in every case. Never render raw HTML returned by the edge or add a BFF to translate these errors. Preserve API error codes rather than remapping them.

There is no SSR. Do not add browser credential or token handling for this unauthenticated POC.

Serve `index.html` only for known UI GET paths:

```text
/
/sessions/{session_id}
```

Serve built assets under `/assets/*`. A missing asset returns `404`, not `index.html`. Any unknown UI route returns `404`. Old `/ui/api/*` paths also return `404`; they are neither compatibility proxies nor SPA routes. Register the internal web health route before static assets and UI routes.

Serve `index.html` with `Cache-Control: no-cache` so browsers revalidate the entry page after deployment rather than retaining references to replaced asset hashes. This does not add an application cache. Keep unknown paths and trailing-slash variants as `404`, and keep asset containment enforced by the static server.

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

These are process liveness checks. They do not query MongoDB and do not claim database readiness. The web health check does not test API readiness or connectivity. A later database outage causes normal API requests to return sanitized `500` errors.

Use Python `urllib` for API and web container health checks so no extra command-line HTTP client is required:

```text
API: http://localhost:8000/healthz
web: http://localhost:8080/healthz
```

Use `mongosh` with root credentials for the MongoDB ping health check. Pass credentials without printing them in logs or process setup output where avoidable.

Compose requirements:

- `mongo` has a named volume and a health check.
- `api` depends on healthy `mongo`.
- `web` has no API or MongoDB startup dependency because it serves static assets. Do not add either dependency.
- `nginx` depends on healthy `api` and `web`.
- All services use `restart: unless-stopped`.
- `api`, `web`, and `mongo` may use `expose` but no host `ports`.
- Only `nginx` maps `0.0.0.0:8080:80`.

NGINX forwards standard proxy headers for observability. Forwarded headers are not trusted identity and do not change the security model.

The JSON error envelope is guaranteed for application API responses. NGINX-generated edge errors, including some `404`, `502`, and `504` responses, may be HTML and are seen directly by the browser. Do not claim a JSON envelope at the edge.

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
| `LOG_LEVEL` | API and web | `INFO` | Application log level |
| `TEST_MONGO_URI` | API integration tests only | Required for integration tests, none | Privileged test-deployment URI whose default database is exactly `quality_agent_test` and whose `authSource` is `admin` |
| `TEST_MONGO_BASE_DB_NAME` | API integration tests only | `quality_agent_test` | Fixed base used to create one isolated fixture database named `quality_agent_test_<uuid4hex>` |

Keep NGINX `proxy_read_timeout 60s` and MongoDB client timing in static configuration. Use a 5-second server selection timeout and sensible 30-second socket timing. Do not expose every internal setting as an environment variable.

The webserver needs no upstream API URL or API credential. Frontend API URLs are relative and need no environment variable. Never put secrets in Vite variables because the bundle is visible to the browser.

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
- After raw JSON value validation passes, every session patch containing top-level `started_at` returns `400 forbidden_field` before Pydantic or repository operations, including when the value is identical, null, or a malformed timestamp. The whole patch is rejected, so valid sibling fields are not applied.
- Raw JSON value errors still take precedence over the patch `started_at` rejection. Nested fields named `started_at` remain data in their containing objects and are not treated as the reserved root field.
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
- Non-string repository identifiers, including `None`, 12-byte values, and `ObjectId` instances, are treated as malformed and issue no MongoDB operation.
- Collections inherit the configured write concern; no adapter overrides it.
- Startup rejects an unacknowledged write concern before the ping and index step and still closes the client.
- A real oversize insert returns `413`.
- Cumulative metadata growth by patch returns `413` and leaves the prior document unchanged.
- Non-finite numbers, huge integers, NUL keys, parse recursion, and final depth over 100 return `400` with the intended code.
- Session lists always return the five-field page envelope, never a bare array.
- Default session list items retain exactly the eight root fields and exclude metadata and runs.
- Repeated list `fields` selectors select nested values while always returning `session_id`. ID-only and empty-result requests work without loading full documents or querying runs.
- Invalid field selectors return sanitized `400 invalid_field` before any repository call. Validate invalid children even when a valid parent is also selected.
- Duplicate and overlapping paths collapse without confusing siblings such as `metadata.a` and `metadata.ab`. Selection changes neither ordering nor membership.
- Each filter builds its documented predicate, and supplied filters combine conjunctively.
- Unknown, repeated, and invalid list query parameters return sanitized `400 invalid_field` before any repository call, including unknown statuses, unparseable or inverted timestamp bounds, empty or oversized filter text, and non-strict page sizes.
- Page size defaults to 25, accepts 1 through 100, and bounds the returned items.
- `total_count` reflects every filter match and is independent of the cursor and the page.
- Forward traversal visits every matching session exactly once on unchanged data, including when sessions share a `started_at` value, and a previous cursor returns the preceding page.
- A projected page still mints working cursors, and an ID-only page does not leak `started_at`.
- Cursors are rejected when malformed, tampered, version-mismatched, unrepresentable, or reused with different filters or page size, and are accepted with a different `fields` selection.
- A valid cursor whose matches have disappeared returns an empty terminal page with the live total.
- Selected nulls and missing values remain distinct. Selected root timestamps retain UTC millisecond formatting; complete selected parents preserve special keys and large integers.
- A projected list read does not narrow later list or detail reads. Default and detail responses still reject incomplete or invalid repository records.
- Detail reads use separate queries and make no snapshot claim.
- Late run insertion into a terminal session succeeds.
- Request ID acceptance, generation, and response-header echo follow the API contract in section 11.

The MongoDB integration suite pins these behaviors against the chosen image and PyMongo lock:

- insert oversize maps to `413`
- cumulative patch oversize maps to `413` with no partial change
- empty patch returns `200` based on `matched_count`
- server-side oversize codes used by the pinned MongoDB version map correctly
- the deployed write concern is acknowledged, so inserted identifiers and `matched_count` are reported
- the boundary filter matches literal text without regard to case, and an escaped value does not match as a pattern
- a text filter matches only a genuine scalar string, so missing, null, numeric, object, and array values never match, including an array of identity objects that path traversal would otherwise reach
- an operator-shaped filter value such as `$status` is treated as data
- `status` and the half-open timestamp range select their documented sets, and combined filters narrow conjunctively
- forward traversal visits every matching session exactly once with repeated `started_at` values, and ties order by descending identifier
- a previous cursor returns the preceding page and the newest page offers no previous cursor
- an ID-only page does not leak the sort key, and selected metadata paths survive a filtered page
- `total_count` covers all matches rather than the returned page

### Static webserver tests

Cover the known SPA routes, internal health, built asset MIME types, missing assets, unknown routes, and old `/ui/api/*` paths. Missing assets, unknown routes, and `/ui/api/*` must return `404`. Verify that the webserver creates no outbound HTTP client and makes no API or MongoDB call.

`web/server/tests` uses temporary HTML/CSS/JavaScript fixtures and runs without a frontend build. `web/server/image_tests` is a separate, explicitly selected suite for the Docker test target: use the default static root and the actual bundle inherited from the runtime image, without host asset mounts or skip-on-missing behavior. Parse the packaged HTML and request its generated scripts and stylesheets; also verify deep links, internal liveness, missing routes, non-root execution, and absence of Node/npm. Verify the HTML cache-revalidation header in fixture and image tests.

### UI tests

Use Vitest and the React testing library under jsdom. Pin the main suite to `Asia/Kolkata` so local rendering and local-to-UTC conversion do not depend on the host zone. Keep separate conversion coverage under `America/New_York` for a skipped spring time and a repeated autumn time.

Cover loading, empty, and error states; unknown count rendering; local timestamps and the named zone; unrecognized verdict text; missing identity values; expandable metadata and details; and HTML-like stored text escaping. Assert the exact relative `/v1/sessions` and encoded `/v1/sessions/{session_id}` fetch paths, with no `/ui/api/*` calls. Cover the five-field page envelope and its rejection of a bare array; configured field requests; filter serialization, including omitted empty values and preserved literal text; local date bounds converted to UTC instants, an inverted range, and a local time skipped by a daylight saving change; drafts that issue no request until submitted and remain mounted while the panel is hidden; supported browser page sizes; cursor navigation that keeps the applied filters, and the cursor reset on a filter or page-size change; restored links, including rejected unknown, repeated, and invalid parameters; browser history restoring applied filters; the three empty results; and the return from a detail view to the same filtered page. Cover non-OK API envelopes, non-JSON NGINX errors, and network failures without rendering raw HTML.

The jsdom suite is not browser verification. Do not report browser behavior as verified unless the separate manual browser checks were performed.

### Composed smoke tests

Run HTTP smoke tests through NGINX. Verify `/v1` routing, known UI routes, unknown route behavior, missing assets, public host binding, and that API and web health routes are internal while edge `/healthz` is `404`.

`scripts/smoke.py` performs GET-only deployment checks. Require root/deep-link HTML, discover and fetch same-origin `/assets/` scripts/styles with correct MIME types, check selected, ID-only, and filtered session pages against the five-field envelope, and reject both an invalid selector and an invalid list parameter even on an empty database. When a session exists, check one complete detail response. Do not compare separate reads as snapshots or print record contents. Reject redirects, unexpected response types, and a bare array list response. Edge `404` responses need not be JSON. Cover smoke failures with `python3 -m unittest discover -s scripts/tests -v`.

HTTP smoke checks do not execute React. Separately verify in a browser that the table or empty state renders, and that row navigation and full details work when data exists. Do not claim browser verification from HTTP status checks alone.

Do not set an arbitrary coverage percentage. This specification does not establish the current test status. Do not claim tests passed until they have run in the implementation environment.

## 15. Build, run, and implementation sequence

These are command contracts for the target implementation. Run them only when the current worktree implements the referenced files and workflows.

Default composed workflow from the repository root:

```bash
docker compose build
docker compose up -d --wait
```

See [deployment instructions](docs/deployment.md) for image tests, safe redeployment of the existing local stack, smoke verification, and rollback. Health alone is not the deployment acceptance gate. Verify only NGINX publishes `0.0.0.0:8080`, preserve the MongoDB volume, and refresh NGINX after replacing upstream containers so its resolved addresses are current.

Verify the packaged web image without a host `dist/` mount:

```bash
docker build --target test -t quality-agent-web-packaging-tests web
docker run --rm --network none quality-agent-web-packaging-tests
docker build --target test -t quality-agent-api-tests api
docker run --rm --network none quality-agent-api-tests
```

The test target inherits the runtime bundle and runs `tests` plus `image_tests`. The Node builder also runs frontend tests and the type-checked production build. Runtime images do not include Python test dependencies or Node/npm.

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

Local static webserver test workflow uses a separate environment to avoid the two `app` packages colliding:

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

Define `npm test` as the nonwatch command `vitest run`. Pin a Vite-compatible Node 22 builder image and commit `package-lock.json`. Use each Python server's packaging and lock files for dependencies, not the historical `requirements.txt` prose.

After deployment, run the root smoke command:

```bash
python3 scripts/smoke.py --base-url http://localhost:8080
```

The fixture web tests, image tests, frontend unit/interaction tests, API unit tests, the guarded list-query integration suite, and the HTTP smoke workflow have executable files in the worktree. The remaining guarded real-Mongo coverage for oversize writes and write concern, the Compose test overlay, the run-creation endpoint, and API request-correlation middleware remain separate planned work. Do not describe those capabilities as verified by frontend deployment checks.

Implement in small, reversible stages:

1. Add API packaging, configuration, parsing, schemas, mapping, and unit tests.
2. Add MongoDB repositories, indexes, lifespan, and real-Mongo integration tests.
3. Add controllers and endpoint tests through FastAPI.
4. Align the Python webserver to serve static assets and internal health only. Add route tests and API request correlation.
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
