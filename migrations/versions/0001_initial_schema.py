"""initial storage schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-06

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], unique=False)

    op.create_table(
        "resumes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resume_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("source_format", sa.String(length=16), nullable=False),
        sa.Column("parsing_status", sa.String(length=16), nullable=False),
        sa.Column("document_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "resume_id", name="uq_session_resume"),
    )
    op.create_index("ix_resumes_resume_id", "resumes", ["resume_id"], unique=False)
    op.create_index("ix_resumes_session_id", "resumes", ["session_id"], unique=False)
    op.create_index("ix_resumes_expires_at", "resumes", ["expires_at"], unique=False)

    op.create_table(
        "match_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_match_runs_resume_id", "match_runs", ["resume_id"], unique=False)

    op.create_table(
        "session_identities",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "ix_session_identities_user_id",
        "session_identities",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_session_identities_user_id", table_name="session_identities")
    op.drop_table("session_identities")
    op.drop_index("ix_match_runs_resume_id", table_name="match_runs")
    op.drop_table("match_runs")
    op.drop_index("ix_resumes_expires_at", table_name="resumes")
    op.drop_index("ix_resumes_session_id", table_name="resumes")
    op.drop_index("ix_resumes_resume_id", table_name="resumes")
    op.drop_table("resumes")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_table("sessions")
