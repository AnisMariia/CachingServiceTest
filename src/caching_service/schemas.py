"""Request and response bodies of the HTTP API."""

import uuid
from typing import Annotated, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

# Bounds keep a single request from producing an unbounded number of
# transformer calls or an oversized SQL statement.
MAX_LIST_LENGTH = 1000
MAX_STRING_LENGTH = 10_000

SourceString = Annotated[str, StringConstraints(max_length=MAX_STRING_LENGTH)]
SourceList = Annotated[list[SourceString], Field(min_length=1, max_length=MAX_LIST_LENGTH)]


class PayloadCreate(BaseModel):
    list_1: SourceList
    list_2: SourceList

    @model_validator(mode="after")
    def check_equal_length(self) -> Self:
        if len(self.list_1) != len(self.list_2):
            raise ValueError("list_1 and list_2 must have the same length")
        return self


class PayloadCreated(BaseModel):
    id: uuid.UUID


class PayloadRead(BaseModel):
    output: str
