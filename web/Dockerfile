FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server/requirements.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && useradd --create-home --uid 10001 appuser
COPY server/app ./app
USER appuser
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]

FROM runtime AS test
USER root
COPY server/requirements-dev.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-dev.lock
COPY server/pyproject.toml ./
COPY --chown=appuser:appuser server/tests ./tests
USER appuser
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider", "tests"]
