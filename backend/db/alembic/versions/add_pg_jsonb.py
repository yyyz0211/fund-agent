"""add_pg_jsonb_and_indexes

Revision ID: add_pg_jsonb
Revises: c86e6132a2fd
Create Date: 2026-07-14 11:58:00.000000

PostgreSQL 特有优化：
1. 将 JSON 字符串列转为 JSONB（支持 GIN 索引）
2. 添加 GIN 索引用于高效 JSON 查询
3. 添加复合索引优化常见查询模式

注意：此迁移仅在 PostgreSQL 上运行，SQLite 上会被跳过。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_pg_jsonb'
down_revision: Union[str, Sequence[str], None] = 'c86e6132a2fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add PostgreSQL-specific optimizations.

    This migration is designed for PostgreSQL. On SQLite, these operations
    will fail gracefully and can be ignored.
    """
    # Check if we're running on PostgreSQL by attempting a JSONB cast
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect != 'postgresql':
        # Skip JSONB/GIN operations on non-PostgreSQL databases
        op.execute("SELECT 1")  # No-op for SQLite
        return

    # ---- JSONB conversions ----
    # Convert JSON string columns to JSONB for efficient querying

    # market_evidence: symbols and metrics often queried
    op.execute("""
        ALTER TABLE market_evidence
        ALTER COLUMN symbols_json TYPE JSONB
        USING CASE WHEN symbols_json IS NULL THEN NULL ELSE symbols_json::jsonb END
    """)

    # cls_telegraph_items: subjects and symbols frequently queried
    op.execute("""
        ALTER TABLE cls_telegraph_items
        ALTER COLUMN subjects_json TYPE JSONB
        USING CASE WHEN subjects_json IS NULL THEN NULL ELSE subjects_json::jsonb END
    """)
    op.execute("""
        ALTER TABLE cls_telegraph_items
        ALTER COLUMN symbols_json TYPE JSONB
        USING CASE WHEN symbols_json IS NULL THEN NULL ELSE symbols_json::jsonb END
    """)

    # knowledge_documents: various JSON fields
    jsonb_columns = [
        ('knowledge_documents', 'topics_json'),
        ('knowledge_documents', 'topic_names_json'),
        ('knowledge_documents', 'fund_theme_tags_json'),
        ('knowledge_documents', 'fund_type_tags_json'),
        ('knowledge_documents', 'markets_json'),
        ('knowledge_documents', 'asset_classes_json'),
    ]
    for table, column in jsonb_columns:
        op.execute(f"""
            ALTER TABLE {table}
            ALTER COLUMN {column} TYPE JSONB
            USING CASE WHEN {column} IS NULL THEN NULL ELSE {column}::jsonb END
        """)

    # knowledge_classification_log: raw response
    op.execute("""
        ALTER TABLE knowledge_classification_log
        ALTER COLUMN raw_response_json TYPE JSONB
        USING CASE WHEN raw_response_json IS NULL THEN NULL ELSE raw_response_json::jsonb END
    """)

    # fund_watchlist_profiles: tag fields
    profile_jsonb = [
        ('fund_watchlist_profiles', 'theme_tags_json'),
        ('fund_watchlist_profiles', 'risk_tags_json'),
        ('fund_watchlist_profiles', 'match_basis_json'),
        ('fund_watchlist_profiles', 'manual_overrides_json'),
    ]
    for table, column in profile_jsonb:
        op.execute(f"""
            ALTER TABLE {table}
            ALTER COLUMN {column} TYPE JSONB
            USING CASE WHEN {column} IS NULL THEN NULL ELSE {column}::jsonb END
        """)

    # knowledge_fund_matches: matched topics
    op.execute("""
        ALTER TABLE knowledge_fund_matches
        ALTER COLUMN matched_topics_json TYPE JSONB
        USING CASE WHEN matched_topics_json IS NULL THEN NULL ELSE matched_topics_json::jsonb END
    """)

    # ---- GIN indexes for JSONB columns ----
    # These enable efficient containment queries like: WHERE symbols_json ? 'AI'

    op.execute("CREATE INDEX ix_market_evidence_symbols_gin ON market_evidence USING GIN (symbols_json)")
    op.execute("CREATE INDEX ix_cls_telegraph_items_subjects_gin ON cls_telegraph_items USING GIN (subjects_json)")
    op.execute("CREATE INDEX ix_cls_telegraph_items_symbols_gin ON cls_telegraph_items USING GIN (symbols_json)")
    op.execute("CREATE INDEX ix_knowledge_documents_topics_gin ON knowledge_documents USING GIN (topics_json)")
    op.execute("CREATE INDEX ix_knowledge_documents_fund_theme_tags_gin ON knowledge_documents USING GIN (fund_theme_tags_json)")
    op.execute("CREATE INDEX ix_knowledge_documents_markets_gin ON knowledge_documents USING GIN (markets_json)")

    # ---- Composite indexes for common query patterns ----

    # knowledge_documents: filter by topic + sort by published_at
    op.execute("""
        CREATE INDEX ix_knowledge_documents_topic_published
        ON knowledge_documents (primary_topic, published_at DESC)
    """)

    # market_evidence: filter by trade_date + brief_type
    op.execute("""
        CREATE INDEX ix_market_evidence_date_type
        ON market_evidence (trade_date DESC, brief_type)
    """)

    # knowledge_reindex_jobs: find stale pending jobs
    op.execute("""
        CREATE INDEX ix_knowledge_reindex_jobs_status_created
        ON knowledge_reindex_jobs (status, created_at)
        WHERE status IN ('pending', 'running')
    """)


def downgrade() -> None:
    """Remove PostgreSQL-specific optimizations."""
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect != 'postgresql':
        op.execute("SELECT 1")
        return

    # Drop GIN indexes
    op.execute("DROP INDEX IF EXISTS ix_market_evidence_symbols_gin")
    op.execute("DROP INDEX IF EXISTS ix_cls_telegraph_items_subjects_gin")
    op.execute("DROP INDEX IF EXISTS ix_cls_telegraph_items_symbols_gin")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_documents_topics_gin")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_documents_fund_theme_tags_gin")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_documents_markets_gin")

    # Drop composite indexes
    op.execute("DROP INDEX IF EXISTS ix_knowledge_documents_topic_published")
    op.execute("DROP INDEX IF EXISTS ix_market_evidence_date_type")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_reindex_jobs_status_created")

    # Convert JSONB back to TEXT (simplified - in production you'd preserve the JSON string)
    op.execute("ALTER TABLE market_evidence ALTER COLUMN symbols_json TYPE TEXT")
    op.execute("ALTER TABLE cls_telegraph_items ALTER COLUMN subjects_json TYPE TEXT")
    op.execute("ALTER TABLE cls_telegraph_items ALTER COLUMN symbols_json TYPE TEXT")
    op.execute("ALTER TABLE knowledge_documents ALTER COLUMN topics_json TYPE TEXT")
    op.execute("ALTER TABLE knowledge_documents ALTER COLUMN topic_names_json TYPE TEXT")
    op.execute("ALTER TABLE knowledge_documents ALTER COLUMN fund_theme_tags_json TYPE TEXT")
    op.execute("ALTER TABLE knowledge_documents ALTER COLUMN fund_type_tags_json TYPE TEXT")
    op.execute("ALTER TABLE knowledge_documents ALTER COLUMN markets_json TYPE TEXT")
    op.execute("ALTER TABLE knowledge_documents ALTER COLUMN asset_classes_json TYPE TEXT")
    op.execute("ALTER TABLE knowledge_classification_log ALTER COLUMN raw_response_json TYPE TEXT")
    op.execute("ALTER TABLE fund_watchlist_profiles ALTER COLUMN theme_tags_json TYPE TEXT")
    op.execute("ALTER TABLE fund_watchlist_profiles ALTER COLUMN risk_tags_json TYPE TEXT")
    op.execute("ALTER TABLE fund_watchlist_profiles ALTER COLUMN match_basis_json TYPE TEXT")
    op.execute("ALTER TABLE fund_watchlist_profiles ALTER COLUMN manual_overrides_json TYPE TEXT")
    op.execute("ALTER TABLE knowledge_fund_matches ALTER COLUMN matched_topics_json TYPE TEXT")
