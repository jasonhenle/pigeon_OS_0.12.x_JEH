"""Pure SVG tree helpers extracted from main_settings (ids, lookup, paint, visibility)."""

from __future__ import annotations

import os
import sys
import unittest
import xml.etree.ElementTree as ET

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon.widgets import main_settings, settings_svg_tree as tree  # noqa: E402

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg">'
    '<g id="main_box1"><rect id="main_x5F_btn_0000016089123456789012" fill="#fff"/></g>'
    '<g id="other"><text id="label"><tspan>old</tspan></text></g>'
    "</svg>"
)


class SvgIdTests(unittest.TestCase):
    def test_encode_decode_round_trip(self) -> None:
        for logical in ("main_settings", "a-b.c|d", "x y"):
            self.assertEqual(tree.decode_svg_id(tree.encode_svg_id(logical)), logical)

    def test_encode_known_values(self) -> None:
        self.assertEqual(tree.encode_svg_id("a_b"), "a_x5F_b")
        self.assertEqual(tree.encode_svg_id(""), "")

    def test_normalize_strips_illustrator_suffix(self) -> None:
        self.assertEqual(tree._normalize_logical("main_x5F_btn_0000016089123456789012"), "main_btn")


class LookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ET.fromstring(_SVG)

    def test_find_by_logical_id_matches_suffixed_ids(self) -> None:
        el = tree._find_by_logical_id(self.root, "main_btn")
        self.assertIsNotNone(el)
        self.assertEqual(el.tag.rsplit("}", 1)[-1], "rect")
        self.assertIsNone(tree._find_by_logical_id(self.root, "missing"))

    def test_remove_by_logical_id(self) -> None:
        tree._remove_by_logical_id(self.root, "main_btn")
        tree._invalidate_logical_index(self.root)
        self.assertIsNone(tree._find_by_logical_id(self.root, "main_btn"))

    def test_set_visible_and_prune(self) -> None:
        el = tree._find_by_logical_id(self.root, "other")
        tree._set_visible(el, False)
        self.assertEqual(el.get("display"), "none")
        tree._set_visible(el, True)
        self.assertIsNone(el.get("display"))
        tree._set_visible(el, False)
        tree._prune_display_none(self.root)
        tree._invalidate_logical_index(self.root)
        self.assertIsNone(tree._find_by_logical_id(self.root, "other"))


class PaintTests(unittest.TestCase):
    def test_norm_hex(self) -> None:
        self.assertEqual(tree._norm_hex("#FFF"), "#ffffff")
        self.assertEqual(tree._norm_hex("white"), "#ffffff")
        self.assertEqual(tree._norm_hex("url(#g)"), None)
        self.assertEqual(tree._norm_hex(None), None)

    def test_set_paint_rewrites_style_and_attrs(self) -> None:
        node = ET.Element("rect", {"style": "fill:#000000;opacity:1"})
        tree._set_paint(node, fill="#ff0000", stroke="#00ff00")
        self.assertEqual(node.get("fill"), "#ff0000")
        self.assertEqual(node.get("stroke"), "#00ff00")
        self.assertIn("fill:#ff0000", node.get("style"))
        self.assertEqual(tree._iter_style_fill_stroke(node), ("#ff0000", "#00ff00"))

    def test_set_text_content_prefers_tspan(self) -> None:
        root = ET.fromstring(_SVG)
        tree._set_text_content(tree._find_by_logical_id(root, "other"), "new")
        self.assertEqual("".join(t.text or "" for t in root.iter() if t.tag.endswith("tspan")), "new")


class CompatTests(unittest.TestCase):
    def test_main_settings_still_exports_moved_names(self) -> None:
        for name in (
            "decode_svg_id", "encode_svg_id", "_normalize_logical", "_find_by_logical_id",
            "_set_paint", "_iter_style_fill_stroke", "_set_visible", "_prune_display_none",
        ):
            self.assertIs(getattr(main_settings, name), getattr(tree, name), name)


if __name__ == "__main__":
    unittest.main()
