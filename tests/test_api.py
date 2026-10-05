import uuid

import pytest

SAMPLE = {
    "list_1": ["first string", "second string", "third string"],
    "list_2": ["other string", "another string", "last string"],
}


async def test_sample_roundtrip(client):
    created = await client.post("/payload", json=SAMPLE)
    assert created.status_code == 201

    fetched = await client.get(f"/payload/{created.json()['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == {
        "output": "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, "
        "THIRD STRING, LAST STRING"
    }


async def test_repeated_post_returns_same_id(client):
    first = (await client.post("/payload", json=SAMPLE)).json()
    second = (await client.post("/payload", json=SAMPLE)).json()

    assert first == second


async def test_unknown_id_is_404(client):
    assert (await client.get(f"/payload/{uuid.uuid4()}")).status_code == 404


async def test_malformed_id_is_422(client):
    assert (await client.get("/payload/not-a-uuid")).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"list_1": ["a"], "list_2": ["b", "c"]},
        {"list_1": [], "list_2": []},
        {"list_1": ["a"]},
    ],
)
async def test_invalid_body_is_422(client, body):
    assert (await client.post("/payload", json=body)).status_code == 422
