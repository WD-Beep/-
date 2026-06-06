import unittest

from price_kb import (
    KBEntry,
    format_kb_entry_price_display,
    format_material_unit_price_text,
)


def _entry(name: str, spec: str, price: str) -> KBEntry:
    return KBEntry(
        raw_name=name,
        raw_spec=spec,
        raw_price=price,
        auto_learned=True,
        normalised_name=name.lower(),
        name_tokens=frozenset(),
        unit_price_value=6.5 if price == "6.5" else 10.5,
        unit_price_unit="",
        price_note="",
    )


class PriceKbDisplayTest(unittest.TestCase):
    def test_bare_number_fabric_becomes_yuan_per_yard(self) -> None:
        out = format_material_unit_price_text(
            "6.5",
            name="20D尼龙精品亮光防泼水",
            spec="150cm/0.09码",
            role="外料",
        )
        self.assertEqual(out, "6.5元/码")

    def test_kb_entry_display(self) -> None:
        ent = _entry("20D尼龙精品亮光防泼水", "150cm", "6.5")
        self.assertEqual(
            format_kb_entry_price_display(ent, role="外料", usage="-"),
            "6.5元/码",
        )

    def test_existing_full_unit_unchanged(self) -> None:
        self.assertEqual(
            format_material_unit_price_text("10.5元/㎡", name="210D涤纶里布", role="里料"),
            "10.5元/㎡",
        )

    def test_slash_y_normalized_for_fabric(self) -> None:
        self.assertEqual(
            format_material_unit_price_text("6.5/Y", name="20D尼龙", role="外料"),
            "6.5元/码",
        )

    def test_slash_y_for_puller_uses_piece(self) -> None:
        self.assertEqual(
            format_material_unit_price_text("0.3/Y", name="普通拉头", role="拉头"),
            "0.3元/个",
        )

    def test_lining_m2_usage(self) -> None:
        self.assertEqual(
            format_material_unit_price_text(
                "10.5",
                name="210D涤纶里布",
                usage="0.32㎡",
                role="里料",
            ),
            "10.5元/㎡",
        )


if __name__ == "__main__":
    unittest.main()
