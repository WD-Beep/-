import unittest

from demand_parser import parse_demand_from_rows


class DemandStrictTableMaterialsTest(unittest.TestCase):
    def test_missing_outer_material_does_not_use_structure_note_fallback(self) -> None:
        rows = [
            ["B. \u4ea7\u54c1\u89c4\u683c"],
            [
                "\u4ea7\u54c1\u7c7b\u578b",
                "\u4ea7\u54c1\u540d\u79f0/\u6b3e\u53f7",
                "L(cm)",
                "W(cm)",
                "H(cm)",
                "\u7ed3\u6784\u590d\u6742\u5ea6",
                "\u7ed3\u6784\u8bf4\u660e",
            ],
            [
                "\u8170\u5305",
                "\u659c\u630e\u5305",
                "37",
                "12",
                "17",
                "\u6807\u51c6",
                "\u56fd\u4ea7X-PAC\uff08\u4e3b\u4f53\u9762\u6599\uff0c\u4ef7\u683c\u4e3a50\u5143/\u7801\uff09\uff1a\u7528\u4e8e\u5305\u4f53\u6b63\u9762\n"
                "\u666e\u901a\u5c3c\u9f99\uff08\u5e95\u90e8\u8010\u78e8\u5c42\uff09\uff1a\u4ec5\u7528\u4e8e\u5305\u4f53\u6700\u4e0b\u65b9\u7684\u5e95\u90e8\u8d34\u7247\uff0c\u4ef7\u683c12\u5143/\u7801\n"
                "210D\u5c3c\u9f99\uff08\u5185\u886c\uff09\uff1a\u4ef7\u683c\u4e3a3\u5143/\u7801",
            ],
            ["C. \u6750\u6599\u4e0e\u914d\u4ef6\uff08\u6807\u51c6\u540d/\u7f16\u7801\uff09"],
            [
                "\u5916\u6599(\u6807\u51c6\u540d/\u7f16\u7801)",
                "\u5916\u6599\u989c\u8272",
                "\u91cc\u6599(\u6807\u51c6\u540d/\u7f16\u7801)",
                "\u91cc\u6599\u989c\u8272",
                "\u62c9\u94fe\u7c7b\u578b",
                "\u62c9\u5934\u7c7b\u578b",
                "\u6263\u5177\u7b49\u7ea7",
                "\u80a9\u5e26/\u7ec7\u5e26\u7c7b\u578b",
            ],
            [
                "#NAME?",
                "\u519b\u7eff\u8272",
                "210D\u6da4\u7eb6",
                "\u7070\u8272",
                "#5\u5c3c\u9f99\u62c9\u94fe\uff0cYKK\u9632\u6c34\u62c9\u94fe",
                "\u666e\u901a",
                "\u5851\u80f6\u6807\u51c6",
                "\u4eff\u5c3c\u9f99\u7ec7\u5e26",
            ],
            ["D. \u5de5\u827a\uff08\u591a\u9009\u7528;\u5206\u9694\uff09"],
            ["LOGO\u65b9\u5f0f(\u591a\u9009)"],
            ["\u4e1d\u5370"],
        ]

        out = parse_demand_from_rows(rows)
        names = [m.name for m in out.materials]

        self.assertIn("210D\u6da4\u7eb6", names)
        self.assertIn("#5\u5c3c\u9f99\u62c9\u94fe", names)
        self.assertIn("YKK\u9632\u6c34\u62c9\u94fe", names)
        self.assertNotIn("\u56fd\u4ea7X-PAC", names)
        self.assertNotIn("\u56fd\u4ea7X-PAC\uff08\u4e3b\u4f53\u9762\u6599", names)
        self.assertNotIn("\u4ec5\u7528\u4e8e\u5305\u4f53\u6700\u4e0b\u65b9\u7684\u5e95\u90e8\u8d34\u7247", names)
        self.assertNotIn("210D\u5c3c\u9f99\uff08\u5185\u886c\uff09", names)
        self.assertFalse(any(m.source.startswith("structure_inline") for m in out.materials))

    def test_structure_main_fabric_does_not_override_valid_outer_cell(self) -> None:
        rows = [
            ["B. \u4ea7\u54c1\u89c4\u683c"],
            ["\u4ea7\u54c1\u7c7b\u578b", "\u4ea7\u54c1\u540d\u79f0/\u6b3e\u53f7", "\u7ed3\u6784\u8bf4\u660e"],
            [
                "\u8170\u5305",
                "\u659c\u630e\u5305",
                "\u56fd\u4ea7X-PAC\uff08\u4e3b\u4f53\u9762\u6599\uff0c\u4ef7\u683c\u4e3a50\u5143/\u7801\uff09",
            ],
            ["C. \u6750\u6599\u4e0e\u914d\u4ef6\uff08\u6807\u51c6\u540d/\u7f16\u7801\uff09"],
            ["\u5916\u6599(\u6807\u51c6\u540d/\u7f16\u7801)", "\u91cc\u6599(\u6807\u51c6\u540d/\u7f16\u7801)"],
            ["600D\u725b\u6d25\u5e03", "210D\u6da4\u7eb6"],
            ["D. \u5de5\u827a\uff08\u591a\u9009\u7528;\u5206\u9694\uff09"],
        ]

        out = parse_demand_from_rows(rows)
        names = [m.name for m in out.materials]

        self.assertIn("600D\u725b\u6d25\u5e03", names)
        self.assertIn("210D\u6da4\u7eb6", names)
        self.assertNotIn("\u56fd\u4ea7X-PAC", names)


if __name__ == "__main__":
    unittest.main()
