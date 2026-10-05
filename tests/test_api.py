import uuid

import pytest

from caching_service import transformer

SAMPLE = {
    "list_1": ["first string", "second string", "third string"],
    "list_2": ["other string", "another string", "last string"],
}


@pytest.fixture(autouse=True)
def fast_transformer(monkeypatch):
    monkeypatch.setattr(transformer, "LATENCY_SECONDS", 0)


def test_sample_roundtrip(client):
    created = client.post("/payload", json=SAMPLE)
    assert created.status_code == 201

    fetched = client.get(f"/payload/{created.json()['id']}")

    assert fetched.status_code == 200
    assert fetched.json() == {
        "output": "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, "
        "THIRD STRING, LAST STRING"
    }


def test_repeated_post_returns_same_id(client):
    first = client.post("/payload", json=SAMPLE).json()
    second = client.post("/payload", json=SAMPLE).json()

    assert first == second


def test_unknown_id_is_404(client):
    assert client.get(f"/payload/{uuid.uuid4()}").status_code == 404


def test_malformed_id_is_422(client):
    assert client.get("/payload/not-a-uuid").status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"list_1": ["a"], "list_2": ["b", "c"]},
        {"list_1": [], "list_2": []},
        {"list_1": ["a"]},
    ],
)
def test_invalid_body_is_422(client, body):
    assert client.post("/payload", json=body).status_code == 422
