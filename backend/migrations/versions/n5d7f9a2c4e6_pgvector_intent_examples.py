"""add pgvector-backed assistant intent examples

Revision ID: n5d7f9a2c4e6
Revises: m4c6e8a1b3d5
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR

revision = "n5d7f9a2c4e6"
down_revision = "m4c6e8a1b3d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "ai_intent_example",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("intent", sa.String(32), nullable=False),
        sa.Column("utterance", sa.String(500), nullable=False),
        sa.Column("embedding", VECTOR(768), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "intent", "utterance", name="uq_ai_intent_example_intent_utterance"
        ),
    )
    op.create_index("ix_ai_intent_example_intent", "ai_intent_example", ["intent"])
    op.create_index("ix_ai_intent_example_enabled", "ai_intent_example", ["enabled"])
    op.execute(
        "CREATE INDEX ix_ai_intent_example_embedding_hnsw "
        "ON ai_intent_example USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("ai_intent_example")
