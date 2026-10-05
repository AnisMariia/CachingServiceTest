import io
import json
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from caching_service import cli

RunCli = Callable[..., str]

BODY = {"list_1": ["a"], "list_2": ["b"]}


@pytest.fixture
def run_cli(
    sync_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> RunCli:
    # Route the CLI's HTTP calls into the in-process app instead of a real server.
    monkeypatch.setattr(httpx, "Client", lambda base_url, timeout: sync_client)

    def run(*args: str) -> str:
        monkeypatch.setattr(sys, "argv", ["cache-cli", *args])
        cli.main()
        return capsys.readouterr().out

    return run


def test_json_argument_repeated(run_cli: RunCli) -> None:
    out = json.loads(run_cli("--json", json.dumps(BODY), "--repeat", "2"))

    assert len(out) == 2
    assert out[0] == out[1]
    assert out[0]["output"] == "A, B"


def test_input_file_and_output_file(run_cli: RunCli, tmp_path: Path) -> None:
    source = tmp_path / "in.json"
    source.write_text(json.dumps(BODY))
    target = tmp_path / "out.json"

    run_cli("-i", str(source), "-o", str(target))

    assert json.loads(target.read_text())[0]["output"] == "A, B"


def test_stdin_input(run_cli: RunCli, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(BODY)))

    assert json.loads(run_cli("-i", "-"))[0]["output"] == "A, B"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--json", "{}", "--input", "-"],
        ["--json", "{}", "--repeat", "0"],
        ["--json", "{}", "--host", "ftp://x"],
    ],
    ids=["no-input", "both-inputs", "zero-repeat", "bad-host-scheme"],
)
def test_invalid_arguments_exit_with_error(run_cli: RunCli, args: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        run_cli(*args)

    assert error.value.code != 0


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        json.dumps({"list_1": ["a"], "list_2": ["b", "c"]}),
        json.dumps({"list_1": [], "list_2": []}),
    ],
    ids=["malformed-json", "missing-lists", "unequal-lengths", "empty-lists"],
)
def test_invalid_body_exits_before_any_request(run_cli: RunCli, raw: str) -> None:
    with pytest.raises(SystemExit) as error:
        run_cli("--json", raw)

    assert str(error.value.code).startswith("Error:")


def test_missing_input_file_exits_with_message(run_cli: RunCli, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        run_cli("-i", str(tmp_path / "missing.json"))

    assert str(error.value.code).startswith("Error:")


def test_server_error_exits_with_message(
    run_cli: RunCli, sync_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(sync_client, "post", fail)

    with pytest.raises(SystemExit) as error:
        run_cli("--json", json.dumps(BODY))

    assert str(error.value.code).startswith("Request failed:")


def test_trailing_slash_is_stripped_from_host() -> None:
    settings = cli.CliSettings(_cli_parse_args=["-j", "{}", "-H", "http://host:8000/"])

    assert settings.host == "http://host:8000"
