"""initial_baseline

Revision ID: initial_baseline
Revises:
Create Date: 2026-07-14 15:00:00.000000

从 models.py 生成的完整 schema 创建。
所有表按 models.py 定义创建，保持字段顺序和约束一致。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = "initial_baseline"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables from models.py."""

    # --- funds ---
    op.create_table(
        "funds",
        sa.Column("fund_code", sa.String(), nullable=False),
        sa.Column("fund_name", sa.String(), nullable=True),
        sa.Column("fund_type", sa.String(), nullable=True),
        sa.Column("manager", sa.String(), nullable=True),
        sa.Column("company", sa.String(), nullable=True),
        sa.Column("inception_date", sa.String(), nullable=True),
        sa.Column("risk_level", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("fund_code"),
    )

    # --- fund_profiles ---
    op.create_table(
        "fund_profiles",
        sa.Column("fund_code", sa.String(), nullable=False),
        sa.Column("scale", sa.Float(), nullable=True),
        sa.Column("scale_date", sa.String(), nullable=True),
        sa.Column("peer_category", sa.String(), nullable=True),
        sa.Column("rank_total", sa.Integer(), nullable=True),
        sa.Column("rank_position", sa.Integer(), nullable=True),
        sa.Column("peer_candidates_json", sa.String(), nullable=True),
        sa.Column("top10_holding_pct", sa.Float(), nullable=True),
        sa.Column("top_industry_pct", sa.Float(), nullable=True),
        sa.Column("manager_summary", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("as_of", sa.String(), nullable=True),
        sa.Column("raw_errors", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("fund_code"),
    )

    # --- watchlist ---
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fund_code", sa.String(), nullable=False),
        sa.Column("fund_name", sa.String(length=64), nullable=True),
        sa.Column("is_holding", sa.Boolean(), nullable=False),
        sa.Column("is_focus", sa.Boolean(), nullable=False),
        sa.Column("holding_amount", sa.Float(), nullable=True),
        sa.Column("holding_share", sa.Float(), nullable=True),
        sa.Column("cost_nav", sa.Float(), nullable=True),
        sa.Column("buy_date", sa.String(), nullable=True),
        sa.Column("preload_status", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("cost_nav_basis", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fund_code", name="uq_watchlist_fund"),
    )
    op.create_index(op.f("ix_watchlist_fund_code"), "watchlist", ["fund_code"], unique=False)

    # --- fund_transactions ---
    op.create_table(
        "fund_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fund_code", sa.String(), nullable=False),
        sa.Column("tx_date", sa.String(), nullable=False),
        sa.Column("tx_seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("nav", sa.Float(), nullable=False),
        sa.Column("share", sa.Float(), nullable=True),
        sa.Column("fee", sa.Float(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fund_code", "tx_date", "tx_seq", name="uq_tx_fund_date_seq"),
    )
    op.create_index(op.f("ix_fund_transactions_fund_code"), "fund_transactions", ["fund_code"], unique=False)

    # --- fund_investment_plans ---
    op.create_table(
        "fund_investment_plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fund_code", sa.String(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("frequency", sa.String(), nullable=False),
        sa.Column("day_rule", sa.String(), nullable=False),
        sa.Column("start_date", sa.String(), nullable=False),
        sa.Column("end_date", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fund_investment_plans_fund_code"), "fund_investment_plans", ["fund_code"], unique=False)

    # --- fund_pending_buys ---
    op.create_table(
        "fund_pending_buys",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fund_code", sa.String(), nullable=False),
        sa.Column("request_date", sa.String(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("nav_date", sa.String(), nullable=True),
        sa.Column("nav", sa.Float(), nullable=True),
        sa.Column("share", sa.Float(), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fund_pending_buys_fund_code"), "fund_pending_buys", ["fund_code"], unique=False)

    # --- fund_nav ---
    op.create_table(
        "fund_nav",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fund_code", sa.String(), nullable=False),
        sa.Column("nav_date", sa.String(), nullable=False),
        sa.Column("unit_nav", sa.Float(), nullable=True),
        sa.Column("accumulated_nav", sa.Float(), nullable=True),
        sa.Column("daily_return", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("source_updated_at", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fund_code", "nav_date", name="uq_nav_fund_date"),
    )
    op.create_index(op.f("ix_fund_nav_fund_code"), "fund_nav", ["fund_code"], unique=False)
    op.create_index(op.f("ix_fund_nav_nav_date"), "fund_nav", ["nav_date"], unique=False)

    # --- market_data ---
    op.create_table(
        "market_data",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("market_date", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "market_date", name="uq_market_symbol_date"),
    )
    op.create_index(op.f("ix_market_data_market_date"), "market_data", ["market_date"], unique=False)
    op.create_index(op.f("ix_market_data_symbol"), "market_data", ["symbol"], unique=False)

    # --- briefings ---
    op.create_table(
        "briefings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("briefing_date", sa.String(), nullable=False),
        sa.Column("brief_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("markdown", sa.String(), nullable=False),
        sa.Column("sections_json", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("as_of", sa.String(), nullable=True),
        sa.Column("data_quality", sa.String(), nullable=True),
        sa.Column("confidence", sa.String(), nullable=True),
        sa.Column("missing_data_json", sa.String(), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("briefing_date", "brief_type", name="uq_briefing_date_type"),
    )
    op.create_index(op.f("ix_briefings_briefing_date"), "briefings", ["briefing_date"], unique=False)
    op.create_index(op.f("ix_briefings_brief_type"), "briefings", ["brief_type"], unique=False)

    # --- briefing_feedback ---
    op.create_table(
        "briefing_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("briefing_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("risk_accuracy", sa.Integer(), nullable=True),
        sa.Column("theme_accuracy", sa.Integer(), nullable=True),
        sa.Column("evidence_quality", sa.Integer(), nullable=True),
        sa.Column("overall_satisfaction", sa.Integer(), nullable=True),
        sa.Column("comment", sa.String(length=2000), nullable=True),
        sa.Column("feedback_meta_json", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("briefing_id", "user_id", name="uq_briefing_feedback"),
    )
    op.create_index(op.f("ix_briefing_feedback_briefing_id"), "briefing_feedback", ["briefing_id"], unique=False)

    # --- market_snapshots ---
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.String(length=10), nullable=False),
        sa.Column("snapshot_type", sa.String(length=16), nullable=False),
        sa.Column("indices_json", sa.String(), nullable=False),
        sa.Column("breadth_json", sa.String(), nullable=False),
        sa.Column("industry_sectors_json", sa.String(), nullable=False),
        sa.Column("concept_sectors_json", sa.String(), nullable=False),
        sa.Column("industry_flows_json", sa.String(), nullable=False),
        sa.Column("concept_flows_json", sa.String(), nullable=False),
        sa.Column("themes_json", sa.String(), nullable=False),
        sa.Column("breadth_indicators_json", sa.String(), nullable=False),
        sa.Column("overseas_json", sa.String(), nullable=False),
        sa.Column("announcements_json", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("as_of", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "snapshot_type", name="uq_market_snapshot_date_type"),
    )
    op.create_index(op.f("ix_market_snapshots_trade_date"), "market_snapshots", ["trade_date"], unique=False)

    # --- market_evidence ---
    op.create_table(
        "market_evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_date", sa.String(length=10), nullable=False),
        sa.Column("brief_type", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("symbols_json", sa.String(), nullable=True),
        sa.Column("metrics_json", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("published_at", sa.String(), nullable=True),
        sa.Column("reliability", sa.String(), nullable=False),
        sa.Column("raw_hash", sa.String(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_date", "brief_type", "source_url", name="uq_evidence_trade_brief_url"),
    )
    op.create_index(op.f("ix_market_evidence_trade_date"), "market_evidence", ["trade_date"], unique=False)
    op.create_index(op.f("ix_market_evidence_brief_type"), "market_evidence", ["brief_type"], unique=False)
    op.create_index(op.f("ix_market_evidence_category"), "market_evidence", ["category"], unique=False)

    # --- cls_telegraph_items ---
    op.create_table(
        "cls_telegraph_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("cls_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("brief", sa.String(), nullable=True),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("subjects_json", sa.String(), nullable=True),
        sa.Column("symbols_json", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("ctime", sa.BigInteger(), nullable=True),
        sa.Column("published_at", sa.String(), nullable=True),
        sa.Column("raw_json", sa.String(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cls_id", name="uq_cls_telegraph_items_cls_id"),
    )
    op.create_index(op.f("ix_cls_telegraph_items_cls_id"), "cls_telegraph_items", ["cls_id"], unique=True)
    op.create_index(op.f("ix_cls_telegraph_items_category"), "cls_telegraph_items", ["category"], unique=False)
    op.create_index(op.f("ix_cls_telegraph_items_ctime"), "cls_telegraph_items", ["ctime"], unique=False)
    op.create_index(op.f("ix_cls_telegraph_items_published_at"), "cls_telegraph_items", ["published_at"], unique=False)

    # --- cls_telegraph_sync_state ---
    op.create_table(
        "cls_telegraph_sync_state",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("last_seen_ctime", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_cls_id", sa.String(), nullable=True),
        sa.Column("last_success_at", sa.String(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- knowledge_documents ---
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("content", sa.String(), nullable=True),
        sa.Column("normalized_text", sa.String(), nullable=False),
        sa.Column("primary_topic", sa.String(length=64), nullable=True),
        sa.Column("topic_title", sa.String(length=128), nullable=True),
        sa.Column("topics_json", sa.String(), nullable=True),
        sa.Column("topic_names_json", sa.String(), nullable=True),
        sa.Column("fund_theme_tags_json", sa.String(), nullable=True),
        sa.Column("fund_type_tags_json", sa.String(), nullable=True),
        sa.Column("markets_json", sa.String(), nullable=True),
        sa.Column("asset_classes_json", sa.String(), nullable=True),
        sa.Column("impact_direction", sa.String(length=16), nullable=False),
        sa.Column("published_at", sa.String(), nullable=True),
        sa.Column("effective_until", sa.String(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("classification_status", sa.String(length=16), nullable=False),
        sa.Column("index_status", sa.String(length=16), nullable=False),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("embedding_version", sa.String(length=64), nullable=True),
        sa.Column("index_attempts", sa.Integer(), nullable=False),
        sa.Column("last_index_error", sa.String(), nullable=True),
        sa.Column("next_index_retry_at", sa.DateTime(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("canonical_content_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_reason", sa.String(), nullable=True),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.Column("conflict_group_id", sa.String(length=64), nullable=True),
        sa.Column("conflict_status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "source_id", name="uq_knowledge_source_identity"),
        sa.UniqueConstraint("content_hash", name="uq_knowledge_content_hash"),
        sa.UniqueConstraint("canonical_content_hash", name="uq_knowledge_canonical_hash"),
    )
    op.create_index(op.f("ix_knowledge_documents_source_type"), "knowledge_documents", ["source_type"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_source_id"), "knowledge_documents", ["source_id"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_primary_topic"), "knowledge_documents", ["primary_topic"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_impact_direction"), "knowledge_documents", ["impact_direction"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_published_at"), "knowledge_documents", ["published_at"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_effective_until"), "knowledge_documents", ["effective_until"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_classification_status"), "knowledge_documents", ["classification_status"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_index_status"), "knowledge_documents", ["index_status"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_content_hash"), "knowledge_documents", ["content_hash"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_canonical_content_hash"), "knowledge_documents", ["canonical_content_hash"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_conflict_status"), "knowledge_documents", ["conflict_status"], unique=False)
    op.create_index(op.f("ix_knowledge_documents_next_index_retry_at"), "knowledge_documents", ["next_index_retry_at"], unique=False)

    # --- knowledge_source_links ---
    op.create_table(
        "knowledge_source_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "source_id", name="uq_knowledge_source_link_source"),
        sa.UniqueConstraint("document_id", "source_type", "source_id", name="uq_knowledge_source_link_doc_source"),
    )
    op.create_index(op.f("ix_knowledge_source_links_document_id"), "knowledge_source_links", ["document_id"], unique=False)
    op.create_index(op.f("ix_knowledge_source_links_source_type"), "knowledge_source_links", ["source_type"], unique=False)
    op.create_index(op.f("ix_knowledge_source_links_source_id"), "knowledge_source_links", ["source_id"], unique=False)

    # --- knowledge_classification_state ---
    op.create_table(
        "knowledge_classification_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_content_hash", sa.String(length=64), nullable=True),
        sa.Column("latest_attempt_no", sa.Integer(), nullable=False),
        sa.Column("should_index", sa.Boolean(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("last_error_message", sa.String(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "source_id", name="uq_knowledge_classification_state_source"),
    )
    op.create_index(op.f("ix_knowledge_classification_state_source_type"), "knowledge_classification_state", ["source_type"], unique=False)
    op.create_index(op.f("ix_knowledge_classification_state_source_id"), "knowledge_classification_state", ["source_id"], unique=False)
    op.create_index(op.f("ix_knowledge_classification_state_status"), "knowledge_classification_state", ["status"], unique=False)
    op.create_index(op.f("ix_knowledge_classification_state_document_id"), "knowledge_classification_state", ["document_id"], unique=False)
    op.create_index(op.f("ix_knowledge_classification_state_next_retry_at"), "knowledge_classification_state", ["next_retry_at"], unique=False)

    # --- knowledge_classification_log ---
    op.create_table(
        "knowledge_classification_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_content_hash", sa.String(length=64), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("should_index", sa.Boolean(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("raw_response_json", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_type", "source_id", "canonical_content_hash",
            "prompt_version", "attempt_no",
            name="uq_knowledge_classification_log_content_attempt",
        ),
    )
    op.create_index(op.f("ix_knowledge_classification_log_source_type"), "knowledge_classification_log", ["source_type"], unique=False)
    op.create_index(op.f("ix_knowledge_classification_log_source_id"), "knowledge_classification_log", ["source_id"], unique=False)
    op.create_index(op.f("ix_knowledge_classification_log_status"), "knowledge_classification_log", ["status"], unique=False)

    # --- knowledge_chunks ---
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("index_status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_doc_idx"),
        sa.UniqueConstraint("content_hash", name="uq_knowledge_chunk_hash"),
    )
    op.create_index(op.f("ix_knowledge_chunks_document_id"), "knowledge_chunks", ["document_id"], unique=False)
    op.create_index(op.f("ix_knowledge_chunks_index_status"), "knowledge_chunks", ["index_status"], unique=False)

    # --- fund_watchlist_profiles ---
    op.create_table(
        "fund_watchlist_profiles",
        sa.Column("fund_code", sa.String(), nullable=False),
        sa.Column("fund_name", sa.String(), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("holding_weight", sa.Float(), nullable=True),
        sa.Column("fund_type", sa.String(), nullable=True),
        sa.Column("peer_category", sa.String(), nullable=True),
        sa.Column("theme_tags_json", sa.String(), nullable=True),
        sa.Column("risk_tags_json", sa.String(), nullable=True),
        sa.Column("match_basis_json", sa.String(), nullable=True),
        sa.Column("manual_overrides_json", sa.String(), nullable=True),
        sa.Column("profile_status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("fund_code"),
    )
    op.create_index(op.f("ix_fund_watchlist_profiles_priority"), "fund_watchlist_profiles", ["priority"], unique=False)
    op.create_index(op.f("ix_fund_watchlist_profiles_profile_status"), "fund_watchlist_profiles", ["profile_status"], unique=False)

    # --- knowledge_fund_matches ---
    op.create_table(
        "knowledge_fund_matches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("fund_code", sa.String(), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column("matched_topics_json", sa.String(), nullable=True),
        sa.Column("match_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "fund_code", name="uq_knowledge_fund_match_doc_fund"),
    )
    op.create_index(op.f("ix_knowledge_fund_matches_document_id"), "knowledge_fund_matches", ["document_id"], unique=False)
    op.create_index(op.f("ix_knowledge_fund_matches_fund_code"), "knowledge_fund_matches", ["fund_code"], unique=False)

    # --- knowledge_retrieval_logs ---
    op.create_table(
        "knowledge_retrieval_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("filters_json", sa.String(), nullable=True),
        sa.Column("retrieval_mode", sa.String(length=32), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_retrieval_logs_retrieval_mode"), "knowledge_retrieval_logs", ["retrieval_mode"], unique=False)

    # --- knowledge_reindex_jobs ---
    op.create_table(
        "knowledge_reindex_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("result_json", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_reindex_jobs_trigger"), "knowledge_reindex_jobs", ["trigger"], unique=False)
    op.create_index(op.f("ix_knowledge_reindex_jobs_status"), "knowledge_reindex_jobs", ["status"], unique=False)


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("knowledge_reindex_jobs")
    op.drop_table("knowledge_retrieval_logs")
    op.drop_table("knowledge_fund_matches")
    op.drop_table("fund_watchlist_profiles")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_classification_log")
    op.drop_table("knowledge_classification_state")
    op.drop_table("knowledge_source_links")
    op.drop_table("knowledge_documents")
    op.drop_table("cls_telegraph_sync_state")
    op.drop_table("cls_telegraph_items")
    op.drop_table("market_evidence")
    op.drop_table("market_snapshots")
    op.drop_table("briefing_feedback")
    op.drop_table("briefings")
    op.drop_table("market_data")
    op.drop_table("fund_nav")
    op.drop_table("fund_pending_buys")
    op.drop_table("fund_investment_plans")
    op.drop_table("fund_transactions")
    op.drop_table("watchlist")
    op.drop_table("fund_profiles")
    op.drop_table("funds")
