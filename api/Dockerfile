FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock \
    && useradd --create-home --uid 10001 appuser
COPY app ./app
USER appuser
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM runtime AS test
USER root
COPY requirements-dev.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-dev.lock
COPY pyproject.toml ./
COPY --chown=appuser:appuser tests ./tests
USER appuser
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider", "tests/unit"]
