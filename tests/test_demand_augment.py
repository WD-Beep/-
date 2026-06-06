import unittest

from demand_parser import Material, augment_materials_from_structure_keywords
from quote_engine import calculate_quote


class DemandAugmentTest(unittest.TestCase):
    def test_structure_keyword_adds_binding(self) -> None:
        base = [Material(role="外料", name="600D牛津", source="demand_form")]
        st = "主面料牛津，包边带捆边收口。"
        merged = augment_materials_from_structure_keywords(st, base)
        self.assertTrue(any(m.name == "包边带" for m in merged))

    def test_structure_keyword_peva(self) -> None:
        merged = augment_materials_from_structure_keywords(
            "里料用PEVA铝膜复合材料。",
            [],
        )
        self.assertTrue(any("PEVA" in m.name for m in merged))


class ManagementBundleBridgeTest(unittest.TestCase):
    def test_cost_bridge_material_plus_mgmt_pct(self) -> None:
        r = calculate_quote(
            {
                "items": [
                    {
                        "name": "面料",
                        "spec": "-",
                        "usage": "1㎡",
                        "unit_price": "100元/㎡",
                        "amount": 100.0,
                    },
                ],
                "management_loss_rate": 5,
            },
        )
        cb = r.get("cost_bridge") or {}
        self.assertEqual(cb.get("system_overhead_rule"), "demand_pct_of_material_total")
        self.assertAlmostEqual(float(cb.get("material_bundle_incl_mgmt_on_material_total") or 0), 105.0)


if __name__ == "__main__":
    unittest.main()
