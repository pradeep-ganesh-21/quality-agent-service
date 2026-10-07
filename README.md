# Quality Agent Tracker

Quality Agent Tracker is a proof-of-concept service for storing and viewing reports produced by quality agents. It records sessions in MongoDB and presents them through a FastAPI API and a read-only React interface. It does not run quality checks itself.

Start with these documents when changing the project:

- [DESIGN.md](DESIGN.md) is the executable specification and takes precedence over the implementation.
- [AGENTS.md](AGENTS.md) summarizes the repository rules for coding agents and contributors.
- [docs/deployment.md](docs/deployment.md) contains the full deployment, verification, redeployment, troubleshooting, and rollback procedures.
- [docs/architecture/quality-agent-architecture.drawio](docs/architecture/quality-agent-architecture.drawio) is the living POC overview. It follows the design rather than defining it.

## Current status

The current API implements four session routes:

- `POST /v1/sessions`
- `PATCH /v1/sessions/{session_id}`
- `GET /v1/sessions`
- `GET /v1/sessions/{session_id}`

The detail route reads existing run records, but `POST /v1/sessions/{session_id}/runs` is still planned. API request-correlation middleware, a Compose test overlay, and guarded real-Mongo coverage for oversized writes and write concern are also planned. The current real-Mongo integration suite covers session list queries. Do not present planned work as implemented.

Run the checks relevant to your change before reporting it complete, and state which commands actually ran. Health and HTTP smoke checks do not execute React. Report browser behavior as verified only after completing the manual browser checks.

## Choose a development workflow

Use Compose for your first start and for integrated verification. It builds the frontend inside the web image, starts MongoDB, the API, the static webserver, and NGINX, and exposes the intended same-origin application at `http://localhost:8080`. You do not need host Python 3.12 or Node for this workflow. The cost is a slower rebuild cycle, and runtime changes require rebuilding and recreating images because the stack has no source bind mounts or developer reload.

Use host environments for focused API, static-server, or frontend checks. They give a faster edit-test cycle, but they are separate component workflows rather than another integrated deployment. In particular, the Vite development server has no `/v1` proxy. Do not add `API_BASE_URL`, CORS configuration, Docker hostnames, or separate-host API paths to turn it into one. Integrated browser traffic must use relative `/v1/sessions` paths through NGINX.

## Prerequisites

For the Compose workflow:

- Docker with Compose support, including `docker compose up --wait`.
- Python 3.9 or newer for `scripts/init_local_env.py` and `scripts/smoke.py`.

For host component development:

- Python `>=3.12,<3.13` for both Python packages.
- Node `^22.22.2`, `^24.15.0`, or `>=26.0.0` for the frontend. A compatible Node 22 release is recommended because the Docker builder uses a digest-pinned Node 22 image. Not every Node 22 or Node 24 release is accepted. For example, Node 24.12.0 is outside the package engine range.

Commands below use POSIX shell syntax on macOS or Linux. Each command block starts from the repository root unless its first command changes directory.

## Start the integrated stack

### Protect existing credentials and data

MongoDB initialization runs only when its data directory is new. Changing `.env` does not rotate users in an existing volume.

Before generating anything, check whether this checkout belongs to an existing deployment. If `.env` exists, retain it. If `.env` is missing but an existing MongoDB volume may contain data, stop and recover the original credentials. Generating new credentials will not update the user stored in that volume. Do not delete the volume to solve an authentication or frontend problem.

For a first installation with no existing `.env` or MongoDB data, run:

```bash
python3 scripts/init_local_env.py
```

The script creates `.env` with mode `0600`, does not print credential values, and refuses to overwrite an existing file. `.env.example` is a variable reference with placeholders, not a usable credential file. Keep `.env` private and out of version control.

### Build, start, and check the stack

> **Security warning:** This POC is HTTP-only and has no HTTP authentication. Every host that can reach port 8080 can read and write `/v1/*`. Compose publishes NGINX on all host interfaces at `0.0.0.0:8080`. Request bodies and session detail responses are unbounded. Callers can walk every list page and invoke an unindexed substring filter. Do not expose this stack to an untrusted network or use it as a production deployment.

From the repository root:

```bash
docker compose build
docker compose up -d --wait
docker compose ps
```

Only NGINX should publish a host port, at `0.0.0.0:8080`. Open `http://localhost:8080/` after the checks below.

## Verify the deployment

First, verify the test images and the smoke validator itself. These commands run from the repository root:

```bash
docker build --target test -t quality-agent-web-packaging-tests web
docker run --rm --network none quality-agent-web-packaging-tests
docker build --target test -t quality-agent-api-tests api
docker run --rm --network none quality-agent-api-tests
python3 -m unittest discover -s scripts/tests -v
```

The web image test checks the actual React bundle packaged at `/app/static`, with no host asset mount. It also checks that the runtime image runs as a non-root user and contains neither Node nor npm. A healthy web process alone does not prove that the bundle was packaged.

Run the read-only HTTP smoke checks through NGINX:

```bash
python3 scripts/smoke.py --base-url http://localhost:8080
```

> **Known smoke validator bug:** The selected-list request asks the API for `status`, but `check_list` rejects `status` in a populated selected row. A conforming populated response can therefore fail this check. An empty database does not exercise the mismatch. Do not bypass the check or delete data to make it pass. Align `scripts/smoke.py` and `scripts/tests/test_smoke.py` before treating that selected-field check as an acceptance gate on populated data.

The smoke script checks HTTP routing, generated asset references, API list shapes, one detail response when data exists, and expected `404` routes. It does not execute React. Complete the separate [manual browser checks](docs/deployment.md#verification): confirm the table or empty state, session navigation when data exists, filters, cursor paging, URL restoration, and browser-local timestamp behavior.

## Run focused host tests

### API unit tests

Create the API environment and run tests without the MongoDB integration marker:

```bash
python3.12 -m venv api/.venv
api/.venv/bin/python -m pip install -e 'api[dev]'
cd api
.venv/bin/python -m pytest -m 'not integration'
```

Keep `-m 'not integration'`. A bare `pytest` includes `api/tests/integration` and fails when the guarded test MongoDB configuration is absent.

### Static webserver tests

Use a second environment because both Python packages are named `app`:

```bash
python3.12 -m venv web/server/.venv
web/server/.venv/bin/python -m pip install -e 'web/server[dev]'
cd web/server
.venv/bin/python -m pytest
```

These tests use temporary HTML, CSS, and JavaScript fixtures. They do not require a frontend build. `web/server/image_tests` requires the real `/app/static` bundle and belongs in the Docker image-test workflow above.

### Frontend tests and build

With a supported Node release:

```bash
cd web/frontend
npm ci
npm test
npm run build
```

`npm test` runs Vitest once. `npm run build` runs TypeScript checking before the Vite build. Host `node_modules` and `dist` are excluded from the Docker build context, so these outputs are not used by `docker compose build`.

### Optional real-Mongo list integration tests

Run these only against a separately provisioned test MongoDB deployment. The test user must authenticate against `admin` and be allowed to create and drop isolated databases. Never use the runtime application user, runtime database, or runtime `MONGO_URI`. Do not publish the application MongoDB port for tests.

Replace every uppercase placeholder and percent-encode the credentials:

```bash
export TEST_MONGO_URI='mongodb://TEST_USER:TEST_PASSWORD@TEST_HOST:27017/quality_agent_test?authSource=admin'
export TEST_MONGO_BASE_DB_NAME='quality_agent_test'
cd api
.venv/bin/python -m pytest -m integration
```

The fixture creates a random database named `quality_agent_test_<uuid4hex>` and drops only the database it recorded. There is no `docker-compose.test.yml` in the current worktree, so no Compose integration-test command is available yet.

## Repository map

```text
api/                         FastAPI API package
  app/controllers/           HTTP routes
  app/services/              business rules, mapping, list validation and cursors
  app/repositories/          PyMongo adapters, protocols, ObjectId handling and indexes
  app/schemas/               request and response models
  tests/unit/                API and adapter unit tests
  tests/integration/         guarded real-Mongo list-query tests
web/
  frontend/src/              React application
  frontend/tests/            Vitest and interaction tests
  server/app/                Python static webserver
  server/tests/              fixture-based server tests
  server/image_tests/        packaged-bundle image tests
mongo/init-app-user.js       first-volume application-user initialization
nginx/nginx.conf             public routing and edge behavior
scripts/                     credential bootstrap and read-only HTTP smoke checks
docs/deployment.md           detailed operations and browser verification
```

## Extend the project safely

Read [DESIGN.md](DESIGN.md) in full before planning a change, then re-read the relevant sections before implementation. If the design does not define a material behavior, stop and ask rather than choosing a default.

Use the existing ownership boundaries:

- Put HTTP binding in `api/app/controllers`, business rules in `api/app/services`, and MongoDB mechanics in `api/app/repositories`.
- Test service behavior through the narrow protocols in `api/app/repositories/protocols.py`. The current code does not yet define the planned session-existence or run-create protocol methods.
- Keep `ObjectId`, BSON, clients, cursors, filters, projections, and MongoDB operators inside repository adapters.
- Change table columns in `web/frontend/src/sessionColumns.tsx`. Change applied filter and paging URL behavior in `web/frontend/src/sessionQuery.ts`. Keep API validation in `web/frontend/src/api.ts`, time formatting in `web/frontend/src/format.ts`, and exact-number JSON handling in `web/frontend/src/json.ts`. Add tests beside the affected module.
- Add only selectors and filters already approved by the API contract. A new arbitrary filter requires a design change, not only a frontend control.
- Treat schema and index changes as migrations. Update schemas, centralized consumed-field mapping, adapters, and tests. Every approved stored-shape change must increment `schema_version` and define either a deliberate data backfill or a backward-reader contract before code lands. Never redefine an existing index name in place.

Before opening a change for review, check these invariants:

- Session `PATCH` remains one atomic, status-guarded pipeline update. Root `started_at` remains creation-only.
- Unknown parsed JSON stays under server-created `metadata` or `details` without flattening or interpretation.
- List reads keep their five-field page envelope, approved filters, field selection, and cursor behavior.
- Browser requests remain same-origin relative paths through NGINX.
- Logs and commits contain no bodies, credentials, arbitrary extra keys, or raw invalid values.
- Tests cover the service seam, adapter behavior, HTTP binding, or frontend module changed.

For the planned run-creation endpoint, follow the separate `RunService` flow specified in DESIGN.md. Add the missing controller, service, protocol operations, adapter write path, and paired tests. Run insertion must remain allowed after a parent session becomes terminal.

## Stop, redeploy, and roll back

To stop containers without resetting data, run from the repository root:

```bash
docker compose stop
```

Do not use a volume-removal command as a routine reset or rollback. For an existing running stack, follow [Redeploy an existing running stack](docs/deployment.md#redeploy-an-existing-running-stack). Retain rollback tags before replacement and confirm MongoDB is healthy. Recreate API and web, then recreate NGINX so it resolves the replacement upstream addresses.

Rollback requires the image tags retained before deployment. Follow [Rollback](docs/deployment.md#rollback). It restores application images and configuration, not database contents, and it must not delete the MongoDB volume.
