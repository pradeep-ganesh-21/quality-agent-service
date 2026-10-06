from collections.abc import Iterator
from contextlib import contextmanager

from bson.errors import BSONError
from pymongo.errors import PyMongoError

from app.errors import ApplicationError, ErrorCode


@contextmanager
def translate_read_errors() -> Iterator[None]:
    try:
        yield
    except (PyMongoError, BSONError):
        raise ApplicationError(ErrorCode.INTERNAL_ERROR) from None
