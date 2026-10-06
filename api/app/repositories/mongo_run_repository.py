from bson import ObjectId
from bson.errors import InvalidId
from pymongo.asynchronous.database import AsyncDatabase

from app.errors import ApplicationError, ErrorCode
from app.repositories.mongo_read_errors import translate_read_errors
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
}


class MongoRunRepository:
    def __init__(self, database: AsyncDatabase) -> None:
        self._collection = database["runs"]

    async def list_for_session(self, session_id: str) -> list[RunRecord]:
        try:
            object_id = ObjectId(session_id)
        except (InvalidId, TypeError):
            raise ApplicationError(ErrorCode.SESSION_NOT_FOUND) from None
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
            records.append(record)
        return records
