from __future__ import annotations

import sys
import unittest
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugin"
sys.path.insert(0, str(PLUGIN_DIR))

from projection_geometry import (
    ProjectionDataError,
    Segment2D,
    merge_collinear_segments,
    projection_to_segments,
)


class ProjectionGeometryTests(unittest.TestCase):
    def setUp(self):
        self.projection = {
            "visible": [
                [[0, 0], [10, 0], [10, 20]],
                [[10, 0], [0, 0]],
                [[4, 4], [4, 4]],
            ],
            "hidden": [[[0, 20], [10, 20]]],
            "bounds2d": {"min": [0, 0], "max": [10, 20]},
        }

    def test_centers_and_flips_projection_for_kicad(self):
        segments = projection_to_segments(self.projection, center_mm=(100, 200))
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].start, (95.0, 210.0))
        self.assertEqual(segments[0].end, (105.0, 210.0))
        self.assertEqual(segments[1].end, (105.0, 190.0))

    def test_hidden_lines_are_optional(self):
        visible = projection_to_segments(self.projection, center_mm=(0, 0))
        all_lines = projection_to_segments(
            self.projection,
            center_mm=(0, 0),
            include_hidden=True,
        )
        self.assertEqual(len(visible), 2)
        self.assertEqual(len(all_lines), 3)
        self.assertTrue(all_lines[-1].hidden)

    def test_can_keep_mathematical_y_direction(self):
        segments = projection_to_segments(
            self.projection,
            center_mm=(0, 0),
            flip_y=False,
        )
        self.assertEqual(segments[0].start, (-5.0, -10.0))

    def test_rejects_invalid_bounds(self):
        projection = dict(self.projection)
        projection["bounds2d"] = {"min": [10, 0], "max": [0, 20]}
        with self.assertRaises(ProjectionDataError):
            projection_to_segments(projection, center_mm=(0, 0))

    def test_enforces_segment_limit(self):
        with self.assertRaises(ProjectionDataError):
            projection_to_segments(self.projection, center_mm=(0, 0), max_segments=1)

    def test_merges_touching_collinear_segments(self):
        segments = [
            Segment2D((0.0, 0.0), (2.0, 0.0)),
            Segment2D((2.0, 0.0), (5.0, 0.0)),
            Segment2D((5.0, 0.0), (8.0, 0.0)),
        ]
        merged = merge_collinear_segments(segments)
        self.assertEqual(merged, [Segment2D((0.0, 0.0), (8.0, 0.0))])

    def test_does_not_merge_corners(self):
        segments = [
            Segment2D((0.0, 0.0), (2.0, 0.0)),
            Segment2D((2.0, 0.0), (2.0, 1.0)),
        ]
        self.assertEqual(len(merge_collinear_segments(segments)), 2)

    def test_merges_straight_line_through_t_junction(self):
        segments = [
            Segment2D((0.0, 0.0), (2.0, 0.0)),
            Segment2D((2.0, 0.0), (4.0, 0.0)),
            Segment2D((2.0, 0.0), (2.0, 1.0)),
        ]
        merged = merge_collinear_segments(segments)
        self.assertEqual(len(merged), 2)
        self.assertIn(Segment2D((0.0, 0.0), (4.0, 0.0)), merged)

    def test_merges_endpoints_within_tolerance(self):
        segments = [
            Segment2D((0.0, 0.0), (2.0, 0.0)),
            Segment2D((2.0005, 0.0), (4.0, 0.0)),
        ]
        merged = merge_collinear_segments(segments, endpoint_tolerance_mm=0.001)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].start, (0.0, 0.0))
        self.assertEqual(merged[0].end, (4.0, 0.0))

    def test_keeps_visible_and_hidden_segments_separate(self):
        segments = [
            Segment2D((0.0, 0.0), (2.0, 0.0), hidden=False),
            Segment2D((2.0, 0.0), (4.0, 0.0), hidden=True),
        ]
        self.assertEqual(len(merge_collinear_segments(segments)), 2)


if __name__ == "__main__":
    unittest.main()
