from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timezone

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.repositories.indexes import ensure_indexes


@asynccontextmanager
async def mongo_runtime(uri: str, database_name: str) -> AsyncIterator[None]:
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
        yield
    finally:
        await client.close()
