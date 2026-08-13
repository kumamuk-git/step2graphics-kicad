from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt


Axis = Literal["+X", "-X", "+Y", "-Y", "+Z", "-Z"]

# (view direction, x-direction on drawing plane, y-direction on drawing plane)
_AXIS_FRAME = {
    "+Z": ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    "-Z": ((0, 0, -1), (-1, 0, 0), (0, 1, 0)),
    "+X": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "-X": ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
    "+Y": ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
    "-Y": ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
}


def load_step(path: Path) -> TopoDS_Shape:
    reader = STEPControl_Reader()
    status = reader.ReadFile(str(path))
    if status != IFSelect_RetDone:
        raise ValueError(f"STEPファイルを読み込めません: {path.name}")
    if reader.TransferRoots() == 0:
        raise ValueError(f"STEPファイルに読み込めるモデルがありません: {path.name}")
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError(f"STEPファイルから形状を取得できません: {path.name}")
    return shape


def _curve_points(edge, deflection_mm: float) -> list[tuple[float, float]]:
    curve = BRepAdaptor_Curve(edge)
    try:
        distribution = GCPnts_QuasiUniformDeflection(curve, deflection_mm)
        if distribution.IsDone() and distribution.NbPoints() >= 2:
            points = []
            for index in range(1, distribution.NbPoints() + 1):
                point = curve.Value(distribution.Parameter(index))
                points.append((point.X(), point.Y()))
            return points
    except Exception:
        pass

    try:
        first = curve.Value(curve.FirstParameter())
        last = curve.Value(curve.LastParameter())
        return [(first.X(), first.Y()), (last.X(), last.Y())]
    except Exception:
        return []


def _edges_to_polylines(compound, deflection_mm: float) -> list[list[tuple[float, float]]]:
    polylines: list[list[tuple[float, float]]] = []
    if compound is None or compound.IsNull():
        return polylines

    explorer = TopExp_Explorer(compound, TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge_s(explorer.Current())
        polyline = _curve_points(edge, deflection_mm)
        if len(polyline) >= 2:
            polylines.append(polyline)
        explorer.Next()
    return polylines


def project_shape(
    shape: TopoDS_Shape,
    axis: Axis,
    curve_tolerance_mm: float = 0.02,
) -> dict:
    if axis not in _AXIS_FRAME:
        raise ValueError(f"投影方向が不正です: {axis}")
    if not math.isfinite(curve_tolerance_mm) or curve_tolerance_mm <= 0:
        raise ValueError("曲線許容差は0より大きい値にしてください。")

    gaze, ux, _vy = _AXIS_FRAME[axis]
    projector = HLRAlgo_Projector(
        gp_Ax2(
            gp_Pnt(0.0, 0.0, 0.0),
            gp_Dir(*gaze),
            gp_Dir(*ux),
        )
    )

    hlr = HLRBRep_Algo()
    hlr.Add(shape)
    hlr.Projector(projector)
    hlr.Update()
    hlr.Hide()

    result = HLRBRep_HLRToShape(hlr)
    visible = _edges_to_polylines(result.VCompound(), curve_tolerance_mm)
    visible += _edges_to_polylines(result.OutLineVCompound(), curve_tolerance_mm)
    hidden = _edges_to_polylines(result.HCompound(), curve_tolerance_mm)

    points = [point for polyline in visible + hidden for point in polyline]
    if not points:
        raise ValueError("この方向から投影できる輪郭がありません。")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {
        "visible": visible,
        "hidden": hidden,
        "bounds2d": {"min": [min(xs), min(ys)], "max": [max(xs), max(ys)]},
    }


def project_step(
    path: Path,
    axis: Axis,
    curve_tolerance_mm: float = 0.02,
) -> dict:
    return project_shape(load_step(path), axis, curve_tolerance_mm)
