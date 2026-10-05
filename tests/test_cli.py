import json
import sys

import pytest

from caching_service import cli

BODY = {"list_1": ["a"], "list_2": ["b"]}


@pytest.fixture
def run_cli(sync_client, monkeypatch, capsys):
    # Route the CLI's HTTP calls into the in-process app instead of a real server.
    monkeypatch.setattr(
        cli.httpx, "Client", lambda base_url, timeout: sync_client
    )

    def run(*args: str):
        monkeypatch.setattr(sys, "argv", ["cache-cli", *args])
        cli.main()
        return capsys.readouterr().out

    return run


def test_json_argument_repeated(run_cli):
    out = json.loads(run_cli("--json", json.dumps(BODY), "--repeat", "2"))

    assert len(out) == 2
    assert out[0] == out[1]
    assert out[0]["output"] == "A, B"


def test_input_file_and_output_file(run_cli, tmp_path):
    source = tmp_path / "in.json"
    source.write_text(json.dumps(BODY))
    target = tmp_path / "out.json"

    run_cli("-i", str(source), "-o", str(target))

    assert json.loads(target.read_text())[0]["output"] == "A, B"


def test_stdin_input(run_cli, monkeypatch):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(BODY)))

    assert json.loads(run_cli("-i", "-"))[0]["output"] == "A, B"


@pytest.mark.parametrize(
    "args",
    [[], ["--json", "{}", "--input", "-"], ["--json", "{}", "--repeat", "0"], ["--json", "not json"]],
)
def test_invalid_arguments_exit(run_cli, args):
    with pytest.raises(SystemExit):
        run_cli(*args)
