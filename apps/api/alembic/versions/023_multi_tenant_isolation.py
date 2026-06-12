"""023: 多租户隔离 + 全局红人池 + 产品维度业务记录"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "023_multi_tenant_isolation"
down_revision: Union[str, None] = "022_youtube_platform_unique_id_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
    )
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_product_workspace_slug"),
    )
    op.create_index("ix_products_workspace_id", "products", ["workspace_id"])

    op.create_table(
        "global_influencer_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("platform_unique_id", sa.String(length=128), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("normalized_username", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("profile_url", sa.String(length=1024), nullable=False),
        sa.Column("normalized_profile_url", sa.String(length=1024), nullable=False),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("niche", sa.String(length=100), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("followers_count", sa.Integer(), nullable=True),
        sa.Column("avg_views", sa.Integer(), nullable=True),
        sa.Column("avg_likes", sa.Integer(), nullable=True),
        sa.Column("avg_comments", sa.Integer(), nullable=True),
        sa.Column("engagement_rate", sa.Float(), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("final_email", sa.String(length=255), nullable=True),
        sa.Column("public_email", sa.String(length=255), nullable=True),
        sa.Column("business_email", sa.String(length=255), nullable=True),
        sa.Column("email_source", sa.String(length=100), nullable=True),
        sa.Column("contact_credibility", sa.Float(), nullable=True),
        sa.Column("contact_score", sa.Float(), nullable=True),
        sa.Column("contact_credibility_level", sa.String(length=20), nullable=True),
        sa.Column("website", sa.String(length=1024), nullable=True),
        sa.Column("contact_page", sa.String(length=1024), nullable=True),
        sa.Column("linktree_url", sa.String(length=1024), nullable=True),
        sa.Column("whatsapp", sa.String(length=50), nullable=True),
        sa.Column("telegram", sa.String(length=100), nullable=True),
        sa.Column("other_social_links", postgresql.JSONB(), nullable=True),
        sa.Column("contact_discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contact_sources", postgresql.JSONB(), nullable=True),
        sa.Column("contact_fetch_status", sa.String(length=32), nullable=True),
        sa.Column("contact_fetch_error", sa.Text(), nullable=True),
        sa.Column("recent_post_titles", postgresql.JSONB(), nullable=True),
        sa.Column("recent_post_urls", postgresql.JSONB(), nullable=True),
        sa.Column("last_post_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posting_frequency", sa.String(length=50), nullable=True),
        sa.Column("data_completeness", sa.Float(), nullable=True),
        sa.Column("has_brand_collaboration", sa.Boolean(), nullable=True),
        sa.Column("estimated_collab_price", sa.String(length=100), nullable=True),
        sa.Column("collaboration_formats", postgresql.JSONB(), nullable=True),
        sa.Column("content_topics", postgresql.JSONB(), nullable=True),
        sa.Column("audience_country", sa.String(length=100), nullable=True),
        sa.Column("audience_language", sa.String(length=50), nullable=True),
        sa.Column("legacy_influencer_id", sa.Integer(), nullable=True),
        sa.Column("profile_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_global_influencer_platform", "global_influencer_profiles", ["platform"])
    op.create_index(
        "ix_global_influencer_username",
        "global_influencer_profiles",
        ["platform", "normalized_username"],
    )
    op.create_index(
        "ix_global_influencer_legacy_influencer_id",
        "global_influencer_profiles",
        ["legacy_influencer_id"],
    )
    op.create_index(
        "ix_global_influencer_contact_fetch_status",
        "global_influencer_profiles",
        ["contact_fetch_status"],
    )

    op.create_table(
        "product_influencers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("global_influencer_id", sa.Integer(), nullable=False),
        sa.Column("legacy_influencer_id", sa.Integer(), nullable=True),
        sa.Column("product_fit", sa.Float(), nullable=True),
        sa.Column("engagement_score", sa.Float(), nullable=True),
        sa.Column("content_match_score", sa.Float(), nullable=True),
        sa.Column("contactability_score", sa.Float(), nullable=True),
        sa.Column("commercial_signal_score", sa.Float(), nullable=True),
        sa.Column("activity_score", sa.Float(), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("travel_fit_score", sa.Float(), nullable=True),
        sa.Column("purchasing_power_score", sa.Float(), nullable=True),
        sa.Column("sales_potential_score", sa.Float(), nullable=True),
        sa.Column("audience_match_score", sa.Float(), nullable=True),
        sa.Column("roi_forecast", sa.Float(), nullable=True),
        sa.Column("final_priority", sa.String(length=10), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("score_reason", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_collaboration_suggestion", sa.Text(), nullable=True),
        sa.Column("ai_outreach_message", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("follow_status", sa.String(length=50), nullable=True),
        sa.Column("owner", sa.String(length=100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalid_reason", sa.Text(), nullable=True),
        sa.Column("blacklist_reason", sa.Text(), nullable=True),
        sa.Column("source_discovery_type", sa.String(length=32), nullable=True),
        sa.Column("source_post_url", sa.String(length=512), nullable=True),
        sa.Column("source_comment_url", sa.String(length=512), nullable=True),
        sa.Column("source_comment_text", sa.Text(), nullable=True),
        sa.Column("is_inserted", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("filter_reason", sa.String(length=64), nullable=True),
        sa.Column("filter_detail", sa.Text(), nullable=True),
        sa.Column("first_inserted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["global_influencer_id"], ["global_influencer_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "global_influencer_id", name="uq_product_influencer_product_global"),
    )
    op.create_index("ix_product_influencers_product_id", "product_influencers", ["product_id"])
    op.create_index("ix_product_influencers_follow_status", "product_influencers", ["follow_status"])
    op.create_index("ix_product_influencers_legacy_influencer_id", "product_influencers", ["legacy_influencer_id"])
    op.create_index("ix_product_influencers_next_follow_up_at", "product_influencers", ["next_follow_up_at"])

    op.add_column("collection_tasks", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("collection_tasks", sa.Column("workspace_id", sa.Integer(), nullable=True))
    op.add_column("collection_tasks", sa.Column("product_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_collection_tasks_user_id", "collection_tasks", "users", ["user_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(
        "fk_collection_tasks_workspace_id", "collection_tasks", "workspaces", ["workspace_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_collection_tasks_product_id", "collection_tasks", "products", ["product_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_collection_tasks_user_id", "collection_tasks", ["user_id"])
    op.create_index("ix_collection_tasks_workspace_id", "collection_tasks", ["workspace_id"])
    op.create_index("ix_collection_tasks_product_id", "collection_tasks", ["product_id"])

    op.add_column("collection_task_candidates", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("collection_task_candidates", sa.Column("product_id", sa.Integer(), nullable=True))
    op.add_column("collection_task_candidates", sa.Column("global_influencer_id", sa.Integer(), nullable=True))
    op.add_column("collection_task_candidates", sa.Column("product_influencer_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_candidates_user_id", "collection_task_candidates", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_candidates_product_id", "collection_task_candidates", "products", ["product_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_candidates_global_influencer_id",
        "collection_task_candidates",
        "global_influencer_profiles",
        ["global_influencer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_candidates_product_influencer_id",
        "collection_task_candidates",
        "product_influencers",
        ["product_influencer_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("email_logs", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("email_logs", sa.Column("product_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_email_logs_user_id", "email_logs", "users", ["user_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(
        "fk_email_logs_product_id", "email_logs", "products", ["product_id"], ["id"], ondelete="SET NULL"
    )

    op.add_column("influencer_followups", sa.Column("product_influencer_id", sa.Integer(), nullable=True))
    op.alter_column("influencer_followups", "influencer_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key(
        "fk_followups_product_influencer_id",
        "influencer_followups",
        "product_influencers",
        ["product_influencer_id"],
        ["id"],
        ondelete="CASCADE",
    )

    _seed_defaults_and_backfill()


def _seed_defaults_and_backfill() -> None:
    op.execute(
        """
        INSERT INTO users (id, username, display_name, email, is_active, is_admin)
        VALUES (1, 'admin', '管理员', 'admin@local', true, true)
        ON CONFLICT (username) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO workspaces (id, name, slug)
        VALUES (1, '默认团队', 'default')
        ON CONFLICT (slug) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO workspace_members (workspace_id, user_id, role)
        SELECT 1, 1, 'owner'
        WHERE NOT EXISTS (
            SELECT 1 FROM workspace_members WHERE workspace_id = 1 AND user_id = 1
        )
        """
    )
    op.execute(
        """
        INSERT INTO products (id, workspace_id, name, slug, brand, is_default)
        VALUES (1, 1, '默认项目', 'default', '默认品牌', true)
        ON CONFLICT ON CONSTRAINT uq_product_workspace_slug DO NOTHING
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                i.*,
                LOWER(TRIM(BOTH '@' FROM i.username)) AS normalized_username,
                LOWER(RTRIM(i.profile_url, '/')) AS normalized_profile_url,
                ROW_NUMBER() OVER (
                    PARTITION BY i.platform,
                        COALESCE(
                            NULLIF(TRIM(i.platform_unique_id), ''),
                            LOWER(RTRIM(i.profile_url, '/'))
                        )
                    ORDER BY
                        CASE
                            WHEN i.platform_unique_id IS NOT NULL AND TRIM(i.platform_unique_id) <> '' THEN 0
                            ELSE 1
                        END,
                        i.id ASC
                ) AS rn
            FROM influencers i
        )
        INSERT INTO global_influencer_profiles (
            platform, platform_unique_id, username, normalized_username,
            display_name, profile_url, normalized_profile_url, avatar_url,
            country, language, category, niche, bio,
            followers_count, avg_views, avg_likes, avg_comments, engagement_rate,
            email, final_email, public_email, business_email, email_source,
            contact_credibility, contact_score, contact_credibility_level,
            website, contact_page, linktree_url, whatsapp, telegram,
            other_social_links, contact_discovered_at, contact_sources,
            contact_fetch_status, contact_fetch_error,
            recent_post_titles, recent_post_urls, last_post_at, posting_frequency,
            data_completeness, has_brand_collaboration, estimated_collab_price,
            collaboration_formats, content_topics, audience_country, audience_language,
            legacy_influencer_id, profile_refreshed_at, created_at, updated_at
        )
        SELECT
            platform,
            NULLIF(TRIM(platform_unique_id), ''),
            username,
            normalized_username,
            display_name,
            profile_url,
            normalized_profile_url,
            avatar_url,
            country,
            language,
            category,
            niche,
            bio,
            followers_count,
            avg_views,
            avg_likes,
            avg_comments,
            engagement_rate,
            email,
            final_email,
            public_email,
            business_email,
            email_source,
            contact_credibility,
            contact_score,
            contact_credibility_level,
            website,
            contact_page,
            linktree_url,
            whatsapp,
            telegram,
            COALESCE(other_social_links, '[]'::jsonb),
            contact_discovered_at,
            COALESCE(contact_sources, '[]'::jsonb),
            contact_fetch_status,
            contact_fetch_error,
            COALESCE(recent_post_titles, '[]'::jsonb),
            COALESCE(recent_post_urls, '[]'::jsonb),
            last_post_at,
            posting_frequency,
            data_completeness,
            has_brand_collaboration,
            estimated_collab_price,
            COALESCE(collaboration_formats, '[]'::jsonb),
            COALESCE(content_topics, '[]'::jsonb),
            audience_country,
            audience_language,
            id,
            COALESCE(last_collected_at, updated_at, created_at),
            created_at,
            updated_at
        FROM ranked
        WHERE rn = 1
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                i.*,
                LOWER(TRIM(BOTH '@' FROM i.username)) AS normalized_username,
                LOWER(RTRIM(i.profile_url, '/')) AS normalized_profile_url,
                ROW_NUMBER() OVER (
                    PARTITION BY i.platform,
                        COALESCE(
                            NULLIF(TRIM(i.platform_unique_id), ''),
                            LOWER(RTRIM(i.profile_url, '/'))
                        )
                    ORDER BY
                        CASE
                            WHEN i.platform_unique_id IS NOT NULL AND TRIM(i.platform_unique_id) <> '' THEN 0
                            ELSE 1
                        END,
                        i.id ASC
                ) AS rn
            FROM influencers i
        ),
        canonical AS (
            SELECT id AS canonical_id, platform, platform_unique_id, normalized_profile_url
            FROM ranked
            WHERE rn = 1
        ),
        influencer_map AS (
            SELECT
                r.id AS influencer_id,
                c.canonical_id
            FROM ranked r
            JOIN canonical c
              ON c.platform = r.platform
             AND COALESCE(NULLIF(TRIM(c.platform_unique_id), ''), c.normalized_profile_url)
               = COALESCE(NULLIF(TRIM(r.platform_unique_id), ''), r.normalized_profile_url)
        )
        INSERT INTO product_influencers (
            product_id, global_influencer_id, legacy_influencer_id,
            product_fit, engagement_score, content_match_score, contactability_score,
            commercial_signal_score, activity_score, risk_score,
            travel_fit_score, purchasing_power_score, sales_potential_score,
            audience_match_score, roi_forecast, final_priority, score, risk_level,
            score_reason, ai_summary, ai_collaboration_suggestion, ai_outreach_message,
            tags, follow_status, owner, note, next_follow_up_at,
            last_contacted_at, last_reply_at, invalid_reason, blacklist_reason,
            source_discovery_type, source_post_url, source_comment_url, source_comment_text,
            is_inserted, first_inserted_at, last_collected_at, created_at, updated_at
        )
        SELECT
            1, g.id, i.id,
            i.product_fit, i.engagement_score, i.content_match_score, i.contactability_score,
            i.commercial_signal_score, i.activity_score, i.risk_score,
            i.travel_fit_score, i.purchasing_power_score, i.sales_potential_score,
            i.audience_match_score, i.roi_forecast, i.final_priority, i.score, i.risk_level,
            i.score_reason, i.ai_summary, i.ai_collaboration_suggestion, i.ai_outreach_message,
            COALESCE(i.tags, '[]'::jsonb), i.follow_status, i.owner, i.note, i.next_follow_up_at,
            i.last_contacted_at, i.last_reply_at, i.invalid_reason, i.blacklist_reason,
            i.source_discovery_type, i.source_post_url, i.source_comment_url, i.source_comment_text,
            true, COALESCE(i.last_collected_at, i.created_at), i.last_collected_at, i.created_at, i.updated_at
        FROM influencers i
        JOIN influencer_map m ON m.influencer_id = i.id
        JOIN global_influencer_profiles g ON g.legacy_influencer_id = m.canonical_id
        ON CONFLICT (product_id, global_influencer_id) DO NOTHING
        """
    )

    op.create_unique_constraint(
        "uq_global_influencer_platform_url",
        "global_influencer_profiles",
        ["platform", "normalized_profile_url"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_global_influencer_platform_unique_id
        ON global_influencer_profiles (platform, platform_unique_id)
        WHERE platform_unique_id IS NOT NULL
        """
    )

    op.execute(
        """
        UPDATE collection_tasks
        SET user_id = 1, workspace_id = 1, product_id = 1
        WHERE user_id IS NULL OR workspace_id IS NULL OR product_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE collection_task_candidates AS c
        SET user_id = t.user_id,
            product_id = t.product_id
        FROM collection_tasks AS t
        WHERE c.task_id = t.id
        """
    )
    op.execute(
        """
        UPDATE collection_task_candidates AS c
        SET product_influencer_id = pi.id,
            global_influencer_id = pi.global_influencer_id
        FROM product_influencers AS pi
        WHERE pi.legacy_influencer_id = c.influencer_id
          AND pi.product_id = c.product_id
        """
    )
    op.execute(
        """
        UPDATE email_logs e
        SET user_id = t.user_id, product_id = t.product_id
        FROM collection_tasks t
        WHERE e.task_id = t.id
        """
    )
    op.execute(
        """
        UPDATE influencer_followups f
        SET product_influencer_id = pi.id
        FROM product_influencers pi
        WHERE f.influencer_id = pi.legacy_influencer_id
          AND f.product_influencer_id IS NULL
        """
    )
    for table in ("users", "workspaces", "products", "global_influencer_profiles", "product_influencers"):
        op.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1))"
        )


def downgrade() -> None:
    op.drop_constraint("fk_followups_product_influencer_id", "influencer_followups", type_="foreignkey")
    op.alter_column("influencer_followups", "influencer_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("influencer_followups", "product_influencer_id")

    op.drop_constraint("fk_email_logs_product_id", "email_logs", type_="foreignkey")
    op.drop_constraint("fk_email_logs_user_id", "email_logs", type_="foreignkey")
    op.drop_column("email_logs", "product_id")
    op.drop_column("email_logs", "user_id")

    op.drop_constraint("fk_candidates_product_influencer_id", "collection_task_candidates", type_="foreignkey")
    op.drop_constraint("fk_candidates_global_influencer_id", "collection_task_candidates", type_="foreignkey")
    op.drop_constraint("fk_candidates_product_id", "collection_task_candidates", type_="foreignkey")
    op.drop_constraint("fk_candidates_user_id", "collection_task_candidates", type_="foreignkey")
    op.drop_column("collection_task_candidates", "product_influencer_id")
    op.drop_column("collection_task_candidates", "global_influencer_id")
    op.drop_column("collection_task_candidates", "product_id")
    op.drop_column("collection_task_candidates", "user_id")

    op.drop_index("ix_collection_tasks_product_id", table_name="collection_tasks")
    op.drop_index("ix_collection_tasks_workspace_id", table_name="collection_tasks")
    op.drop_index("ix_collection_tasks_user_id", table_name="collection_tasks")
    op.drop_constraint("fk_collection_tasks_product_id", "collection_tasks", type_="foreignkey")
    op.drop_constraint("fk_collection_tasks_workspace_id", "collection_tasks", type_="foreignkey")
    op.drop_constraint("fk_collection_tasks_user_id", "collection_tasks", type_="foreignkey")
    op.drop_column("collection_tasks", "product_id")
    op.drop_column("collection_tasks", "workspace_id")
    op.drop_column("collection_tasks", "user_id")

    op.drop_table("product_influencers")
    op.execute("DROP INDEX IF EXISTS uq_global_influencer_platform_unique_id")
    op.drop_table("global_influencer_profiles")
    op.drop_table("products")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
    op.drop_table("users")
