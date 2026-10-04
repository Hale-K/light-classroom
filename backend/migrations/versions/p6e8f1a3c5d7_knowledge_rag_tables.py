"""add tenant-isolated RAG knowledge tables

Revision ID: p6e8f1a3c5d7
Revises: n5d7f9a2c4e6
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR

revision = "p6e8f1a3c5d7"
down_revision = "n5d7f9a2c4e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("knowledge_base"):
        op.create_table(
        "knowledge_base",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_knowledge_base_tenant_name"),
    )
    if not inspector.has_table("knowledge_document"):
        op.create_table(
        "knowledge_document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("knowledge_base_id", sa.Integer(), sa.ForeignKey("knowledge_base.id"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("knowledge_base_id", "content_hash", name="uq_knowledge_document_hash"),
    )
    if not inspector.has_table("knowledge_chunk"):
        op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False, index=True),
        sa.Column("knowledge_base_id", sa.Integer(), sa.ForeignKey("knowledge_base.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("knowledge_document.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_locator", sa.String(255), nullable=False),
        sa.Column("embedding", VECTOR(768), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_chunk_embedding_hnsw ON knowledge_chunk USING hnsw (embedding vector_cosine_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_chunk_base ON knowledge_chunk (tenant_id, knowledge_base_id)")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("knowledge_chunk"):
        op.drop_table("knowledge_chunk")
    if inspector.has_table("knowledge_document"):
        op.drop_table("knowledge_document")
    if inspector.has_table("knowledge_base"):
        op.drop_table("knowledge_base")
