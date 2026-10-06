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
- Persist Python datetimes, not JSON-dumped strings. Store ObjectIds and map them explicitly to response strings.
- Implement session patch as the single guarded pipeline update in DESIGN.md. Use `$literal` for every supplied value and always shallow-merge metadata with `$mergeObjects`.
- Use `matched_count` for patch success. Do not use `modified_count` as the success test.
- Catch `DocumentTooLarge` before `InvalidDocument`.
- Map JSON parse `RecursionError` to `400`.
- Override FastAPI request validation to `400`. Preserve Starlette HTTP exception status and the `Allow` header on `405`.
- Keep reads unbounded and use two detail queries. Do not add pagination, hidden limits, `$lookup`, or snapshot claims.
- Allow run insertion after a parent becomes terminal. Only session patch is status-guarded.
- Browser code calls only relative `/ui/api/*` paths. It never calls `/v1` directly.
- The Python BFF passes API JSON through. It adds no business logic, retries, caching, authentication, or aggregation.
- Serve the SPA only for `/` and `/sessions/{session_id}`. Unknown routes and missing assets return `404`.
- NGINX is the only host-published service at `0.0.0.0:8080:80`. Keep HTTP only.
- Set `client_max_body_size 0`. Do not add an application request size cap.
- Do not add HTTP authentication, tokens, TLS, CORS as a security claim, queues, Redis, deletes, `PUT`, idempotency, or transactions.
- Do not log bodies, credentials, arbitrary extra keys, or raw invalid values.
- Treat API and web health routes as internal liveness only. Edge `/healthz` remains `404`.
- Keep the exact NGINX `location = /healthz { return 404; }` block before proxy locations.
- Keep `.env` ignored and commit placeholders only in `.env.example`.
- Run MongoDB integration tests only with the guarded, privileged test deployment settings in DESIGN.md. Never widen runtime application-user privileges.
- Never use `docker compose down -v` as a normal reset or rollback instruction.

## Before reporting completion

Check the implementation against the endpoint, error, index, BFF, deployment, and test contracts in DESIGN.md. Run only commands that the repository now implements. State which commands ran and which did not.

Do not claim a live MongoDB integration test, composed smoke test, package lock, or production behavior without evidence from the current worktree and test output.
