"""写入标价表后：强制重载 PriceKB 内存单例并重建 EmbeddingIndex（非仅打日志）。"""

from __future__ import annotations

import threading
from pathlib import Path

from embedding.embedding_index import get_embedding_index
from price_kb import get_price_kb, reset_price_kb
from price_kb_paths import official_kb_path

# smart_lookup miss 异步闭环与磁盘写共用，避免与读路径交叉
KNOWLEDGE_MUTATION_LOCK = threading.Lock()


def knowledge_reload_hook(kb_path: Path | None = None) -> None:
    """
    PriceKB + Embedding 写入成功后的刷新链（须在 apply_kb_write 成功后调用）：
    1) reset_price_kb() —— 清空 PriceKB 单例并联 invalidate_embedding_index；
    2) get_price_kb() —— **重新读盘**构造 PriceKB；
    3) get_embedding_index().prepare(...) —— 按新文件 md5 重装向量；锁内即 READY 且代数与 _kb_disk_mutation_seq 对齐。
    任一失败可由调用方捕获；语义层在未完成 prepare 前应处于 mark_unready / is_ready=False。
    """
    path = Path(kb_path or official_kb_path()).resolve()
    reset_price_kb()
    kb = get_price_kb(None if path == official_kb_path() else path)
    get_embedding_index().prepare(kb, path)
    print(
        f"[knowledge-reload] PriceKB reloaded size={kb.size}, embedding prepared for md5-change",
        flush=True,
    )
