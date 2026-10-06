from pymongo.asynchronous.database import AsyncDatabase


async def ensure_indexes(database: AsyncDatabase) -> None:
    await database["sessions"].create_index(
        [("started_at", -1), ("_id", -1)], name="sessions_started_desc_idx"
    )
    await database["runs"].create_index(
        [("session_id", 1), ("occurred_at", 1), ("_id", 1)],
        name="runs_session_occurred_idx",
    )
