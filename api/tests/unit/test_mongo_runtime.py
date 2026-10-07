import asyncio
from datetime import timezone

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure
from pymongo.write_concern import WriteConcern

from app.repositories import mongo_runtime as runtime_module


def build_client(events, *, fail_startup=False, write_concern=WriteConcern()):
    database = type("Database", (), {"write_concern": write_concern})()

    class Client:
        admin = None

        def __init__(self, uri, **options):
            assert options == {
                "tz_aware": True,
                "tzinfo": timezone.utc,
                "serverSelectionTimeoutMS": 5000,
                "socketTimeoutMS": 30000,
            }
            self.admin = self

        async def command(self, name):
            assert name == "ping"
            events.append("ping")
            if fail_startup:
                raise ConnectionFailure("sensitive connection details")

        def __getitem__(self, name):
            assert name == "unit"
            return database

        async def close(self):
            events.append("close")

    return Client, database


def install(monkeypatch, events, client, database, repository, run_repository):
    async def ensure_indexes(value):
        assert value is database
        events.append("indexes")

    def create_repository(value):
        assert value is database
        return repository

    def create_run_repository(value):
        assert value is database
        return run_repository

    monkeypatch.setattr(runtime_module, "AsyncMongoClient", client)
    monkeypatch.setattr(runtime_module, "ensure_indexes", ensure_indexes)
    monkeypatch.setattr(runtime_module, "MongoSessionRepository", create_repository)
    monkeypatch.setattr(runtime_module, "MongoRunRepository", create_run_repository)


@pytest.mark.parametrize("fail_startup", [False, True])
def test_mongo_runtime_pings_indexes_and_closes(monkeypatch, fail_startup):
    events = []
    repository = object()
    run_repository = object()
    client, database = build_client(events, fail_startup=fail_startup)
    install(monkeypatch, events, client, database, repository, run_repository)

    async def exercise():
        async with runtime_module.mongo_runtime("mongodb://unit-test.invalid", "unit") as result:
            assert result.sessions is repository
            assert result.runs is run_repository
            events.append("running")

    if fail_startup:
        with pytest.raises(RuntimeError, match="MongoDB startup failed") as error:
            asyncio.run(exercise())
        assert "sensitive connection details" not in str(error.value)
        assert events == ["ping", "close"]
    else:
        asyncio.run(exercise())
        assert events == ["ping", "indexes", "running", "close"]


@pytest.mark.parametrize(
    "write_concern",
    [
        WriteConcern(),
        WriteConcern(w=1),
        WriteConcern(w=2),
        WriteConcern(w="majority"),
        WriteConcern(w="majority", j=True),
        WriteConcern(w=1, j=True),
    ],
)
def test_startup_accepts_every_acknowledged_write_concern(monkeypatch, write_concern):
    events = []
    repository = object()
    client, database = build_client(events, write_concern=write_concern)
    install(monkeypatch, events, client, database, repository, object())

    async def exercise():
        async with runtime_module.mongo_runtime("mongodb://unit-test.invalid", "unit") as result:
            assert result.sessions is repository

    asyncio.run(exercise())
    assert events == ["ping", "indexes", "close"]


def test_startup_rejects_unacknowledged_writes_before_pinging(monkeypatch):
    events = []
    client, database = build_client(events, write_concern=WriteConcern(w=0))
    install(monkeypatch, events, client, database, object(), object())

    async def exercise():
        async with runtime_module.mongo_runtime("mongodb://unit-test.invalid", "unit"):
            events.append("running")

    with pytest.raises(RuntimeError, match="write concern must be acknowledged") as error:
        asyncio.run(exercise())
    # The client is closed, and no ping, index, or repository work happened.
    assert events == ["close"]
    assert "unit-test.invalid" not in str(error.value)


@pytest.mark.parametrize(
    ("uri", "acknowledged"),
    [
        ("mongodb://unit-test.invalid/unit", True),
        ("mongodb://unit-test.invalid/unit?w=1", True),
        ("mongodb://unit-test.invalid/unit?w=majority", True),
        ("mongodb://unit-test.invalid/unit?w=majority&journal=true", True),
        ("mongodb://unit-test.invalid/unit?w=0", False),
    ],
)
def test_configured_uri_write_concern_reaches_the_database_handle(uri, acknowledged):
    # connect=False keeps the client lazy, so no socket or monitor is opened.
    client = AsyncMongoClient(uri, connect=False)
    assert client["unit"].write_concern.acknowledged is acknowledged


def test_uri_write_concern_is_not_overridden_by_the_session_collection():
    client = AsyncMongoClient(
        "mongodb://unit-test.invalid/unit?w=majority&journal=true", connect=False
    )
    database = client["unit"]
    sessions = runtime_module.MongoSessionRepository(database)._collection
    runs = runtime_module.MongoRunRepository(database)._collection
    assert sessions.write_concern == WriteConcern(w="majority", j=True)
    assert sessions.write_concern == database.write_concern
    assert runs.write_concern == database.write_concern
