"""Persistent semantic examples used to route assistant turns."""
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel


class AiIntentExample(SQLModel, table=True):
    __tablename__ = "ai_intent_example"
    __table_args__ = (
        UniqueConstraint("intent", "utterance", name="uq_ai_intent_example_intent_utterance"),
    )

    id: int | None = Field(default=None, primary_key=True)
    intent: str = Field(index=True, max_length=32)
    utterance: str = Field(max_length=500)
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(VECTOR(768), nullable=True),
    )
    embedding_model: str = Field(default="bge-base-zh-v1.5", max_length=100)
    enabled: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
