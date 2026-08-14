from __future__ import annotations

import math
from pathlib import Path
from typing import Literal

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepGProp import BRepGProp
from OCP.BRepTools import BRepTools_WireExplorer
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.GeomAbs import GeomAbs_Plane
from OCP.GProp import GProp_GProps
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_WIRE
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


def _point3d(point) -> tuple[float, float, float]:
    return (point.X(), point.Y(), point.Z())


def _curve_points_3d(edge, deflection_mm: float) -> list[tuple[float, float, float]]:
    curve = BRepAdaptor_Curve(edge)
    try:
        distribution = GCPnts_QuasiUniformDeflection(curve, deflection_mm)
        if distribution.IsDone() and distribution.NbPoints() >= 2:
            points = []
            for index in range(1, distribution.NbPoints() + 1):
                point = curve.Value(distribution.Parameter(index))
                points.append(_point3d(point))
            return points
    except Exception:
        pass

    try:
        first = curve.Value(curve.FirstParameter())
        last = curve.Value(curve.LastParameter())
        return [_point3d(first), _point3d(last)]
    except Exception:
        return []


def _curve_points(edge, deflection_mm: float) -> list[tuple[float, float]]:
    return [(point[0], point[1]) for point in _curve_points_3d(edge, deflection_mm)]


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


def _dot3(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return sum(a * b for a, b in zip(first, second))


def _dominant_planar_face_outlines(
    shape: TopoDS_Shape,
    axis: Axis,
    deflection_mm: float,
) -> list[list[tuple[float, float]]]:
    """Return ordered, closed wires from the largest face parallel to the view plane."""
    gaze, ux, vy = _AXIS_FRAME[axis]
    candidates: list[tuple[float, object]] = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_Plane:
            direction = surface.Plane().Axis().Direction()
            normal = (direction.X(), direction.Y(), direction.Z())
            if abs(_dot3(normal, gaze)) >= 1.0 - 1e-8:
                properties = GProp_GProps()
                BRepGProp.SurfaceProperties_s(face, properties)
                if math.isfinite(properties.Mass()) and properties.Mass() > 0:
                    candidates.append((properties.Mass(), face))
        explorer.Next()

    if not candidates:
        return []

    _area, face = max(candidates, key=lambda candidate: candidate[0])
    polylines: list[list[tuple[float, float]]] = []
    wires = TopExp_Explorer(face, TopAbs_WIRE)
    while wires.More():
        wire = TopoDS.Wire_s(wires.Current())
        if not wire.Closed():
            return []
        wire_explorer = BRepTools_WireExplorer(wire, face)
        ordered_edges: list[tuple[object, tuple[float, float, float]]] = []
        while wire_explorer.More():
            edge = TopoDS.Edge_s(wire_explorer.Current())
            vertex = TopoDS.Vertex_s(wire_explorer.CurrentVertex())
            ordered_edges.append((edge, _point3d(BRep_Tool.Pnt_s(vertex))))
            wire_explorer.Next()

        polyline: list[tuple[float, float]] = []
        for index, (edge, start) in enumerate(ordered_edges):
            end = ordered_edges[(index + 1) % len(ordered_edges)][1]
            points = _curve_points_3d(edge, deflection_mm)
            if len(points) < 2:
                return []
            if math.dist(points[-1], start) < math.dist(points[0], start):
                points.reverse()
            points[0] = start
            points[-1] = end
            projected = [(_dot3(point, ux), _dot3(point, vy)) for point in points]
            if polyline:
                polyline.extend(projected[1:])
            else:
                polyline.extend(projected)

        if len(polyline) >= 3:
            polyline[-1] = polyline[0]
            polylines.append(polyline)
        wires.Next()
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
    outline = _dominant_planar_face_outlines(shape, axis, curve_tolerance_mm)

    points = [point for polyline in visible + hidden for point in polyline]
    if not points:
        raise ValueError("この方向から投影できる輪郭がありません。")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    if outline:
        outline_points = [point for polyline in outline for point in polyline]
        outline_xs = [point[0] for point in outline_points]
        outline_ys = [point[1] for point in outline_points]
        visible_extent = (max(xs) - min(xs), max(ys) - min(ys))
        outline_extent = (
            max(outline_xs) - min(outline_xs),
            max(outline_ys) - min(outline_ys),
        )
        if any(
            visible_size > 1e-9 and outline_size < visible_size * 0.9
            for visible_size, outline_size in zip(visible_extent, outline_extent)
        ):
            outline = []
    return {
        "visible": visible,
        "hidden": hidden,
        "outline": outline,
        "bounds2d": {"min": [min(xs), min(ys)], "max": [max(xs), max(ys)]},
    }


def project_step(
    path: Path,
    axis: Axis,
    curve_tolerance_mm: float = 0.02,
) -> dict:
    return project_shape(load_step(path), axis, curve_tolerance_mm)
