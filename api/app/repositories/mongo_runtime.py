from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timezone

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.repositories.indexes import ensure_indexes
from app.repositories.mongo_run_repository import MongoRunRepository
from app.repositories.mongo_session_repository import MongoSessionRepository
from app.repositories.protocols import RunRepository, SessionRepository


@dataclass(frozen=True)
class MongoRepositories:
    sessions: SessionRepository
    runs: RunRepository


@asynccontextmanager
async def mongo_runtime(uri: str, database_name: str) -> AsyncIterator[MongoRepositories]:
    client = AsyncMongoClient(
        uri,
        tz_aware=True,
        tzinfo=timezone.utc,
        serverSelectionTimeoutMS=5000,
        socketTimeoutMS=30000,
    )
    try:
        try:
            await client.admin.command("ping")
            await ensure_indexes(client[database_name])
        except PyMongoError:
            raise RuntimeError(
                "MongoDB startup failed; check availability, credentials, and indexes."
            ) from None
        database = client[database_name]
        yield MongoRepositories(
            sessions=MongoSessionRepository(database),
            runs=MongoRunRepository(database),
        )
    finally:
        await client.close()
