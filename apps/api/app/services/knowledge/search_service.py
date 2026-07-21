# 文件说明：后端知识库服务，负责资料解析、保存和检索；当前文件：search service
"""知识库关键词检索（可后续扩展向量 embedding）。"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.schemas.knowledge import KnowledgeSearchResult


def _tokenize(query: str) -> list[str]:
    query = query.strip().lower()
    if not query:
        return []
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", query)
    return [token for token in tokens if len(token) >= 2]


def _score_chunk(query_tokens: list[str], *, title: str | None, content: str) -> float:
    if not query_tokens:
        return 0.0
    haystack = f"{title or ''}\n{content}".lower()
    score = 0.0
    for token in query_tokens:
        if token in haystack:
            score += 1.0
            if title and token in title.lower():
                score += 0.5
    return score


class KnowledgeSearchService:
    @staticmethod
    async def search(
        db: AsyncSession,
        *,
        product_id: int,
        query: str,
        knowledge_base_id: int | None = None,
        limit: int = 8,
    ) -> list[KnowledgeSearchResult]:
        tokens = _tokenize(query)
        if not tokens:
            return []

        stmt = (
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.product_id == product_id,
                KnowledgeDocument.status == "ready",
            )
        )
        if knowledge_base_id:
            stmt = stmt.where(KnowledgeChunk.knowledge_base_id == knowledge_base_id)

        result = await db.execute(stmt)
        rows = result.all()
        scored: list[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []
        for chunk, document in rows:
            score = _score_chunk(tokens, title=chunk.title, content=chunk.content)
            if score <= 0:
                continue
            scored.append((score, chunk, document))

        scored.sort(key=lambda item: item[0], reverse=True)
        output: list[KnowledgeSearchResult] = []
        for score, chunk, document in scored[:limit]:
            metadata = dict(chunk.chunk_metadata or {})
            section = None
            if "page" in metadata:
                section = f"第 {metadata['page']} 页"
            elif "slide" in metadata:
                section = f"幻灯片 {metadata['slide']}"
            output.append(
                KnowledgeSearchResult(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    document_name=document.file_name,
                    title=chunk.title,
                    section=section,
                    content=chunk.content,
                    score=round(score, 2),
                    metadata=metadata,
                )
            )
        return output
