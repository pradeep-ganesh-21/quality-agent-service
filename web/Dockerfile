FROM node:22-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm test && npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server/requirements.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && useradd --create-home --uid 10001 appuser
COPY server/app ./app
COPY --from=frontend-build /frontend/dist ./static
RUN test -s /app/static/index.html && test -d /app/static/assets
USER appuser
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]

FROM runtime AS test
USER root
COPY server/requirements-dev.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-dev.lock
COPY server/pyproject.toml ./
COPY --chown=appuser:appuser server/tests ./tests
COPY --chown=appuser:appuser server/image_tests ./image_tests
USER appuser
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider", "tests", "image_tests"]
