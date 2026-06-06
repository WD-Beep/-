# -*- coding: utf-8 -*-
"""把「自报项目」有用文件备份到 D:\\完整版自动报价\\自报项目。

- 只复制，不修改、不删除源目录 d:\\自动报价旅行包\\...
- 排除 .tmp、.bak、__pycache__、运行锁等垃圾
- 保留 .env、data/quotes.db、源码、static、scripts、tests 等
"""
from __future__ import annotations

import shutil
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
TARGET = Path(r"D:\完整版自动报价\自报项目")
TARGET_PARENT = TARGET.parent

EXCLUDE_DIRS = {
    ".tmp",
    ".acceptance_runtime",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "node_modules",
    "tmpd1r24uug",
    "logs",
    ".git",
    ".idea",
    "reports",
    "uploads",
    ".embedding_cache",
}

EXCLUDE_FILE_SUFFIXES = (".pyc", ".bak", ".log", ".zip", ".xlsx", ".xls", ".csv")
EXCLUDE_FILE_NAMES = {".server.lock", ".server.pid"}

# 运行必需：完整版需保留，与 .gitignore 中「不提交」项区分
KEEP_FILES = {
    ".env",
    "quotes.db",
    "quotes.db-wal",
    "quotes.db-shm",
}


def should_skip(rel: Path) -> bool:
    parts = rel.parts
    part_set = set(parts)
    if part_set & EXCLUDE_DIRS:
        return True
    if "tests" in parts and "_pytest_data" in parts:
        return True
    name = rel.name
    if name in KEEP_FILES:
        return False
    if name in EXCLUDE_FILE_NAMES:
        return True
    if name.endswith(EXCLUDE_FILE_SUFFIXES):
        return True
    if ".bak-" in name or ".pre_recover_" in name:
        return True
    if name.endswith(".db") and name not in KEEP_FILES:
        return True
    return False


def main() -> None:
    if not (SOURCE / "server.py").is_file():
        raise SystemExit(f"源目录缺少 server.py: {SOURCE}")

    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src in SOURCE.rglob("*"):
        rel = src.relative_to(SOURCE)
        if should_skip(rel):
            continue
        dst = TARGET / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1

    repo = SOURCE.parent.parent
    for z in (
        repo / "autoquote-deploy-latest.zip",
        repo / "acquireKnowledge" / "autoquote-deploy-20260526-001220.zip",
    ):
        if z.is_file():
            TARGET_PARENT.mkdir(parents=True, exist_ok=True)
            shutil.copy2(z, TARGET_PARENT / z.name)
            print(f"  部署 zip -> {TARGET_PARENT / z.name}")
            break

    checks = ["server.py", ".env", "data/quotes.db", "static/app.js", "scripts/deploy_local.ps1"]
    print(f"已备份 {copied} 个文件 -> {TARGET}")
    print(f"源目录未改动: {SOURCE}")
    for c in checks:
        ok = (TARGET / c).exists()
        print(f"  {'OK' if ok else 'MISSING'} {c}")

    leaks = []
    for bad in ("data/uploads", "tests/_pytest_data", ".tmp", "logs"):
        if (TARGET / bad).exists():
            leaks.append(bad)
    if leaks:
        print("  WARN 目标仍含应排除目录:", ", ".join(leaks))


if __name__ == "__main__":
    main()
