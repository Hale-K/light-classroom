"""租户隔离的 RAG 知识库、文档和文本分块。"""
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import Column, Index, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.db.base import TenantMixin, TimestampMixin


class KnowledgeBase(TimestampMixin, TenantMixin, SQLModel, table=True):
    __tablename__ = "knowledge_base"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_knowledge_base_tenant_name"),)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=120)
    description: str = Field(default="", sa_column=Column(Text, nullable=False))
    embedding_model: str = Field(default="bge-base-zh-v1.5", max_length=100)
    enabled: bool = Field(default=True, index=True)
    created_by: int | None = Field(default=None, index=True)


class KnowledgeDocument(TimestampMixin, TenantMixin, SQLModel, table=True):
    __tablename__ = "knowledge_document"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "content_hash", name="uq_knowledge_document_hash"),)

    id: int | None = Field(default=None, primary_key=True)
    knowledge_base_id: int = Field(index=True, foreign_key="knowledge_base.id")
    file_name: str = Field(max_length=255)
    content_type: str = Field(default="text/plain", max_length=120)
    content_hash: str = Field(max_length=64)
    file_size: int = Field(default=0, ge=0)
    status: str = Field(default="queued", max_length=16, index=True)
    chunk_count: int = Field(default=0, ge=0)
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_by: int | None = Field(default=None, index=True)


class KnowledgeChunk(TimestampMixin, TenantMixin, SQLModel, table=True):
    __tablename__ = "knowledge_chunk"
    __table_args__ = (
        Index("ix_knowledge_chunk_base", "tenant_id", "knowledge_base_id"),
        Index("ix_knowledge_chunk_embedding_hnsw", "embedding",
              postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    id: int | None = Field(default=None, primary_key=True)
    knowledge_base_id: int = Field(index=True, foreign_key="knowledge_base.id")
    document_id: int = Field(index=True, foreign_key="knowledge_document.id")
    chunk_index: int = Field(ge=0)
    content: str = Field(sa_column=Column(Text, nullable=False))
    source_locator: str = Field(default="", max_length=255)
    embedding: list[float] | None = Field(default=None, sa_column=Column(VECTOR(768), nullable=True))
    embedding_model: str = Field(default="bge-base-zh-v1.5", max_length=100)

