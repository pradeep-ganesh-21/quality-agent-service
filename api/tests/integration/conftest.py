"""Guarded fixtures for the real-MongoDB integration suite.

These tests need a separately provisioned privileged test deployment. They never
touch the runtime application database, and cleanup can only drop the one
isolated fixture database this module created.
"""

import asyncio
import os
import re
from datetime import timezone
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import InvalidURI
from pymongo.uri_parser import parse_uri

BASE_DATABASE_NAME = "quality_agent_test"
FIXTURE_DATABASE = re.compile(r"quality_agent_test_[0-9a-f]{32}")


def _fail(reason: str) -> None:
    # Configuration problems must never echo a URI or its credentials.
    pytest.fail(f"Integration tests require a guarded test deployment: {reason}", pytrace=False)


@pytest.fixture(scope="session")
def test_mongo_uri() -> str:
    uri = os.environ.get("TEST_MONGO_URI", "")
    if not uri:
        _fail("set TEST_MONGO_URI.")
    if os.environ.get("TEST_MONGO_BASE_DB_NAME", BASE_DATABASE_NAME) != BASE_DATABASE_NAME:
        _fail(f"TEST_MONGO_BASE_DB_NAME must equal {BASE_DATABASE_NAME}.")
    if uri == os.environ.get("MONGO_URI"):
        _fail("TEST_MONGO_URI must not equal the runtime MONGO_URI.")
    try:
        parsed = parse_uri(uri)
    except (InvalidURI, ValueError):
        _fail("TEST_MONGO_URI is not a valid MongoDB URI.")
    if parsed["database"] != BASE_DATABASE_NAME:
        _fail(f"the TEST_MONGO_URI default database must be exactly {BASE_DATABASE_NAME}.")
    if parsed["options"].get("authSource") != "admin":
        _fail("TEST_MONGO_URI must set authSource=admin.")
    return uri


def _client(uri: str) -> AsyncMongoClient:
    return AsyncMongoClient(
        uri,
        tz_aware=True,
        tzinfo=timezone.utc,
        serverSelectionTimeoutMS=5000,
        socketTimeoutMS=30000,
    )


@pytest.fixture
def run_against_database(test_mongo_uri):
    """Run one coroutine against a fresh isolated fixture database.

    The client is created and closed inside a single event loop because an async
    client must not be shared across loops.
    """
    name = f"{BASE_DATABASE_NAME}_{uuid4().hex}"
    if FIXTURE_DATABASE.fullmatch(name) is None:
        _fail("the generated fixture database name failed its guard.")
    created: list[str] = []

    def run(main):
        async def runner():
            client = _client(test_mongo_uri)
            try:
                created.append(name)
                return await main(client[name])
            finally:
                await client.close()

        return asyncio.run(runner())

    yield run

    for recorded in created[:1]:
        # Only the recorded, guard-matching name this fixture created is dropped.
        if FIXTURE_DATABASE.fullmatch(recorded) is None:
            continue
        asyncio.run(_drop(test_mongo_uri, recorded))


async def _drop(uri: str, name: str) -> None:
    client = _client(uri)
    try:
        await client.drop_database(name)
    finally:
        await client.close()
