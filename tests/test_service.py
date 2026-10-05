import uuid

from caching_service import service


class CountingTransformer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> str:
        self.calls.append(text)
        return text.upper()


def test_interleave():
    assert service.interleave(["a", "b"], ["x", "y"]) == ["a", "x", "b", "y"]


def test_output_is_interleaved_and_transformed(session):
    payload_id = service.create_payload(session, ["a", "b"], ["x", "y"], CountingTransformer())

    assert service.get_payload_output(session, payload_id) == "A, X, B, Y"


def test_duplicate_strings_are_transformed_once(session):
    transformer = CountingTransformer()

    service.create_payload(session, ["a", "a"], ["a", "b"], transformer)

    assert sorted(transformer.calls) == ["a", "b"]


def test_cached_strings_are_not_transformed_again(session):
    transformer = CountingTransformer()
    service.create_payload(session, ["a"], ["b"], transformer)

    service.create_payload(session, ["b", "c"], ["a", "a"], transformer)

    assert sorted(transformer.calls) == ["a", "b", "c"]


def test_same_input_reuses_payload_id(session):
    transformer = CountingTransformer()
    first = service.create_payload(session, ["a"], ["b"], transformer)
    calls_after_first = len(transformer.calls)

    second = service.create_payload(session, ["a"], ["b"], transformer)

    assert first == second
    assert len(transformer.calls) == calls_after_first


def test_different_input_gets_different_id(session):
    first = service.create_payload(session, ["a"], ["b"], CountingTransformer())
    second = service.create_payload(session, ["b"], ["a"], CountingTransformer())

    assert first != second


def test_unknown_payload_returns_none(session):
    assert service.get_payload_output(session, uuid.uuid4()) is None
