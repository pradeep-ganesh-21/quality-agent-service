from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from typing import Any

from bson import ObjectId
from bson.errors import InvalidDocument, InvalidId
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DocumentTooLarge, OperationFailure, PyMongoError
from pymongo.write_concern import WriteConcern

from app.domain import SessionStatus
from app.errors import ApplicationError, ErrorCode


@contextmanager
def _translate_mongo_errors() -> Iterator[None]:
    try:
        yield
    except DocumentTooLarge:
        raise ApplicationError(ErrorCode.DOCUMENT_TOO_LARGE) from None
    except (InvalidDocument, UnicodeEncodeError, OverflowError):
        raise ApplicationError(ErrorCode.INVALID_FIELD) from None
    except OperationFailure as error:
        if error.code in {10334, 17419}:
            raise ApplicationError(ErrorCode.DOCUMENT_TOO_LARGE) from None
        raise ApplicationError(ErrorCode.INTERNAL_ERROR) from None
    except PyMongoError:
        raise ApplicationError(ErrorCode.INTERNAL_ERROR) from None


class MongoSessionRepository:
    def __init__(self, database: AsyncDatabase) -> None:
        self._collection = database.get_collection(
            "sessions", write_concern=WriteConcern(w=1)
        )

    async def create(self, values: Mapping[str, Any]) -> str:
        document = deepcopy(dict(values))
        with _translate_mongo_errors():
            result = await self._collection.insert_one(document)
        return str(result.inserted_id)

    async def patch_open_session(
        self,
        session_id: str,
        known: Mapping[str, Any],
        extras: Mapping[str, Any],
    ) -> str:
        try:
            object_id = ObjectId(session_id)
        except (InvalidId, TypeError):
            raise ApplicationError(ErrorCode.SESSION_NOT_FOUND) from None

        set_spec = {
            key: {"$literal": deepcopy(value)} for key, value in known.items()
        }
        set_spec["metadata"] = {
            "$mergeObjects": [
                {"$ifNull": ["$metadata", {"$literal": {}}]},
                {"$literal": deepcopy(dict(extras))},
            ]
        }
        with _translate_mongo_errors():
            result = await self._collection.update_one(
                {"_id": object_id, "status": SessionStatus.IN_PROGRESS.value},
                [{"$set": set_spec}],
                upsert=False,
            )
            if result.matched_count == 1:
                return str(object_id)
            existing = await self._collection.find_one({"_id": object_id}, {"_id": 1})
            if existing is None:
                raise ApplicationError(ErrorCode.SESSION_NOT_FOUND)
            raise ApplicationError(ErrorCode.SESSION_NOT_OPEN)
