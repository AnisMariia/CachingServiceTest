"""Command line client for testing the service."""

import json
import sys
from pathlib import Path
from typing import Annotated

import httpx
from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, CliApp, SettingsConfigDict

from caching_service.schemas import PayloadCreate

STDIO = "-"


class CliSettings(BaseSettings):
    """Arguments are parsed and validated by pydantic-settings."""

    # `-h` is taken by --help (argparse), so the short flag for the host is `-H`.
    model_config = SettingsConfigDict(
        cli_parse_args=True, cli_prog_name="cache-cli", case_sensitive=True
    )

    host: Annotated[
        str,
        Field(
            validation_alias=AliasChoices("H", "host"),
            description="Base URL of the server",
        ),
    ] = "http://127.0.0.1:8000"
    repeat: Annotated[
        int,
        Field(
            ge=1,
            validation_alias=AliasChoices("r", "repeat"),
            description="Number of iterations",
        ),
    ] = 1
    input: Annotated[
        str | None,
        Field(
            validation_alias=AliasChoices("i", "input"),
            description="Input JSON file, or - for stdin",
        ),
    ] = None
    json_: Annotated[
        str | None,
        Field(
            validation_alias=AliasChoices("j", "json"),
            description='Input as a JSON string: {"list_1": [...], "list_2": [...]}',
        ),
    ] = None
    output: Annotated[
        str,
        Field(
            validation_alias=AliasChoices("o", "output"),
            description="Output file, or - for stdout",
        ),
    ] = STDIO

    @field_validator("host")
    @classmethod
    def _check_host(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value.rstrip("/")

    @model_validator(mode="after")
    def _check_single_input(self) -> "CliSettings":
        if (self.input is None) == (self.json_ is None):
            raise ValueError("provide exactly one of --input and --json")
        return self

    def read_body(self) -> PayloadCreate:
        if self.json_ is not None:
            raw = self.json_
        elif self.input == STDIO:
            raw = sys.stdin.read()
        else:
            raw = Path(self.input).read_text()
        return PayloadCreate.model_validate_json(raw)

    def cli_cmd(self) -> None:
        body = self.read_body()
        results = []
        with httpx.Client(base_url=self.host, timeout=30) as client:
            for _ in range(self.repeat):
                created = client.post("/payload", json=body.model_dump())
                created.raise_for_status()
                payload_id = created.json()["id"]
                fetched = client.get(f"/payload/{payload_id}")
                fetched.raise_for_status()
                results.append({"id": payload_id, **fetched.json()})

        text = json.dumps(results, indent=2) + "\n"
        if self.output == STDIO:
            sys.stdout.write(text)
        else:
            Path(self.output).write_text(text)


def main() -> None:
    try:
        CliApp.run(CliSettings)
    except httpx.HTTPError as error:
        sys.exit(f"Request failed: {error}")
    except (OSError, ValueError) as error:
        sys.exit(f"Error: {error}")
