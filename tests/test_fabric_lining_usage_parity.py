"""主料/里布同裁片时㎡用量应共用面积基准，禁止里布占比压低。"""
from __future__ import annotations

import re
import unittest

from structure_usage import apply_structure_usage_hints


def _parse_m2(usage: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*㎡", str(usage or ""))
    if not m:
        raise AssertionError(f"非㎡用量: {usage!r}")
    return float(m.group(1))


class FabricLiningUsageParityTest(unittest.TestCase):
    def _basketball_rows(self) -> list[dict]:
        return [
            {
                "name": "600D 牛津布",
                "spec": "140*90CM",
                "usage": "1码",
                "unit_price": "16.74元/㎡",
                "amount": 0,
            },
            {
                "name": "210D涤纶",
                "spec": "152cm",
                "usage": "-",
                "unit_price": "12.56元/㎡",
                "amount": 0,
            },
        ]

    def test_basketball_main_and_lining_share_body_area_not_ratio(self) -> None:
        st = (
            "篮球包。成品32×19×45cm。幅宽140CM。\n"
            "前片、后片、底片、侧片2片、拉链弧形盖。"
        )
        ps = {"LCM": 32, "WCM": 19, "HCM": 45}
        rows = self._basketball_rows()
        meta = apply_structure_usage_hints(rows, st, product_size=ps)
        self.assertGreater(meta.get("geometry_matched") or 0, 0)

        main_m2 = _parse_m2(rows[0]["usage"])
        lining_m2 = _parse_m2(rows[1]["usage"])
        self.assertGreater(lining_m2, 0.5, "里布不应被压到约0.25㎡")
        self.assertNotAlmostEqual(lining_m2, 0.25, delta=0.08)

        ratio = abs(main_m2 - lining_m2) / max(main_m2, 1e-6)
        self.assertLessEqual(
            ratio,
            0.30,
            f"同裁片主料/里布差异过大: {main_m2} vs {lining_m2}",
        )

        lining_note = str(rows[1].get("calc_note") or "")
        self.assertIn("共用", lining_note)
        self.assertNotIn("里布占比", lining_note)
        self.assertNotIn("×0.22", lining_note)

    def test_152cm_spec_not_treated_as_roll_width_for_m2(self) -> None:
        """规格「152cm」仅作门幅/规格展示，不得单独换算成约0.25㎡。"""
        rows = [
            {
                "name": "210D涤纶",
                "spec": "152cm",
                "usage": "1码",
                "unit_price": "12元/㎡",
                "amount": 0,
            },
        ]
        st = "收纳包。长32cm,宽19cm，高45cm"
        apply_structure_usage_hints(
            rows,
            st,
            product_size={"LCM": 32, "WCM": 19, "HCM": 45},
        )
        m2 = _parse_m2(rows[0]["usage"])
        self.assertGreater(m2, 0.45)

    def test_piece_area_table_same_basis_when_complete(self) -> None:
        from piece_area_table import attach_piece_area_calculation, body_piece_area_m2_with_loss

        payload = {
            "product_size": {"LCM": 32, "WCM": 19, "HCM": 45},
            "structure_text_snapshot": "篮球包；损耗15%",
            "items": self._basketball_rows(),
        }
        pac = attach_piece_area_calculation(payload)
        self.assertIsNotNone(pac)
        piece_m2 = body_piece_area_m2_with_loss(pac)
        assert piece_m2 is not None

        rows = self._basketball_rows()
        apply_structure_usage_hints(
            rows,
            payload["structure_text_snapshot"],
            product_size=payload["product_size"],
            piece_area_calculation=pac,
        )
        main_m2 = _parse_m2(rows[0]["usage"])
        lining_m2 = _parse_m2(rows[1]["usage"])
        self.assertAlmostEqual(main_m2, piece_m2, places=2)
        self.assertAlmostEqual(lining_m2, piece_m2, places=2)
        self.assertIn("裁片面积表", str(rows[0].get("calc_note") or ""))


if __name__ == "__main__":
    unittest.main()
