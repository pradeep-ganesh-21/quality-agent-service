from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from bson.errors import InvalidDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DocumentTooLarge, OperationFailure, PyMongoError
from pymongo.write_concern import WriteConcern

from app.errors import ApplicationError, ErrorCode


class MongoSessionRepository:
    def __init__(self, database: AsyncDatabase) -> None:
        self._collection = database.get_collection(
            "sessions", write_concern=WriteConcern(w=1)
        )

    async def create(self, values: Mapping[str, Any]) -> str:
        document = deepcopy(dict(values))
        try:
            result = await self._collection.insert_one(document)
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
        return str(result.inserted_id)
