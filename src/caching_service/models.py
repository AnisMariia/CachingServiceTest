"""Database tables."""

import uuid

from sqlalchemy import String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SHA256_HEX_LENGTH = 64


class Base(DeclarativeBase):
    pass


class CachedTransformation(Base):
    """Result of one transformer call, kept so the same string is never transformed twice."""

    __tablename__ = "cached_transformations"

    # The hash is the key instead of the text itself: PostgreSQL B-tree entries
    # are limited to roughly 2.7 kB, while source strings may be longer.
    source_hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    transformed: Mapped[str] = mapped_column(Text)


class Payload(Base):
    """A generated payload. The output is stored whole so reads never touch the cache."""

    __tablename__ = "payloads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Unique hash of the output: this is what makes identical payloads share one id.
    fingerprint: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH), unique=True)
    output: Mapped[str] = mapped_column(Text)
