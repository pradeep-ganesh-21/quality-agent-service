from datetime import datetime

from pymongo.asynchronous.database import AsyncDatabase

from app.errors import ApplicationError, ErrorCode
from app.repositories.mongo_read_errors import translate_read_errors
from app.repositories.object_ids import parse_object_id
from app.repositories.protocols import RunRecord

_RUN_PROJECTION = {
    "_id": 1,
    "session_id": 1,
    "schema_version": 1,
    "step": 1,
    "command": 1,
    "verdict": 1,
    "occurred_at": 1,
    "received_at": 1,
    "details": 1,
    "deleted_at": 1,
}


class MongoRunRepository:
    def __init__(self, database: AsyncDatabase) -> None:
        self._collection = database["runs"]

    async def list_for_session(self, session_id: str) -> list[RunRecord]:
        object_id = parse_object_id(session_id)
        if object_id is None:
            raise ApplicationError(ErrorCode.SESSION_NOT_FOUND)
        with translate_read_errors():
            async with self._collection.find(
                {"session_id": object_id}, _RUN_PROJECTION
            ).sort([("occurred_at", 1), ("_id", 1)]) as cursor:
                documents = await cursor.to_list(length=None)
        records = []
        for document in documents:
            record = dict(document)
            record["run_id"] = str(record.pop("_id"))
            record["session_id"] = str(record["session_id"])
            # Runs written before soft delete existed lack the field.
            record.setdefault("deleted_at", None)
            records.append(record)
        return records

    async def soft_delete_for_session(self, session_id: str, deleted_at: datetime) -> int:
        object_id = parse_object_id(session_id)
        if object_id is None:
            return 0
        # Null equality also matches a missing field. Stamped runs keep their timestamp.
        with translate_read_errors():
            result = await self._collection.update_many(
                {"session_id": object_id, "deleted_at": None},
                {"$set": {"deleted_at": deleted_at}},
                upsert=False,
            )
        return result.matched_count
