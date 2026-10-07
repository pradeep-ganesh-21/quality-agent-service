# Coding agent guide

## Start here

Read [DESIGN.md](DESIGN.md) in full before planning or changing this repository. It is the authoritative executable specification for the proof of concept.

Re-read the relevant DESIGN.md sections immediately before implementation. If a material behavior is missing, stop and ask. Do not invent a default, copy a legacy shape, or leave a production TODO while claiming the work is complete.

## Source authority

Use this order when sources conflict:

1. `DESIGN.md`
2. Current implementation and tests that conform to `DESIGN.md`
3. `requirements.txt` as background only
4. `run.json`, `Mongo Schema.txt`, `quality-agent-architecture.drawio`, and `noc-agent.drawio` as legacy or production context only

Do not edit the legacy sample, schema draft, requirements prose, or architecture diagrams to make an implementation change appear consistent.

## Hard rules

- Build a Python FastAPI API with the official PyMongo `AsyncMongoClient`. Do not use Motor or an ODM.
- Keep business logic in `api/app/services`. Do not add a separate business or domain layer.
- Keep `ObjectId`, BSON, clients, cursors, filters, and MongoDB operators inside repository adapters. `indexes.py` may contain index definitions.
- Use narrow repository protocols as actual service test seams. Do not add generic CRUD bases or a DI container.
- Create one MongoDB client in API lifespan. Ping and create indexes at startup, then close the client at shutdown.
- Construct the client inside the repository adapter with `tz_aware=True`, `tzinfo=timezone.utc`, and the timeouts fixed in DESIGN.md.
- Remember that async PyMongo `find()` returns a cursor synchronously. Do not await `find()`.
- Preserve unknown parsed JSON under server-created `metadata` and `details` wrappers. Do not flatten, rewrite, evaluate, index, or use it for business rules.
- Reject reserved top-level fields before Pydantic. Nested `_id`, dotted keys, and dollar-prefixed keys are allowed subject to DESIGN.md validation.
- Treat root session `started_at` as creation-only. Reject it on every session `PATCH` with `400 forbidden_field` before Pydantic or repository operations.
- Persist Python datetimes, not JSON-dumped strings. Store ObjectIds and map them explicitly to response strings.
- Implement session patch as the single guarded pipeline update in DESIGN.md. Use `$literal` for every supplied value and always shallow-merge metadata with `$mergeObjects`.
- Use `matched_count` for patch success. Do not use `modified_count` as the success test.
- Catch `DocumentTooLarge` before `InvalidDocument`.
- Map JSON parse `RecursionError` to `400`.
- Override FastAPI request validation to `400`. Preserve Starlette HTTP exception status and the `Allow` header on `405`.
- Keep detail reads unbounded and use two detail queries. Do not add `$lookup`, hidden limits, or snapshot claims to any read.
- Return every session list as the five-field page envelope in DESIGN.md. Keep paging cursor-based with next and previous only, and never add offsets, page numbers, or a client-selectable sort.
- Support only the named list filters in DESIGN.md. Filter no metadata path other than `metadata.boundary` and `metadata.invoked_by.email`, escape literal filter text, and require a genuine non-array scalar at every filtered metadata path.
- Validate every list query parameter in the service before any repository call. Reject unknown and repeated parameters with `invalid_field` instead of ignoring them, and never echo a supplied value.
- Treat cursors as unsigned continuation values, not credentials. Bind them to the filters and page size, validate them before any database operation, and return an empty terminal page for a stale one.
- Always project the list sort key to mint cursors, and strip it from records that did not select it.
- Allow run insertion after a parent becomes terminal. Only session patch is status-guarded.
- Browser code calls only relative `/v1/sessions` (optionally with repeated `fields` parameters and the DESIGN.md filter and paging parameters) and `/v1/sessions/{session_id}` paths through NGINX. It never uses the Docker hostname `api`, its internal port, `API_BASE_URL`, or `/ui/api/*`.
- Read list rows from `page.items` and navigate only with response cursors. Keep applied filters, page size, and cursor in the browser URL. Keep unsubmitted filter drafts out of it, and drop the cursor when filters or page size change.
- Offer browser page sizes `25`, `50`, and `100`, with `25` as the default. Do not narrow the API contract, which accepts `page_size` from 1 through 100.
- Display session and run timestamps in the browser's named local time zone. Convert local filter inputs to one UTC API instant, and preserve API timestamp text in raw JSON and `dateTime` attributes.
- The Python webserver serves built React assets and internal liveness only. It has no API or MongoDB client, BFF data routes, server rendering, retries, caching, authentication, or aggregation.
- Keep default list items to the eight root fields in DESIGN.md, excluding metadata and runs. Explicit `fields` selection may include metadata paths; always return `session_id`, never runs, and do not fill omitted values. Validate selectors in services and build inclusion projections only in the repository adapter. Keep the full detail projection independent of selected list fields.
- Serve the SPA only for `/` and `/sessions/{session_id}`. Unknown routes and missing assets return `404`.
- NGINX is the only host-published service at `0.0.0.0:8080:80`. Keep HTTP only.
- Set `client_max_body_size 0`. Do not add an application request size cap.
- Do not add HTTP authentication, tokens, TLS, CORS as a security claim, queues, Redis, deletes, `PUT`, idempotency, or transactions.
- Do not log bodies, credentials, arbitrary extra keys, or raw invalid values.
- Treat API and web health routes as internal liveness only. Edge `/healthz` remains `404`.
- Package the React build into the Python web image at `/app/static`. Verify the image without a host asset mount and run the composed UI/asset smoke checks before declaring deployment complete; healthy containers alone are not sufficient.
- Keep the exact NGINX `location = /healthz { return 404; }` block before proxy locations.
- Keep `.env` ignored and commit placeholders only in `.env.example`.
- Run MongoDB integration tests only with the guarded, privileged test deployment settings in DESIGN.md. Never widen runtime application-user privileges.
- Never use `docker compose down -v` as a normal reset or rollback instruction.

## Before reporting completion

Check the implementation against the endpoint, error, index, web/browser, deployment, and test contracts in DESIGN.md. Run only commands that the repository now implements. State which commands ran and which did not.

Do not claim a live MongoDB integration test, composed smoke test, package lock, or production behavior without evidence from the current worktree and test output.

HTTP smoke checks do not execute React. Report browser verification separately and only when it was actually performed.
