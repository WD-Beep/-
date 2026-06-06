"""工程级 Embedding 索引：单例 + BGE 封装 + 磁盘 hash 缓存 + 纯内存检索。"""

from __future__ import annotations

import threading
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional

import numpy as np

from embedding import cache_manager as cm
from embedding.bge_encoder import BGEEncoder, embedding_enabled
from price_kb import KBEntry, PriceKB
from price_kb_paths import official_kb_path

_singleton: Optional["EmbeddingIndex"] = None
_singleton_lock = threading.Lock()

# 向量索引与 KB 版本对齐闸门：DIRTY 时语义检索不得在旧矩阵上产出结果
GLOBAL_INDEX_STATE: str = "READY"


def get_embedding_index() -> "EmbeddingIndex":
    """全局唯一 EmbeddingIndex 句柄（懒创建壳；向量在 prepare 阶段注入）。"""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = EmbeddingIndex()
        return _singleton


def invalidate_embedding_index() -> None:
    """PriceKB 重置或源文件逻辑变更时清空内存索引状态（单例对象保留）。"""
    with _singleton_lock:
        if _singleton is not None:
            _singleton.invalidate()


class EmbeddingIndex:
    """管理 BGE-M3 编码器与物料向量矩阵；build 仅在 prepare，search 不做 batch 语料编码。"""

    def __init__(self) -> None:
        self._encoder = BGEEncoder()
        self._prepare_lock = threading.Lock()
        self._ready = False
        self._source_md5: str | None = None
        self._resolved_path: Path | None = None
        self._rows: list[KBEntry] = []
        self._matrix: np.ndarray | None = None
        # key = 行内容 md5（与 disk manifest 一致）；value = 行向量副本
        self._material_embedding_cache: dict[str, np.ndarray] = {}
        # 与 _source_md5 对应快照，用于避免每次 is_ready 全文件 md5；文件被改写后 mtime/size 必变
        self._indexed_stat: tuple[float, int] | None = None
        self._committed_kb_version: int = -1

    def is_ready(self) -> bool:
        """仅当最近一次 prepare 与磁盘 price_kb.xlsx **当前**内容一致时为 True（hash + stat 兜底）。"""
        if not embedding_enabled():
            return False
        if GLOBAL_INDEX_STATE != "READY":
            return False
        if not self._ready:
            return False
        path = self._resolved_path
        if path is None or self._source_md5 is None:
            return False
        if not path.is_file():
            with self._prepare_lock:
                self._soft_reset_locked()
            return False
        try:
            st = path.stat()
        except OSError:
            return False
        quick = False
        if self._indexed_stat is not None:
            imt, isize = self._indexed_stat
            quick = (
                abs(st.st_mtime - imt) < 1e-6
                and int(st.st_size) == int(isize)
            )
        try:
            if not quick:
                live_md5 = cm.compute_file_md5(path)
                if live_md5 != self._source_md5:
                    with self._prepare_lock:
                        self._soft_reset_locked()
                    return False
                self._indexed_stat = (st.st_mtime, int(st.st_size))
        except OSError:
            with self._prepare_lock:
                self._soft_reset_locked()
            return False

        if not self._rows:
            return True
        return self._matrix is not None and self._matrix.size > 0

    def mark_unready(self) -> None:
        """磁盘即将或已经变更、但尚未 prepare 时使用；禁止语义检索读到旧向量。"""
        global GLOBAL_INDEX_STATE
        with self._prepare_lock:
            self._ready = False
            GLOBAL_INDEX_STATE = "DIRTY"

    def commit(self, kb_version: int) -> None:
        """兼容占位：对齐版本已在 prepare 锁内原子完成，禁止依赖外部拆分 commit。"""
        _ = kb_version

    def invalidate(self) -> None:
        with self._prepare_lock:
            self._soft_reset_locked()

    @property
    def material_embedding_cache(self) -> Mapping[str, np.ndarray]:
        """只读视图：物料行哈希 → 向量（与磁盘 manifest.row_keys 顺序一致）。"""
        return MappingProxyType(dict(self._material_embedding_cache))

    def _soft_reset_locked(self) -> None:
        global GLOBAL_INDEX_STATE
        self._ready = False
        self._source_md5 = None
        self._resolved_path = None
        self._rows = []
        self._matrix = None
        self._material_embedding_cache.clear()
        self._indexed_stat = None
        self._committed_kb_version = -1
        GLOBAL_INDEX_STATE = "DIRTY"

    def _finalize_prepare_commit_locked(self, kb_version: int) -> None:
        """prepare 锁内尾声：仅此路径将索引标为 READY 并与磁盘代数对齐（与 prepare 成功原子捆绑）。"""
        global GLOBAL_INDEX_STATE
        self._committed_kb_version = int(kb_version)
        GLOBAL_INDEX_STATE = "READY"

    def prepare(
        self,
        price_kb: PriceKB,
        kb_source_path: Path | None = None,
        *,
        expected_kb_version: int | None = None,
    ) -> None:
        """读盘 hash、按需 encode；凡成功路径在锁内即完成 READY + 代数对齐（不再依赖外部 commit）。"""
        if not embedding_enabled():
            print(
                "[embedding] prepare skipped: QUOTE_EMBEDDING_ENABLED=0; "
                "semantic search disabled, PriceKB rule lookup still works",
                flush=True,
            )
            return
        _ = expected_kb_version  # 保留签名；代数唯一源见 get_kb_disk_mutation_seq
        path = kb_source_path or official_kb_path()
        path = path.resolve()
        if not path.is_file():
            print(f"[embedding] prepare skipped: file not found {path}", flush=True)
            return

        with self._prepare_lock:
            from price_kb import get_kb_disk_mutation_seq

            v_align = int(get_kb_disk_mutation_seq())
            entries: list[KBEntry] = list(price_kb._entries)  # noqa: SLF001
            row_keys = [cm.row_content_key(e.raw_name, e.raw_spec) for e in entries]
            file_md5 = cm.compute_file_md5(path)

            try:
                st_done = path.stat()
                stat_pair = (st_done.st_mtime, int(st_done.st_size))
            except OSError:
                stat_pair = None

            if (
                self._ready
                and GLOBAL_INDEX_STATE == "READY"
                and self._source_md5 == file_md5
                and self._resolved_path == path
                and self._committed_kb_version == v_align
                and (
                    len(entries) == 0
                    or (
                        self._matrix is not None
                        and self._matrix.shape[0] == len(entries)
                        and len(row_keys) == len(entries)
                    )
                )
            ):
                self._rows = entries
                if stat_pair is not None:
                    self._indexed_stat = stat_pair
                self._finalize_prepare_commit_locked(v_align)
                return

            if not entries:
                self._rows = []
                self._matrix = None
                self._material_embedding_cache.clear()
                self._ready = True
                self._source_md5 = file_md5
                self._resolved_path = path
                if stat_pair is not None:
                    self._indexed_stat = stat_pair
                print("[embedding] Embedding index ready（PriceKB 无条目，语义检索跳过）", flush=True)
                self._finalize_prepare_commit_locked(v_align)
                return

            restored = cm.try_load_vectors_and_manifest(
                file_md5=file_md5,
                model_name=self._encoder.model_name,
                row_keys_live=row_keys,
            )
            if restored is not None:
                self._matrix = restored.astype(np.float32, copy=False)
                self._rows = entries
                self._rebuild_embedding_cache(row_keys)
                self._ready = True
                self._source_md5 = file_md5
                self._resolved_path = path
                if stat_pair is not None:
                    self._indexed_stat = stat_pair
                print(
                    "[embedding] Embedding index ready / disk cache md5-hit "
                    f"({len(entries)} rows, md5[:8]={file_md5[:8]}…)",
                    flush=True,
                )
                self._finalize_prepare_commit_locked(v_align)
                return

            if not self._encoder.available:
                reason = self._encoder.unavailable_reason or "encoder unavailable"
                print(
                    f"[embedding] prepare skipped batch_encode ({reason}); "
                    "semantic search disabled, PriceKB rule lookup still works",
                    flush=True,
                )
                return

            texts = [
                (f"{e.raw_name} {e.raw_spec}".strip() or e.raw_name) for e in entries
            ]
            try:
                mat = self._encoder.batch_encode(texts)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[embedding] prepare batch_encode failed ({exc}); semantic search disabled",
                    flush=True,
                )
                return
            if mat.size == 0 or mat.shape[0] != len(entries) or mat.shape[1] == 0:
                print(
                    "[embedding] prepare got empty embedding matrix; semantic search disabled",
                    flush=True,
                )
                return
            self._matrix = mat
            self._rows = entries
            self._rebuild_embedding_cache(row_keys)
            try:
                cm.save_manifest_and_vectors(
                    file_md5=file_md5,
                    model_name=self._encoder.model_name,
                    matrix=mat,
                    row_keys=row_keys,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[embedding] disk cache save failed (non-fatal): {exc}", flush=True)
            self._ready = True
            self._source_md5 = file_md5
            self._resolved_path = path
            if stat_pair is not None:
                self._indexed_stat = stat_pair
            print(
                "[embedding] Embedding index ready / batch_encode + disk save "
                f"({len(entries)} rows, md5[:8]={file_md5[:8]}…)",
                flush=True,
            )
            self._finalize_prepare_commit_locked(v_align)

    def _rebuild_embedding_cache(self, row_keys: list[str]) -> None:
        """将矩阵行同步到字典缓存（按需 O(1) 取单行向量）。"""
        self._material_embedding_cache.clear()
        if self._matrix is None:
            return
        for i, key in enumerate(row_keys):
            self._material_embedding_cache[key] = self._matrix[i].copy()

    def row_vector_by_key(self, key: str) -> np.ndarray | None:
        """调试或扩展用：按 material 行 hash 取向量。"""
        return self._material_embedding_cache.get(key)

    def search(self, query: str, *, top_k: int = 5) -> list[tuple[KBEntry, float]]:
        """查询相位：单次 encode(query) + 余弦（归一化点积）；禁止在此处 build 或 batch_encode 物料。"""
        if not self.is_ready():
            return []
        if not self._rows:
            return []
        assert self._matrix is not None
        q = (query or "").strip()
        if not q:
            return []
        try:
            qvec = self._encoder.encode(q)
        except Exception as exc:  # noqa: BLE001
            print(f"[embedding] search encode failed: {exc}", flush=True)
            return []
        if qvec.size == 0 or qvec.shape[0] != self._matrix.shape[1]:
            return []
        sims = self._matrix @ qvec
        k = max(1, min(int(top_k), sims.shape[0]))
        idx = np.argpartition(-sims, kth=k - 1)[:k]
        idx = idx[np.argsort(-sims[idx])]
        return [(self._rows[int(i)], float(sims[int(i)])) for i in idx]


def warm_prepare(price_kb: PriceKB | None = None, kb_source_path: Path | None = None) -> None:
    """提供给 server 的统一预热入口。"""
    if not embedding_enabled():
        print("[embedding] warm_prepare skipped: QUOTE_EMBEDDING_ENABLED=0", flush=True)
        return
    from price_kb import get_price_kb  # noqa: PLC0415

    try:
        kb = price_kb or get_price_kb()
    except Exception as exc:  # noqa: BLE001
        print(f"[embedding] prepare skipped（无法加载 PriceKB）: {exc}", flush=True)
        return
    try:
        get_embedding_index().prepare(kb, kb_source_path or official_kb_path())
    except Exception as exc:  # noqa: BLE001
        print(f"[embedding] warm_prepare failed: {exc}", flush=True)
