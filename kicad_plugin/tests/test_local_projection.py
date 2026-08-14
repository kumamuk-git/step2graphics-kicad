from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1] / "plugin"
sys.path.insert(0, str(PLUGIN_DIR))

try:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from local_projection import project_shape, project_step
except ModuleNotFoundError:
    project_shape = None
    project_step = None


@unittest.skipIf(project_shape is None, "cadquery-ocp-novtk is not installed")
class LocalProjectionTests(unittest.TestCase):
    def test_projects_box_to_expected_bounds(self):
        shape = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
        projection = project_shape(shape, "+Z")

        self.assertAlmostEqual(projection["bounds2d"]["min"][0], 0.0)
        self.assertAlmostEqual(projection["bounds2d"]["min"][1], 0.0)
        self.assertAlmostEqual(projection["bounds2d"]["max"][0], 10.0)
        self.assertAlmostEqual(projection["bounds2d"]["max"][1], 20.0)
        self.assertGreater(len(projection["visible"]), 0)

    def test_all_six_axes_have_expected_dimensions(self):
        shape = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
        expected = {
            "+Z": (10.0, 20.0),
            "-Z": (10.0, 20.0),
            "+X": (20.0, 30.0),
            "-X": (20.0, 30.0),
            "+Y": (10.0, 30.0),
            "-Y": (10.0, 30.0),
        }
        for axis, size in expected.items():
            with self.subTest(axis=axis):
                bounds = project_shape(shape, axis)["bounds2d"]
                actual = (
                    bounds["max"][0] - bounds["min"][0],
                    bounds["max"][1] - bounds["min"][1],
                )
                self.assertAlmostEqual(actual[0], size[0])
                self.assertAlmostEqual(actual[1], size[1])

    def test_discretizes_curved_edges_by_tolerance(self):
        shape = BRepPrimAPI_MakeCylinder(10.0, 20.0).Shape()
        projection = project_shape(shape, "+Z", curve_tolerance_mm=0.05)
        self.assertTrue(any(len(polyline) > 8 for polyline in projection["visible"]))

    def test_extracts_closed_planar_outline(self):
        shape = BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
        outline = project_shape(shape, "+Z")["outline"]

        self.assertEqual(len(outline), 1)
        self.assertEqual(outline[0][0], outline[0][-1])

    def test_planar_outline_preserves_inner_cutouts(self):
        board = BRepPrimAPI_MakeBox(20.0, 10.0, 1.0).Shape()
        hole_axis = gp_Ax2(gp_Pnt(5.0, 5.0, 0.0), gp_Dir(0.0, 0.0, 1.0))
        hole = BRepPrimAPI_MakeCylinder(hole_axis, 1.0, 1.0).Shape()
        shape = BRepAlgoAPI_Cut(board, hole).Shape()
        outline = project_shape(shape, "+Z", curve_tolerance_mm=0.05)["outline"]

        self.assertEqual(len(outline), 2)
        self.assertTrue(all(polyline[0] == polyline[-1] for polyline in outline))

    def test_reads_step_file_without_external_service(self):
        shape = BRepPrimAPI_MakeBox(4.0, 5.0, 6.0).Shape()
        with tempfile.TemporaryDirectory() as temp_dir:
            step_path = Path(temp_dir) / "box.step"
            writer = STEPControl_Writer()
            self.assertEqual(writer.Transfer(shape, STEPControl_AsIs), IFSelect_RetDone)
            self.assertEqual(writer.Write(str(step_path)), IFSelect_RetDone)
            projection = project_step(step_path, "+Z")

        self.assertAlmostEqual(projection["bounds2d"]["max"][0], 4.0)
        self.assertAlmostEqual(projection["bounds2d"]["max"][1], 5.0)


if __name__ == "__main__":
    unittest.main()
