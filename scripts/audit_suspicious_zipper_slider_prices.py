"""审计正式价格库与待审核队列中的异常拉头/拉链单价（只读，默认不删）。

用法：
  python scripts/audit_suspicious_zipper_slider_prices.py
  python scripts/audit_suspicious_zipper_slider_prices.py --fix-exception-markers

说明：
  - 默认仅列出疑似脏数据，不会修改正式 price_kb.xlsx。
  - --fix-exception-markers 仅将待审核队列里 marker=AUTO_QUOTE_SYNC 的异常行
    改为 AUTO_PENDING_PRICE（仍不删、不写正式库）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kb_data_quality import ACCESSORY_PRICE_OUTLIER_REASON, is_accessory_price_outlier
from price_admin_store import AUTO_PENDING_MARKER, AUTO_SYNC_MARKER, list_price_entries
from price_kb_paths import exception_path, official_kb_path


def _scan_official_kb() -> list[dict[str, str]]:
    path = official_kb_path()
    if not path.exists():
        print(f"[WARN] 正式价格库不存在: {path}")
        return []
    items, _total = list_price_entries(page=1, page_size=100000, kb_path=path)
    hits: list[dict[str, str]] = []
    for row in items:
        name = str(row.get("name") or "").strip()
        spec = str(row.get("spec") or "").strip()
        price = str(row.get("price") or "").strip()
        if is_accessory_price_outlier(name, price):
            hits.append({"source": "official_kb", "name": name, "spec": spec, "price": price})
    return hits


def _scan_exceptions() -> list[dict[str, object]]:
    path = exception_path()
    if not path.exists():
        print(f"[WARN] 待审核队列不存在: {path}")
        return []
    hits: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = str(obj.get("name") or obj.get("material_name") or "").strip()
        price = str(obj.get("price") or obj.get("new_price") or "").strip()
        if not is_accessory_price_outlier(name, price):
            continue
        hits.append(
            {
                "source": "price_exceptions",
                "exception_id": str(obj.get("exception_id") or obj.get("candidate_id") or ""),
                "name": name,
                "spec": str(obj.get("spec") or "").strip(),
                "price": price,
                "marker": str(obj.get("marker") or ""),
                "status": str(obj.get("status") or obj.get("exception_status") or ""),
            }
        )
    return hits


def _fix_exception_markers() -> int:
    path = exception_path()
    if not path.exists():
        return 0
    changed = 0
    out_lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        name = str(obj.get("name") or obj.get("material_name") or "").strip()
        price = str(obj.get("price") or obj.get("new_price") or "").strip()
        marker = str(obj.get("marker") or "")
        if (
            marker == AUTO_SYNC_MARKER
            and is_accessory_price_outlier(name, price)
        ):
            obj["marker"] = AUTO_PENDING_MARKER
            obj["exception_reason"] = "拉链拉头单价异常"
            note = str(obj.get("note") or "")
            if ACCESSORY_PRICE_OUTLIER_REASON not in note:
                obj["note"] = f"数据质量待确认：{ACCESSORY_PRICE_OUTLIER_REASON}。{note}".strip()
            changed += 1
        out_lines.append(json.dumps(obj, ensure_ascii=False))
    if changed:
        path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="审计异常拉头/拉链单价")
    parser.add_argument(
        "--fix-exception-markers",
        action="store_true",
        help="将待审核队列中 AUTO_QUOTE_SYNC 的异常行改为 AUTO_PENDING_PRICE",
    )
    args = parser.parse_args()

    kb_hits = _scan_official_kb()
    exc_hits = _scan_exceptions()

    print(f"正式库路径: {official_kb_path()}")
    print(f"待审核队列: {exception_path()}")
    print(f"异常拉头/拉链（正式库）: {len(kb_hits)}")
    for item in kb_hits:
        print(f"  - [{item['name']}] spec={item['spec'] or '-'} price={item['price']}")

    print(f"异常拉头/拉链（待审核队列）: {len(exc_hits)}")
    for item in exc_hits:
        print(
            f"  - [{item['name']}] price={item['price']} marker={item['marker']} "
            f"id={item['exception_id']}"
        )

    if kb_hits:
        print(
            "\n建议：在后台价格管理删除或修正上述正式库行，勿直接脚本删库。"
            " 典型脏数据：金色拉头 60元/个、金属拉链 120元/条。"
        )

    if args.fix_exception_markers:
        n = _fix_exception_markers()
        print(f"\n已更新待审核 marker: {n} 条 -> {AUTO_PENDING_MARKER}")
    elif exc_hits:
        print(
            "\n可选：python scripts/audit_suspicious_zipper_slider_prices.py --fix-exception-markers"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
