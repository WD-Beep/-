"""price_kb.xlsx 文件 hash 与磁盘向量缓存（避免源文件未变时重复 encode）。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# 自报项目根目录（embedding 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / ".embedding_cache"
MANIFEST_NAME = "manifest.json"
VECTORS_NAME = "vectors.npy"
CACHE_FORMAT_VERSION = 1


def compute_file_md5(path: Path) -> str:
    """对源 xlsx 做 MD5，用于判断是否需要重建索引。"""
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def row_content_key(raw_name: str, raw_spec: str) -> str:
    """物料行稳定键：供 manifest 与内存 cache 对齐。"""
    blob = f"{raw_name}\x1e{raw_spec}".encode("utf-8", errors="replace")
    return hashlib.md5(blob).hexdigest()


@dataclass
class PersistedManifest:
    version: int
    file_md5: str
    model_name: str
    dim: int
    row_keys: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "file_md5": self.file_md5,
            "model_name": self.model_name,
            "dim": self.dim,
            "row_keys": self.row_keys,
        }

    @staticmethod
    def from_json(obj: dict[str, Any]) -> PersistedManifest | None:
        try:
            return PersistedManifest(
                version=int(obj["version"]),
                file_md5=str(obj["file_md5"]),
                model_name=str(obj["model_name"]),
                dim=int(obj["dim"]),
                row_keys=list(obj["row_keys"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def cache_dir_ready() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def manifest_path() -> Path:
    return cache_dir_ready() / MANIFEST_NAME


def vectors_path() -> Path:
    return cache_dir_ready() / VECTORS_NAME


def try_load_vectors_and_manifest(
    *,
    file_md5: str,
    model_name: str,
    row_keys_live: list[str],
) -> np.ndarray | None:
    """若磁盘缓存与当前文件 md5 / 模型 / 行列一致则返回矩阵，否则返回 None。"""
    mp = manifest_path()
    vp = vectors_path()
    if not mp.is_file() or not vp.is_file():
        return None
    try:
        raw = json.loads(mp.read_text(encoding="utf-8"))
        man = PersistedManifest.from_json(raw)
        if man is None or man.version != CACHE_FORMAT_VERSION:
            return None
        if man.file_md5 != file_md5 or man.model_name != model_name:
            return None
        if man.row_keys != row_keys_live:
            return None
        mat = np.load(vp)
        mat = np.asarray(mat, dtype=np.float32)
        if mat.ndim != 2 or mat.shape[0] != len(row_keys_live):
            return None
        if mat.shape[1] != man.dim:
            return None
        return mat
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def save_manifest_and_vectors(
    *,
    file_md5: str,
    model_name: str,
    matrix: np.ndarray,
    row_keys: list[str],
) -> None:
    """写入 manifest + vectors.npy（原子替换由调用方覆盖写）。"""
    cache_dir_ready()
    mat = np.asarray(matrix, dtype=np.float32)
    if mat.ndim != 2:
        raise ValueError("matrix must be 2-D")
    dim = int(mat.shape[1])
    manifest = PersistedManifest(
        version=CACHE_FORMAT_VERSION,
        file_md5=file_md5,
        model_name=model_name,
        dim=dim,
        row_keys=list(row_keys),
    )
    mp = manifest_path()
    vp = vectors_path()
    np.save(vp, mat)
    tmp = mp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest.to_json(), ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(mp)
