from bson import ObjectId
from bson.errors import InvalidId


def parse_object_id(value: object) -> ObjectId | None:
    """Return the ObjectId for a 24-character hexadecimal string, otherwise None.

    Non-string input is rejected before conversion because `ObjectId(None)`
    generates a new identifier instead of failing, and `ObjectId` accepts bytes
    and existing ObjectIds that the string identifier contract does not allow.
    """
    if not isinstance(value, str):
        return None
    try:
        return ObjectId(value)
    except InvalidId:
        return None
