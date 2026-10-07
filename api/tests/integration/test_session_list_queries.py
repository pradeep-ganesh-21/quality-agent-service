"""Pin list filtering and cursor pagination against a real MongoDB server.

These behaviors depend on server semantics that mocks cannot reproduce: array
path traversal, case-insensitive regular expressions, and reverse-ordered reads.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.repositories.indexes import ensure_indexes
from app.repositories.mongo_session_repository import MongoSessionRepository
from app.services.session_listing import (
    build_session_list_result,
    parse_session_list_request,
)

pytestmark = pytest.mark.integration

START = datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)


def session_document(started_at, status="COMPLETED", metadata=None):
    return {
        "schema_version": 1,
        "started_at": started_at,
        "received_at": started_at,
        "status": status,
        "completion_time": None,
        "last_step_executed": [],
        "execution_outcome": None,
        "metadata": {} if metadata is None else metadata,
    }


async def seed(database, documents):
    await ensure_indexes(database)
    repository = MongoSessionRepository(database)
    return [await repository.create(document) for document in documents]


async def fetch(database, **parameters):
    repository = MongoSessionRepository(database)
    request = parse_session_list_request(
        [(name, value) for name, value in parameters.items() if value is not None]
    )
    page = await repository.list_page(request.query)
    return build_session_list_result(request, page)


def identifiers(result):
    return [record["session_id"] for record in result.items]


def test_boundary_filter_matches_literal_text_without_regard_to_case(run_against_database):
    async def main(database):
        ids = await seed(database, [
            session_document(START, metadata={"boundary": "payments-api"}),
            session_document(START - timedelta(minutes=1), metadata={"boundary": "PAYMENTS"}),
            session_document(START - timedelta(minutes=2), metadata={"boundary": "checkout"}),
            session_document(START - timedelta(minutes=3), metadata={"boundary": "pay.ments"}),
        ])
        literal = await fetch(database, fields="session_id", boundary="payments")
        escaped = await fetch(database, fields="session_id", boundary="pay.ments")
        return ids, identifiers(literal), identifiers(escaped)

    ids, literal, escaped = run_against_database(main)
    assert literal == [ids[0], ids[1]]
    # An unescaped pattern would let "pay.ments" match "payments-api".
    assert escaped == [ids[3]]


@pytest.mark.parametrize(
    "boundary",
    [["payments"], ["other", "payments"], {"name": "payments"}, 17, None, "other"],
)
def test_only_scalar_boundary_strings_match(run_against_database, boundary):
    async def main(database):
        await seed(database, [
            session_document(START, metadata={} if boundary is None else {"boundary": boundary}),
        ])
        return identifiers(await fetch(database, fields="session_id", boundary="payments"))

    assert run_against_database(main) == []


def test_invoked_by_email_matches_exact_scalar_values_only(run_against_database):
    async def main(database):
        ids = await seed(database, [
            session_document(START, metadata={"invoked_by": {"email": "ops@example.invalid"}}),
            session_document(
                START - timedelta(minutes=1),
                metadata={"invoked_by": {"email": "OPS@EXAMPLE.INVALID"}},
            ),
            session_document(
                START - timedelta(minutes=2),
                metadata={"invoked_by": [{"email": "ops@example.invalid"}]},
            ),
            session_document(
                START - timedelta(minutes=3),
                metadata={"invoked_by": {"email": ["ops@example.invalid"]}},
            ),
            session_document(
                START - timedelta(minutes=4), metadata={"invoked_by": "ops@example.invalid"},
            ),
            session_document(START - timedelta(minutes=5), metadata={}),
        ])
        result = await fetch(
            database, fields="session_id", invoked_by_email="ops@example.invalid"
        )
        return ids, identifiers(result), result.total_count

    ids, matched, total_count = run_against_database(main)
    # Case differences, arrays, traversal, and non-object identities never match.
    assert matched == [ids[0]]
    assert total_count == 1


def test_an_operator_shaped_email_is_treated_as_data(run_against_database):
    async def main(database):
        ids = await seed(database, [
            session_document(START, metadata={"invoked_by": {"email": "$status"}}),
            session_document(START - timedelta(minutes=1), metadata={"invoked_by": {"email": "x"}}),
        ])
        return ids, identifiers(await fetch(database, fields="session_id", invoked_by_email="$status"))

    ids, matched = run_against_database(main)
    assert matched == [ids[0]]


def test_status_and_half_open_range_select_their_documented_sets(run_against_database):
    async def main(database):
        ids = await seed(database, [
            session_document(START, status="IN_PROGRESS"),
            session_document(START + timedelta(hours=1), status="COMPLETED"),
            session_document(START + timedelta(hours=2), status="FAILED"),
        ])
        window = await fetch(
            database,
            fields="session_id",
            started_from="2026-10-01T10:00:00Z",
            started_before="2026-10-01T11:00:00Z",
        )
        status = await fetch(database, fields="session_id", status="IN_PROGRESS")
        return ids, identifiers(window), identifiers(status)

    ids, window, status = run_against_database(main)
    # The start bound is inclusive and the end bound is exclusive.
    assert window == [ids[1]]
    assert status == [ids[0]]


def test_combined_filters_narrow_conjunctively(run_against_database):
    async def main(database):
        ids = await seed(database, [
            session_document(
                START, status="FAILED",
                metadata={"boundary": "payments", "invoked_by": {"email": "ops@example.invalid"}},
            ),
            session_document(
                START - timedelta(minutes=1), status="COMPLETED",
                metadata={"boundary": "payments", "invoked_by": {"email": "ops@example.invalid"}},
            ),
            session_document(
                START - timedelta(minutes=2), status="FAILED",
                metadata={"boundary": "checkout", "invoked_by": {"email": "ops@example.invalid"}},
            ),
        ])
        result = await fetch(
            database, fields="session_id", status="FAILED", boundary="payments",
            invoked_by_email="ops@example.invalid",
        )
        return ids, identifiers(result), result.total_count

    ids, matched, total_count = run_against_database(main)
    assert matched == [ids[0]]
    assert total_count == 1


def test_forward_traversal_visits_every_session_exactly_once(run_against_database):
    async def main(database):
        # Repeated start times force the identifier tie-break to carry paging.
        ids = await seed(database, [
            session_document(START - timedelta(minutes=index // 3)) for index in range(11)
        ])
        pages = []
        cursor = None
        while True:
            result = await fetch(database, fields="session_id", page_size="3", cursor=cursor)
            pages.append((identifiers(result), result.total_count, result.previous_cursor))
            cursor = result.next_cursor
            if cursor is None:
                break
            if len(pages) > 10:
                raise AssertionError("forward traversal did not terminate")
        return ids, pages

    ids, pages = run_against_database(main)
    visited = [session_id for page, _, _ in pages for session_id in page]
    # Server-generated ObjectIds increase with insertion order, so each equal
    # start time is ordered by descending identifier.
    assert visited == [
        ids[2], ids[1], ids[0],
        ids[5], ids[4], ids[3],
        ids[8], ids[7], ids[6],
        ids[10], ids[9],
    ]
    assert [len(page) for page, _, _ in pages] == [3, 3, 3, 2]
    assert all(total_count == 11 for _, total_count, _ in pages)
    assert pages[0][2] is None
    assert all(previous is not None for _, _, previous in pages[1:])



def test_ties_on_the_sort_key_order_by_descending_identifier(run_against_database):
    async def main(database):
        ids = await seed(database, [session_document(START) for _ in range(5)])
        return ids, identifiers(await fetch(database, fields="session_id"))

    ids, visited = run_against_database(main)
    assert visited == sorted(ids, reverse=True)


def test_previous_cursor_returns_the_preceding_page(run_against_database):
    async def main(database):
        await seed(database, [
            session_document(START - timedelta(minutes=index)) for index in range(9)
        ])
        first = await fetch(database, fields="session_id", page_size="3")
        second = await fetch(
            database, fields="session_id", page_size="3", cursor=first.next_cursor
        )
        third = await fetch(
            database, fields="session_id", page_size="3", cursor=second.next_cursor
        )
        back = await fetch(
            database, fields="session_id", page_size="3", cursor=third.previous_cursor
        )
        first_again = await fetch(
            database, fields="session_id", page_size="3", cursor=back.previous_cursor
        )
        return (
            [identifiers(page) for page in (first, second, third, back, first_again)],
            [page.next_cursor is None for page in (first, second, third)],
            first_again.previous_cursor,
        )

    pages, exhausted, top = run_against_database(main)
    assert pages[3] == pages[1]
    assert pages[4] == pages[0]
    assert exhausted == [False, False, True]
    assert top is None


def test_id_only_pages_do_not_leak_the_sort_key(run_against_database):
    async def main(database):
        await seed(database, [
            session_document(START - timedelta(minutes=index)) for index in range(4)
        ])
        first = await fetch(database, fields="session_id", page_size="2")
        second = await fetch(
            database, fields="session_id", page_size="2", cursor=first.next_cursor
        )
        return [set(record) for record in first.items + second.items], identifiers(second)

    keys, second = run_against_database(main)
    # The sort key is read for cursors but is not a selected response field.
    assert keys == [{"session_id"}] * 4
    assert len(second) == 2


def test_total_count_covers_all_matches_not_the_returned_page(run_against_database):
    async def main(database):
        await seed(database, [
            session_document(START - timedelta(minutes=index), status="COMPLETED")
            for index in range(7)
        ] + [session_document(START + timedelta(minutes=1), status="FAILED")])
        unfiltered = await fetch(database, fields="session_id", page_size="2")
        filtered = await fetch(
            database, fields="session_id", page_size="2", status="COMPLETED"
        )
        return (
            (unfiltered.total_count, len(unfiltered.items)),
            (filtered.total_count, len(filtered.items)),
        )

    assert run_against_database(main) == ((8, 2), (7, 2))


def test_selected_metadata_paths_survive_a_filtered_page(run_against_database):
    async def main(database):
        await seed(database, [
            session_document(
                START,
                metadata={
                    "boundary": "payments-api",
                    "invoked_by": {"name": "Operator", "email": "ops@example.invalid"},
                    "a.b": {"$set": "$status"},
                    "large": 9223372036854775807,
                },
            ),
        ])
        request = [
            ("fields", "metadata.boundary"),
            ("fields", "metadata.invoked_by.name"),
            ("boundary", "payments"),
        ]
        parsed = parse_session_list_request(request)
        page = await MongoSessionRepository(database).list_page(parsed.query)
        return build_session_list_result(parsed, page).items

    items = run_against_database(main)
    assert len(items) == 1
    assert items[0]["metadata"] == {
        "boundary": "payments-api", "invoked_by": {"name": "Operator"},
    }
    assert set(items[0]) == {"session_id", "metadata"}


def test_an_empty_result_is_a_terminal_page(run_against_database):
    async def main(database):
        await seed(database, [session_document(START, status="COMPLETED")])
        result = await fetch(database, fields="session_id", status="FAILED")
        return result.items, result.total_count, result.next_cursor, result.previous_cursor

    assert run_against_database(main) == ([], 0, None, None)
