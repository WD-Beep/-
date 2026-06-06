"""本地语义索引（不落外部向量数据库）。"""

from embedding.embedding_index import (
    EmbeddingIndex,
    get_embedding_index,
    invalidate_embedding_index,
    warm_prepare,
)

__all__ = [
    "EmbeddingIndex",
    "get_embedding_index",
    "invalidate_embedding_index",
    "warm_prepare",
]
