# Local POC deployment

Open **http://localhost:8080/** after deployment and verification. NGINX is the only host-published service. It serves public requests through the Python webserver for UI files and through the API for `/v1/*` data.

This POC is HTTP-only and unauthenticated. Anyone who can reach port 8080 can read and write API data. Request bodies and session detail reads are unbounded, and explicit full-metadata selection can use substantial memory and bandwidth. Session list reads are bounded to one page of at most 100 records, but any caller can still walk every page and can request substring filters that the server evaluates without a supporting index. This is not a production deployment.

## Prerequisites

- Docker with Compose, and Python 3.9 or newer for the smoke script.
- Run commands from the repository root.
- Keep the existing private `.env` when a MongoDB volume already exists. Never commit or share it.
- For a first installation only, `python3 scripts/init_local_env.py` generates local credentials without overwriting an existing `.env`. `.env.example` contains placeholders, not usable deployment credentials.

MongoDB initialization runs only on a new data directory. Editing `.env` does not rotate credentials in an existing volume. Do not delete the volume to fix an authentication or frontend problem.

## What the web build packages

`web/Dockerfile` has three stages:

1. `frontend-build`: digest-pinned Node 22 runs `npm ci`, `npm test`, and `npm run build`.
2. `runtime`: Python 3.12 installs the hashed runtime lock and copies the generated frontend `dist/` into `/app/static`. Uvicorn runs as `appuser`; Node and npm are not included.
3. `test`: inherits the runtime image and its bundle, adds test dependencies, and runs fixture-based and image-level tests.

Host `web/frontend/dist`, `node_modules`, and environment files are excluded from the build context. Building React locally is not a prerequisite for `docker compose build`. Restarting an existing container does not rebuild its frontend.

`web/server/app/main.py` uses `/app/static` by default in the image. Tests can override `static_root`; deployed containers need no asset bind mount or upstream API setting.

## Test before deployment

```bash
docker build --target test -t quality-agent-web-packaging-tests web
docker run --rm --network none quality-agent-web-packaging-tests
docker build --target test -t quality-agent-api-tests api
docker run --rm --network none quality-agent-api-tests
python3 -m unittest discover -s scripts/tests -v
```

The image tests use the actual packaged HTML and discover its JavaScript/CSS references. Missing assets fail the tests, rather than being skipped. The ordinary `web/server/tests` suite still uses temporary fixtures, so it can run locally without a frontend build.

For frontend-only development checks, use the Node version supported by `web/frontend/package.json`:

```bash
cd web/frontend
npm ci
npm test
npm run build
```

The integrated browser path is through NGINX. Do not introduce `API_BASE_URL`, container hostnames, or CORS settings to connect a separately served frontend to the API.

## First startup

With valid credentials in `.env`:

```bash
docker compose build
docker compose up -d --wait
python3 scripts/smoke.py --base-url http://localhost:8080
```

Then perform the browser checks below. A green health status alone is not sufficient.

## Redeploy an existing running stack

Confirm MongoDB is already running and healthy with `docker compose ps`. Before replacing API/web images, retain rollback tags for the images used by their current containers. For each service, obtain the image ID without displaying its environment:

```bash
docker inspect --format '{{.Image}}' "$(docker compose ps -q web)"
docker inspect --format '{{.Image}}' "$(docker compose ps -q api)"
```

Tag those IDs using a unique label for this deployment, for example `quality-agent-poc-web:rollback-DEPLOYMENT` and `quality-agent-poc-api:rollback-DEPLOYMENT`. Replace `DEPLOYMENT` with your own unique label and do not overwrite an earlier rollback tag.

After all pre-deployment tests pass:

```bash
docker compose build api web
docker compose up -d --no-deps --force-recreate --wait api web
docker compose up -d --no-deps --force-recreate --wait nginx
python3 scripts/smoke.py --base-url http://localhost:8080
```

Stop if any command fails. The `--no-deps` commands above assume the existing MongoDB service is healthy; they do not recreate it. Recreating NGINX refreshes its upstream addresses after API/web replacement. This local rollout can briefly interrupt requests; it is not a zero-downtime deployment.

## Verification

The smoke script makes GET requests only. It checks:

- Root and session-deep-link HTML.
- The script and stylesheet URLs discovered in that HTML, including MIME types and nonempty bodies.
- Representative selected-field and ID-only API responses, with the UTC timestamp format required by the browser.
- Rejection of an unsupported field selector, even when no sessions exist.
- Full detail for one existing session, if available.
- Missing assets, unknown routes, and legacy `/ui/api/*` paths returning `404`.
- Edge `/healthz` returning `404`, including when NGINX sends an HTML error body.

It does not insert test records, compare reads as snapshots, or print session contents. An empty database is a valid result. These deployment checks are not the privileged MongoDB integration suite described in DESIGN.md.

In a browser:

1. Open http://localhost:8080/ and check that the session table or its empty state appears without an error banner.
2. When sessions exist, click a row, inspect the detail page, expand its JSON, and navigate back.
3. Refresh a session detail URL to check direct navigation.
4. Check that the browser calls relative `/v1/sessions` paths through the same origin and that JavaScript/CSS load successfully.

Use `docker compose ps` to confirm only NGINX publishes `0.0.0.0:8080`. API/web health checks are internal process-liveness checks. They do not prove frontend packaging or database readiness. Entry HTML uses `Cache-Control: no-cache` to revalidate references to generated asset hashes after deployment.

## Changing session columns

Edit `web/frontend/src/sessionColumns.tsx`. Each definition supplies the header, field dependencies, and renderer. Update the matching UI assertions and rebuild/redeploy the web image. The initial columns request `started_at`, `metadata.invoked_by.name`, and `metadata.boundary`.

The smoke script uses that initial selection as a representative API check; it does not derive its selector from the frontend configuration. Update the smoke selector and its tests if the deployment check should exercise a different set of columns.

No API change is required for supported field paths. The list API always supplies `session_id`; row navigation fetches complete session detail separately. Column selection is code configuration, not a browser picker.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Homepage returns JSON `404` while containers are healthy | Confirm the deployed web image was built with the frontend stage. The image tests must pass without a host `dist/` mount. |
| HTML loads but a script or stylesheet returns `404` | Rebuild the complete web image and recreate its container. Run smoke checks against the asset URLs in the newly served HTML. |
| NGINX returns `502` after replacing API/web | Wait for healthy upstreams, then recreate NGINX to refresh its resolved addresses. |
| Field-selection smoke check fails | Rebuild and recreate the API image; an older API can ignore `fields` and return its default response. |
| Table displays an API/network error | Use the smoke results to separate API/proxy failures from asset serving. Keep response bodies, identities, and credentials out of diagnostic logs. |
| UI displays no sessions | An empty database is valid. Deployment verification does not create sample data. |

## Rollback

Restore the previously retained image tags to the local Compose image names, then recreate the application containers without building:

```bash
docker image tag quality-agent-poc-api:rollback-DEPLOYMENT quality-agent-poc-api:latest
docker image tag quality-agent-poc-web:rollback-DEPLOYMENT quality-agent-poc-web:latest
docker compose up -d --no-build --no-deps --force-recreate --wait api web
docker compose up -d --no-deps --force-recreate --wait nginx
```

Use the unique label recorded before rollout. Restore any changed configuration along with its matching images. Retain a separate tag for the failed release before overwriting `latest` if you need a roll-forward reference. This does not revert database contents or delete volumes. If the previous web image lacked the frontend bundle, rollback restores that limitation too; do not call it a passing UI deployment.
