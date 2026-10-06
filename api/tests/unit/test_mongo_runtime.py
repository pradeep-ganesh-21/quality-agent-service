import asyncio
from datetime import timezone

import pytest
from pymongo.errors import ConnectionFailure

from app.repositories import mongo_runtime as runtime_module


@pytest.mark.parametrize("fail_startup", [False, True])
def test_mongo_runtime_pings_indexes_and_closes(monkeypatch, fail_startup):
    events = []
    database = object()

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

    async def ensure_indexes(value):
        assert value is database
        events.append("indexes")

    monkeypatch.setattr(runtime_module, "AsyncMongoClient", Client)
    monkeypatch.setattr(runtime_module, "ensure_indexes", ensure_indexes)

    async def exercise():
        async with runtime_module.mongo_runtime("mongodb://unit-test.invalid", "unit"):
            events.append("running")

    if fail_startup:
        with pytest.raises(RuntimeError, match="MongoDB startup failed") as error:
            asyncio.run(exercise())
        assert "sensitive connection details" not in str(error.value)
        assert events == ["ping", "close"]
    else:
        asyncio.run(exercise())
        assert events == ["ping", "indexes", "running", "close"]
