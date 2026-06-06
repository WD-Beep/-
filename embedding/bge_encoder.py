"""BGE-M3 编码器封装：统一 encode / batch_encode，不修改模型权重。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

_DEFAULT_MODEL = os.environ.get("BGE_M3_MODEL_NAME", "BAAI/bge-m3")
_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}

# Do not let transformers/huggingface probe the network during quote requests.
# A local model path or an already populated local HF cache can still be used.
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("BGE_LOCAL_FILES_ONLY", "1")


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUTHY


def embedding_enabled() -> bool:
    raw = os.environ.get("QUOTE_EMBEDDING_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() not in _FALSY


def _offline_mode_requested(model_name: str) -> bool:
    # Default to local-only unless an operator explicitly opts into online loads.
    if not _env_truthy("BGE_ALLOW_ONLINE_DOWNLOAD"):
        return True
    if _env_truthy("TRANSFORMERS_OFFLINE") or _env_truthy("HF_HUB_OFFLINE"):
        return True
    if _env_truthy("BGE_LOCAL_FILES_ONLY"):
        return True
    path = Path(model_name)
    try:
        return path.exists() and (path.is_dir() or path.is_file())
    except OSError:
        return False


class BGEEncoder:
    """SentenceTransformer(BGE-M3) 懒加载；加载失败时标记 unavailable，不阻塞报价主流程。"""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = str(model_name or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
        self._backend: Any = None
        self._available: bool | None = None
        self._load_error: str | None = None

    @property
    def available(self) -> bool:
        if self._available is False:
            return False
        if self._backend is not None:
            return True
        try:
            self._ensure_backend()
            return self._available is True
        except Exception:
            return False

    @property
    def unavailable_reason(self) -> str | None:
        return self._load_error

    def _ensure_backend(self) -> None:
        if self._backend is not None:
            return
        if not embedding_enabled():
            self._mark_unavailable("QUOTE_EMBEDDING_ENABLED=0")
            raise RuntimeError(self._load_error or "BGE embedding disabled")
        if self._available is False:
            raise RuntimeError(self._load_error or "BGE embedding unavailable")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            self._mark_unavailable(str(exc))
            raise RuntimeError(
                "需要安装 sentence-transformers：`pip install sentence-transformers`",
            ) from exc
        local_only = _offline_mode_requested(self.model_name)
        try:
            self._backend = SentenceTransformer(
                self.model_name,
                local_files_only=local_only,
            )
            self._available = True
        except Exception as exc:  # noqa: BLE001
            self._mark_unavailable(str(exc))
            print(
                f"[embedding] BGEEncoder load failed"
                f" model={self.model_name!r} local_files_only={local_only}: {exc}",
                flush=True,
            )
            raise RuntimeError(self._load_error or "BGE embedding unavailable") from exc

    def _mark_unavailable(self, reason: str) -> None:
        self._available = False
        self._load_error = str(reason or "unknown").strip() or "unknown"
        self._backend = None

    def batch_encode(self, texts: list[str], *, batch_size: int = 64) -> np.ndarray:
        """批量编码，返回 float32 矩阵 (n, dim)，行已 L2 归一化。"""
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        if not self.available:
            print(
                f"[embedding] batch_encode skipped (encoder unavailable)"
                f"{': ' + self._load_error if self._load_error else ''}",
                flush=True,
            )
            return np.zeros((len(texts), 0), dtype=np.float32)
        try:
            self._ensure_backend()
        except Exception:
            return np.zeros((len(texts), 0), dtype=np.float32)
        assert self._backend is not None
        try:
            arr = self._backend.encode(
                list(texts),
                batch_size=max(1, min(batch_size, len(texts))),
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._mark_unavailable(str(exc))
            print(f"[embedding] batch_encode failed: {exc}", flush=True)
            return np.zeros((len(texts), 0), dtype=np.float32)
        mat = np.asarray(arr, dtype=np.float32)
        if mat.ndim == 1:
            mat = mat.reshape(1, -1)
        if mat.size == 0 or mat.shape[1] == 0:
            return np.zeros((len(texts), 0), dtype=np.float32)
        return self._l2_rows(mat)

    def encode(self, text: str) -> np.ndarray:
        """单条查询编码，返回一维单位向量；空串或不可用时返回 size 0 数组。"""
        key = (text or "").strip()
        if not key:
            return np.zeros(0, dtype=np.float32)
        if not self.available:
            return np.zeros(0, dtype=np.float32)
        try:
            self._ensure_backend()
        except Exception:
            return np.zeros(0, dtype=np.float32)
        assert self._backend is not None
        try:
            vec = self._backend.encode(
                key,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # noqa: BLE001
            self._mark_unavailable(str(exc))
            print(f"[embedding] encode failed: {exc}", flush=True)
            return np.zeros(0, dtype=np.float32)
        row = np.asarray(vec, dtype=np.float32).reshape(-1)
        if row.size == 0:
            return row
        return self._l2_row(row)

    @staticmethod
    def _l2_row(v: np.ndarray) -> np.ndarray:
        n = float(np.linalg.norm(v))
        if n <= 0:
            return v
        return (v / n).astype(np.float32, copy=False)

    @staticmethod
    def _l2_rows(m: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (m / norms).astype(np.float32, copy=False)
