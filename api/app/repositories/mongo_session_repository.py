from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from re import escape
from typing import Any

from bson.errors import InvalidDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DocumentTooLarge, OperationFailure, PyMongoError

from app.domain import SessionStatus
from app.errors import ApplicationError, ErrorCode
from app.repositories.mongo_read_errors import translate_read_errors
from app.repositories.object_ids import parse_object_id
from app.repositories.protocols import (
    PageAnchor,
    PageDirection,
    PagePosition,
    SessionFilters,
    SessionListQuery,
    SessionPage,
    SessionRecord,
)

_SESSION_DETAIL_PROJECTION = {
    "_id": 1,
    "schema_version": 1,
    "started_at": 1,
    "received_at": 1,
    "status": 1,
    "completion_time": 1,
    "last_step_executed": 1,
    "execution_outcome": 1,
    "metadata": 1,
}
# The list sort key is always read so cursors can be minted, and is projected
# separately from the caller's selected fields.
_LIST_ANCHOR_PROJECTION = {"_id": 1, "started_at": 1}
_NOT_AN_ARRAY = {"$not": {"$type": "array"}}


def _session_record(document: dict[str, Any]) -> SessionRecord:
    record = dict(document)
    record["session_id"] = str(record.pop("_id"))
    return record


def _list_record(
    document: dict[str, Any], keep_started_at: bool
) -> tuple[SessionRecord, PageAnchor]:
    record = dict(document)
    started_at = record.get("started_at")
    if not isinstance(started_at, datetime):
        # Without the stored sort key a page cannot be anchored. Treat the record
        # as corrupt rather than emitting a cursor that skips or repeats rows.
        raise ApplicationError(ErrorCode.INTERNAL_ERROR)
    if not keep_started_at:
        del record["started_at"]
    session_id = str(record.pop("_id"))
    record["session_id"] = session_id
    return record, PageAnchor(started_at=started_at, session_id=session_id)


def _filter_spec(filters: SessionFilters) -> dict[str, Any]:
    """Build the list filter.

    Server-owned root fields hold known scalar types. Metadata filters are
    applied to arbitrary stored JSON, so they additionally require a non-array
    value: an ordinary field predicate would otherwise match array elements.
    """
    spec: dict[str, Any] = {}
    if filters.status is not None:
        spec["status"] = filters.status
    started_at: dict[str, Any] = {}
    if filters.started_from is not None:
        started_at["$gte"] = filters.started_from
    if filters.started_before is not None:
        started_at["$lt"] = filters.started_before
    if started_at:
        spec["started_at"] = started_at
    if filters.boundary_contains is not None:
        # Escaped text matches literally, and $regex matches string values only.
        spec["metadata.boundary"] = {
            "$regex": escape(filters.boundary_contains),
            "$options": "i",
            **_NOT_AN_ARRAY,
        }
    if filters.invoked_by_email is not None:
        # An array of identity objects must not match through path traversal.
        spec["metadata.invoked_by"] = dict(_NOT_AN_ARRAY)
        spec["metadata.invoked_by.email"] = {
            "$eq": filters.invoked_by_email,
            **_NOT_AN_ARRAY,
        }
    return spec


def _position_spec(position: PagePosition) -> dict[str, Any]:
    """Exclude everything up to and including one page boundary."""
    object_id = parse_object_id(position.session_id)
    if object_id is None:
        raise ApplicationError(ErrorCode.INVALID_FIELD)
    operator = "$lt" if position.direction == "next" else "$gt"
    return {
        "$or": [
            {"started_at": {operator: position.started_at}},
            {"started_at": position.started_at, "_id": {operator: object_id}},
        ]
    }


def _read_spec(
    filter_spec: Mapping[str, Any], position: PagePosition | None
) -> dict[str, Any]:
    if position is None:
        return dict(filter_spec)
    position_spec = _position_spec(position)
    if not filter_spec:
        return position_spec
    # $and keeps a started_at range filter from colliding with the boundary.
    return {"$and": [dict(filter_spec), position_spec]}


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
        # The collection inherits the configured write concern. Startup rejects
        # an unacknowledged setting, which patch cannot report through matched_count.
        self._collection = database["sessions"]

    async def create(self, values: Mapping[str, Any]) -> str:
        document = deepcopy(dict(values))
        with _translate_mongo_errors():
            result = await self._collection.insert_one(document)
        return str(result.inserted_id)

    async def get(self, session_id: str) -> SessionRecord | None:
        object_id = parse_object_id(session_id)
        if object_id is None:
            return None
        with translate_read_errors():
            document = await self._collection.find_one(
                {"_id": object_id}, _SESSION_DETAIL_PROJECTION
            )
        return None if document is None else _session_record(document)

    async def list_page(self, query: SessionListQuery) -> SessionPage:
        filter_spec = _filter_spec(query.filters)
        projection = dict(_LIST_ANCHOR_PROJECTION)
        projection.update(
            {
                field: 1
                for field in query.fields
                if field not in _LIST_ANCHOR_PROJECTION and field != "session_id"
            }
        )
        # Paging backward reads ascending from the boundary, then restores the
        # response to the newest-first order.
        backward = query.position is not None and query.position.direction == "previous"
        order = 1 if backward else -1
        with translate_read_errors():
            # The count covers every filter match and is read separately from the
            # page, so the two can disagree while sessions are being updated.
            total_count = await self._collection.count_documents(filter_spec)
            async with self._collection.find(
                _read_spec(filter_spec, query.position), projection
            ).sort([("started_at", order), ("_id", order)]) as cursor:
                documents = await cursor.to_list(length=query.page_size + 1)
            # One extra record only reveals whether the travelled direction continues.
            beyond = len(documents) > query.page_size
            del documents[query.page_size :]
            if backward:
                documents.reverse()
            if not documents:
                return SessionPage(items=[], total_count=total_count)

            keep_started_at = "started_at" in query.fields
            mapped = [_list_record(document, keep_started_at) for document in documents]
            newest, oldest = mapped[0][1], mapped[-1][1]
            has_newer = beyond if backward else False
            has_older = False if backward else beyond
            # The opposite direction needs its own check because the anchored
            # record may no longer match the filters.
            if backward:
                has_older = await self._reaches(filter_spec, oldest, "next")
            elif query.position is not None:
                has_newer = await self._reaches(filter_spec, newest, "previous")
        return SessionPage(
            items=[record for record, _ in mapped],
            total_count=total_count,
            newest=newest,
            oldest=oldest,
            has_newer=has_newer,
            has_older=has_older,
        )

    async def _reaches(
        self,
        filter_spec: Mapping[str, Any],
        anchor: PageAnchor,
        direction: PageDirection,
    ) -> bool:
        position = PagePosition(
            started_at=anchor.started_at,
            session_id=anchor.session_id,
            direction=direction,
        )
        document = await self._collection.find_one(
            _read_spec(filter_spec, position), {"_id": 1}
        )
        return document is not None

    async def patch_open_session(
        self,
        session_id: str,
        known: Mapping[str, Any],
        extras: Mapping[str, Any],
    ) -> str:
        object_id = parse_object_id(session_id)
        if object_id is None:
            raise ApplicationError(ErrorCode.SESSION_NOT_FOUND)

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
