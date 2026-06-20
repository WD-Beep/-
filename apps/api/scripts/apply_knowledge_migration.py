"""直接执行 032 知识库 migration（当 alembic CLI 不可用时备用）。"""

import asyncio

from sqlalchemy import text

from app.db.session import async_session_factory

SQL = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_knowledge_bases_product_id ON knowledge_bases(product_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_bases_workspace_id ON knowledge_bases(workspace_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_bases_updated_at ON knowledge_bases(updated_at);

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id SERIAL PRIMARY KEY,
    knowledge_base_id INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    file_name VARCHAR(512) NOT NULL,
    file_type VARCHAR(16) NOT NULL,
    source_path VARCHAR(1024),
    uploaded_file_path VARCHAR(1024),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_knowledge_documents_knowledge_base_id ON knowledge_documents(knowledge_base_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_documents_product_id ON knowledge_documents(product_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_documents_status ON knowledge_documents(status);
CREATE INDEX IF NOT EXISTS ix_knowledge_documents_file_type ON knowledge_documents(file_type);
CREATE INDEX IF NOT EXISTS ix_knowledge_documents_updated_at ON knowledge_documents(updated_at);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    knowledge_base_id INTEGER NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    title VARCHAR(512),
    content TEXT NOT NULL,
    embedding JSONB,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_document_id ON knowledge_chunks(document_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_knowledge_base_id ON knowledge_chunks(knowledge_base_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_product_id ON knowledge_chunks(product_id);
"""


async def main() -> None:
    async with async_session_factory() as db:
        for statement in SQL.split(";"):
            stmt = statement.strip()
            if stmt:
                await db.execute(text(stmt))
        await db.execute(
            text(
                """
                INSERT INTO alembic_version (version_num)
                SELECT '032_knowledge_base'
                WHERE NOT EXISTS (
                    SELECT 1 FROM alembic_version WHERE version_num = '032_knowledge_base'
                )
                """
            )
        )
        await db.commit()
    print("Knowledge base tables ready.")


if __name__ == "__main__":
    asyncio.run(main())
