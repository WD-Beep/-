from __future__ import annotations

import base64
from pathlib import Path

from sheet_media_enhancer import enrich_items_with_sheet_media_hints


def _load_fixture_xlsx_base64() -> str:
    # Reuse existing workbook fixture in repository.
    p = Path(__file__).resolve().parents[2] / "B260128 报价资料.xlsx"
    data = p.read_bytes()
    return base64.b64encode(data).decode("ascii")


def test_enhancer_noop_on_non_xlsx() -> None:
    items = [{"name": "A", "spec": "-", "usage": "-", "unit_price": "1", "amount": 1.0}]
    summary = enrich_items_with_sheet_media_hints(
        {"name": "a.csv", "content_base64": "aGVsbG8="},
        "Sheet1",
        items,
    )
    assert summary["applied"] == 0
    assert "calc_note" not in items[0]


def test_enhancer_runs_on_xlsx_without_breaking_items() -> None:
    items = [{"name": "A", "spec": "-", "usage": "-", "unit_price": "1", "amount": 1.0}]
    summary = enrich_items_with_sheet_media_hints(
        {"name": "B260128 报价资料.xlsx", "content_base64": _load_fixture_xlsx_base64()},
        "",
        items,
    )
    assert "applied" in summary
    assert isinstance(summary["applied"], int)
    assert items[0]["name"] == "A"
