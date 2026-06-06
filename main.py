from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_INPUT = Path("data/sample_quotes.csv")
DEFAULT_REPORT = Path("reports/latest_report.md")
DEFAULT_KNOWLEDGE = Path("knowledge_updates/pending_knowledge.jsonl")

HIGH_ERROR_RATE = 0.08
MEDIUM_ERROR_RATE = 0.03


@dataclass(frozen=True)
class QuoteRecord:
    quote_id: str
    product_name: str
    category: str
    material: str
    process: str
    quantity: int
    ai_cost: float
    manual_cost: float
    ai_reason: str
    manual_reason: str

    @property
    def diff(self) -> float:
        return self.ai_cost - self.manual_cost

    @property
    def abs_diff(self) -> float:
        return abs(self.diff)

    @property
    def error_rate(self) -> float:
        if self.manual_cost == 0:
            return 0.0
        return self.abs_diff / self.manual_cost

    @property
    def direction(self) -> str:
        if math.isclose(self.diff, 0.0, abs_tol=0.01):
            return "match"
        return "overpriced" if self.diff > 0 else "underpriced"


def parse_money(value: str) -> float:
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return 0.0
    return float(cleaned)


def load_quotes(path: Path) -> list[QuoteRecord]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = csv.DictReader(file)
        records: list[QuoteRecord] = []
        for row in rows:
            records.append(
                QuoteRecord(
                    quote_id=row.get("quote_id", "").strip(),
                    product_name=row.get("product_name", "").strip(),
                    category=row.get("category", "").strip(),
                    material=row.get("material", "").strip(),
                    process=row.get("process", "").strip(),
                    quantity=int(row.get("quantity", "0") or 0),
                    ai_cost=parse_money(row.get("ai_cost", "0")),
                    manual_cost=parse_money(row.get("manual_cost", "0")),
                    ai_reason=row.get("ai_reason", "").strip(),
                    manual_reason=row.get("manual_reason", "").strip(),
                )
            )
    return records


def classify_error(record: QuoteRecord) -> str:
    if record.error_rate >= HIGH_ERROR_RATE:
        return "high"
    if record.error_rate >= MEDIUM_ERROR_RATE:
        return "medium"
    return "low"


def infer_gaps(record: QuoteRecord) -> list[str]:
    text = f"{record.ai_reason} {record.manual_reason}".lower()
    gaps: list[str] = []

    signals = {
        "loss_rate": ["loss", "waste", "损耗", "报废"],
        "labor_cost": ["labor", "人工", "工时", "装配"],
        "surface_process": ["surface", "spray", "paint", "coating", "表面", "喷涂", "电镀"],
        "packaging": ["package", "packaging", "包装"],
        "freight": ["freight", "shipping", "运输", "运费", "物流"],
        "tax": ["tax", "税"],
        "moq": ["moq", "minimum", "起订量", "最小订单"],
        "outsourcing": ["outsource", "外协", "外发"],
    }

    for gap, keywords in signals.items():
        if any(keyword in text for keyword in keywords):
            gaps.append(gap)

    if record.direction == "underpriced" and not gaps:
        gaps.extend(["missing_surcharge", "incomplete_process_route"])
    if record.direction == "overpriced" and not gaps:
        gaps.extend(["outdated_price_reference", "too_conservative_margin"])

    return sorted(set(gaps))


def summarize(records: Iterable[QuoteRecord]) -> dict:
    by_group: dict[tuple[str, str, str], list[QuoteRecord]] = defaultdict(list)
    total_abs_error = 0.0
    total_manual = 0.0
    counts = {"high": 0, "medium": 0, "low": 0}
    directions = {"underpriced": 0, "overpriced": 0, "match": 0}
    gap_counts: dict[str, int] = defaultdict(int)

    record_list = list(records)
    for record in record_list:
        by_group[(record.category, record.material, record.process)].append(record)
        total_abs_error += record.abs_diff
        total_manual += record.manual_cost
        counts[classify_error(record)] += 1
        directions[record.direction] += 1
        for gap in infer_gaps(record):
            gap_counts[gap] += 1

    group_rows = []
    for (category, material, process), group_records in by_group.items():
        avg_error_rate = sum(item.error_rate for item in group_records) / len(group_records)
        avg_diff = sum(item.diff for item in group_records) / len(group_records)
        group_rows.append(
            {
                "category": category,
                "material": material,
                "process": process,
                "count": len(group_records),
                "avg_error_rate": avg_error_rate,
                "avg_diff": avg_diff,
            }
        )

    group_rows.sort(key=lambda item: item["avg_error_rate"], reverse=True)

    return {
        "total": len(record_list),
        "weighted_error_rate": total_abs_error / total_manual if total_manual else 0.0,
        "counts": counts,
        "directions": directions,
        "gap_counts": dict(sorted(gap_counts.items(), key=lambda item: item[1], reverse=True)),
        "groups": group_rows,
    }


def build_knowledge_item(record: QuoteRecord) -> dict:
    gaps = infer_gaps(record)
    return {
        "id": f"quote-feedback-{record.quote_id}",
        "type": "quote_cost_feedback",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "product_name": record.product_name,
        "category": record.category,
        "material": record.material,
        "process": record.process,
        "quantity": record.quantity,
        "ai_cost": record.ai_cost,
        "manual_cost": record.manual_cost,
        "difference": round(record.diff, 4),
        "error_rate": round(record.error_rate, 6),
        "direction": record.direction,
        "severity": classify_error(record),
        "suspected_gaps": gaps,
        "lesson": build_lesson(record, gaps),
        "source_quote_id": record.quote_id,
    }


def build_lesson(record: QuoteRecord, gaps: list[str]) -> str:
    direction_text = "偏低" if record.direction == "underpriced" else "偏高"
    if record.direction == "match":
        return f"{record.product_name} 的 AI 成本价与人工成本价基本一致，可作为正样本保留。"

    gap_text = "、".join(gaps) if gaps else "未知因素"
    return (
        f"{record.product_name} 在 {record.material}/{record.process} 场景下 AI 报价{direction_text}，"
        f"误差率 {record.error_rate:.2%}。下次报价应重点检查：{gap_text}。"
    )


def write_knowledge_updates(records: Iterable[QuoteRecord], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            if classify_error(record) == "low":
                continue
            file.write(json.dumps(build_knowledge_item(record), ensure_ascii=False) + "\n")
            written += 1
    return written


def write_report(records: list[QuoteRecord], summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# 自动报价反馈学习报告",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 报价记录数：{summary['total']}",
        f"- 加权平均误差率：{summary['weighted_error_rate']:.2%}",
        f"- 偏低次数：{summary['directions']['underpriced']}",
        f"- 偏高次数：{summary['directions']['overpriced']}",
        f"- 基本一致次数：{summary['directions']['match']}",
        "",
        "## 误差等级",
        "",
        f"- 高误差：{summary['counts']['high']}",
        f"- 中误差：{summary['counts']['medium']}",
        f"- 低误差：{summary['counts']['low']}",
        "",
        "## 高频疑似缺口",
        "",
    ]

    if summary["gap_counts"]:
        for gap, count in summary["gap_counts"].items():
            lines.append(f"- {gap}: {count}")
    else:
        lines.append("- 暂无明显缺口")

    lines.extend(["", "## 高风险组合", ""])
    for group in summary["groups"][:10]:
        lines.append(
            "- "
            f"{group['category']} / {group['material']} / {group['process']}："
            f"{group['count']} 条，平均误差率 {group['avg_error_rate']:.2%}，"
            f"平均差额 {group['avg_diff']:.2f}"
        )

    lines.extend(["", "## 需要沉淀的报价教训", ""])
    for record in records:
        if classify_error(record) == "low":
            continue
        lines.append(f"- {build_lesson(record, infer_gaps(record))}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze(input_path: Path, report_path: Path, knowledge_path: Path) -> None:
    records = load_quotes(input_path)
    summary = summarize(records)
    write_report(records, summary, report_path)
    knowledge_count = write_knowledge_updates(records, knowledge_path)

    print(f"Loaded {len(records)} quote records")
    print(f"Weighted error rate: {summary['weighted_error_rate']:.2%}")
    print(f"Report written to: {report_path}")
    print(f"Knowledge updates written to: {knowledge_path} ({knowledge_count} items)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare manual cost prices with AI cost prices and generate quote-learning feedback."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"CSV file with quote feedback records. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help=f"Markdown report output path. Default: {DEFAULT_REPORT}",
    )
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=DEFAULT_KNOWLEDGE,
        help=f"JSONL knowledge update output path. Default: {DEFAULT_KNOWLEDGE}",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    analyze(args.input, args.report, args.knowledge)


if __name__ == "__main__":
    main()
