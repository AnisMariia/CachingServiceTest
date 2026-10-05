import uuid

import httpx
import pytest

from caching_service.schemas import MAX_LIST_LENGTH, MAX_STRING_LENGTH

SAMPLE = {
    "list_1": ["first string", "second string", "third string"],
    "list_2": ["other string", "another string", "last string"],
}


async def test_sample_roundtrip(client: httpx.AsyncClient) -> None:
    created = await client.post("/payload", json=SAMPLE)
    assert created.status_code == 201

    fetched = await client.get(f"/payload/{created.json()['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == {
        "output": "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, "
        "THIRD STRING, LAST STRING"
    }


async def test_repeated_post_returns_same_id(client: httpx.AsyncClient) -> None:
    first = (await client.post("/payload", json=SAMPLE)).json()
    second = (await client.post("/payload", json=SAMPLE)).json()

    assert first == second


async def test_unknown_id_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"/payload/{uuid.uuid4()}")).status_code == 404


async def test_malformed_id_is_422(client: httpx.AsyncClient) -> None:
    assert (await client.get("/payload/not-a-uuid")).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"list_1": ["a"], "list_2": ["b", "c"]},
        {"list_1": [], "list_2": []},
        {"list_1": ["a"]},
        {"list_2": ["a"]},
        {},
        {"list_1": "a", "list_2": "b"},
        {"list_1": [1], "list_2": ["b"]},
        {"list_1": [None], "list_2": ["b"]},
        {
            "list_1": ["a"] * (MAX_LIST_LENGTH + 1),
            "list_2": ["b"] * (MAX_LIST_LENGTH + 1),
        },
        {"list_1": ["a" * (MAX_STRING_LENGTH + 1)], "list_2": ["b"]},
    ],
    ids=[
        "unequal-length",
        "empty-lists",
        "missing-list_2",
        "missing-list_1",
        "empty-body",
        "not-lists",
        "non-string-item",
        "null-item",
        "too-many-items",
        "too-long-string",
    ],
)
async def test_invalid_body_is_422(client: httpx.AsyncClient, body: dict[str, object]) -> None:
    assert (await client.post("/payload", json=body)).status_code == 422


async def test_limits_are_inclusive(client: httpx.AsyncClient) -> None:
    body = {"list_1": ["a" * MAX_STRING_LENGTH], "list_2": ["b"]}

    assert (await client.post("/payload", json=body)).status_code == 201


async def test_different_payloads_get_different_ids(client: httpx.AsyncClient) -> None:
    first = (await client.post("/payload", json={"list_1": ["a"], "list_2": ["b"]})).json()
    second = (await client.post("/payload", json={"list_1": ["b"], "list_2": ["a"]})).json()

    assert first != second
