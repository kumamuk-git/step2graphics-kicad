from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


class ProjectionDataError(ValueError):
    pass


@dataclass(frozen=True)
class Segment2D:
    start: tuple[float, float]
    end: tuple[float, float]
    hidden: bool = False


def merge_collinear_segments(
    segments: Iterable[Segment2D],
    *,
    endpoint_tolerance_mm: float = 0.001,
    angle_tolerance_degrees: float = 0.05,
) -> list[Segment2D]:
    """Join unbranched chains of touching, collinear segments.

    Corners and visibility boundaries are preserved.  A straight line may be
    joined through a T junction because that does not change the drawn shape.
    """
    if not math.isfinite(endpoint_tolerance_mm) or endpoint_tolerance_mm <= 0:
        raise ValueError("endpoint_tolerance_mm must be positive")
    if not math.isfinite(angle_tolerance_degrees) or not 0 <= angle_tolerance_degrees < 90:
        raise ValueError("angle_tolerance_degrees must be between 0 and 90")

    source = list(segments)
    if len(source) < 2:
        return source

    nodes: list[tuple[float, float]] = []
    cells: dict[tuple[int, int], list[int]] = {}

    def node_for(point: tuple[float, float]) -> int:
        cell = (
            math.floor(point[0] / endpoint_tolerance_mm),
            math.floor(point[1] / endpoint_tolerance_mm),
        )
        best: tuple[float, int] | None = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for node_id in cells.get((cell[0] + dx, cell[1] + dy), ()):
                    distance = math.dist(point, nodes[node_id])
                    if distance <= endpoint_tolerance_mm and (
                        best is None or distance < best[0]
                    ):
                        best = (distance, node_id)
        if best is not None:
            return best[1]
        node_id = len(nodes)
        nodes.append(point)
        cells.setdefault(cell, []).append(node_id)
        return node_id

    edges: list[tuple[int, int, bool]] = []
    edge_keys: set[tuple[int, int, bool]] = set()
    for segment in source:
        a = node_for(segment.start)
        b = node_for(segment.end)
        if a == b:
            continue
        key = (min(a, b), max(a, b), segment.hidden)
        if key in edge_keys:
            continue
        edge_keys.add(key)
        edges.append((a, b, segment.hidden))

    incident: list[list[int]] = [[] for _ in nodes]
    for edge_id, (a, b, _hidden) in enumerate(edges):
        incident[a].append(edge_id)
        incident[b].append(edge_id)

    angle_limit = math.cos(math.radians(angle_tolerance_degrees))

    def other_node(edge_id: int, node_id: int) -> int:
        a, b, _hidden = edges[edge_id]
        return b if a == node_id else a

    def continuation(node_id: int, edge_id: int) -> int | None:
        connected = incident[node_id]
        first = nodes[other_node(edge_id, node_id)]
        center = nodes[node_id]
        first_vector = (first[0] - center[0], first[1] - center[1])
        first_length = math.hypot(*first_vector)
        if first_length <= 0:
            return None

        candidates: list[int] = []
        for other_edge in connected:
            if other_edge == edge_id or edges[other_edge][2] != edges[edge_id][2]:
                continue
            second = nodes[other_node(other_edge, node_id)]
            second_vector = (second[0] - center[0], second[1] - center[1])
            second_length = math.hypot(*second_vector)
            if second_length <= 0:
                continue
            cosine = (
                first_vector[0] * second_vector[0]
                + first_vector[1] * second_vector[1]
            ) / (first_length * second_length)
            if cosine <= -angle_limit:
                candidates.append(other_edge)
        return candidates[0] if len(candidates) == 1 else None

    visited: set[int] = set()
    merged: list[Segment2D] = []

    def walk(start_node: int, first_edge: int) -> None:
        current_node = start_node
        edge_id = first_edge
        hidden = edges[first_edge][2]
        while True:
            visited.add(edge_id)
            next_node = other_node(edge_id, current_node)
            next_edge = continuation(next_node, edge_id)
            if next_edge is None or next_edge in visited:
                merged.append(
                    Segment2D(start=nodes[start_node], end=nodes[next_node], hidden=hidden)
                )
                return
            current_node = next_node
            edge_id = next_edge

    # Start at chain ends first, so an interior edge cannot split a chain.
    for edge_id, (a, b, _hidden) in enumerate(edges):
        if edge_id in visited:
            continue
        if continuation(a, edge_id) is None:
            walk(a, edge_id)
        elif continuation(b, edge_id) is None:
            walk(b, edge_id)

    # Any leftovers are closed or degenerate chains; keep them deterministic.
    for edge_id, (a, _b, _hidden) in enumerate(edges):
        if edge_id not in visited:
            walk(a, edge_id)

    return merged


def _point(value: Any) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ProjectionDataError("投影座標の形式が不正です。")
    try:
        point = (float(value[0]), float(value[1]))
    except (TypeError, ValueError) as exc:
        raise ProjectionDataError("投影座標に数値以外が含まれています。") from exc
    if not all(math.isfinite(component) for component in point):
        raise ProjectionDataError("投影座標に有限値以外が含まれています。")
    return point


def _polylines(value: Any, label: str) -> Iterable[list[tuple[float, float]]]:
    if not isinstance(value, list):
        raise ProjectionDataError(f"{label} の形式が不正です。")
    for polyline in value:
        if not isinstance(polyline, list):
            raise ProjectionDataError(f"{label} のポリライン形式が不正です。")
        yield [_point(point) for point in polyline]


def _bounds_center(projection: dict[str, Any]) -> tuple[float, float]:
    bounds = projection.get("bounds2d")
    if not isinstance(bounds, dict):
        raise ProjectionDataError("投影範囲 bounds2d がありません。")
    minimum = _point(bounds.get("min"))
    maximum = _point(bounds.get("max"))
    if maximum[0] < minimum[0] or maximum[1] < minimum[1]:
        raise ProjectionDataError("投影範囲 bounds2d の大小関係が不正です。")
    return ((minimum[0] + maximum[0]) * 0.5, (minimum[1] + maximum[1]) * 0.5)


def projection_to_segments(
    projection: dict[str, Any],
    *,
    center_mm: tuple[float, float],
    include_hidden: bool = False,
    flip_y: bool = True,
    merge_collinear: bool = True,
    merge_endpoint_tolerance_mm: float = 0.001,
    merge_angle_tolerance_degrees: float = 0.05,
    max_segments: int = 100_000,
) -> list[Segment2D]:
    """Convert projected polylines into centered, de-duplicated KiCad-space segments."""
    if max_segments < 1:
        raise ValueError("max_segments must be positive")

    source_center = _bounds_center(projection)
    target_center = _point(center_mm)
    segment_keys: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    segments: list[Segment2D] = []

    groups = [(projection.get("visible"), False, "visible")]
    if include_hidden:
        groups.append((projection.get("hidden"), True, "hidden"))

    def transform(point: tuple[float, float]) -> tuple[float, float]:
        x = target_center[0] + point[0] - source_center[0]
        y_delta = point[1] - source_center[1]
        y = target_center[1] - y_delta if flip_y else target_center[1] + y_delta
        return (x, y)

    for raw_polylines, hidden, label in groups:
        for polyline in _polylines(raw_polylines, label):
            for raw_start, raw_end in zip(polyline, polyline[1:]):
                start = transform(raw_start)
                end = transform(raw_end)
                if math.dist(start, end) < 1e-9:
                    continue

                # HLR compounds can expose the same edge twice or in reverse order.
                qa = (round(start[0] * 1_000_000), round(start[1] * 1_000_000))
                qb = (round(end[0] * 1_000_000), round(end[1] * 1_000_000))
                key = (qa, qb) if qa <= qb else (qb, qa)
                if key in segment_keys:
                    continue
                segment_keys.add(key)
                segments.append(Segment2D(start=start, end=end, hidden=hidden))
                if len(segments) > max_segments:
                    raise ProjectionDataError(
                        f"投影結果が {max_segments:,} セグメントを超えました。"
                    )

    if not segments:
        raise ProjectionDataError("投影結果に読み込める線分がありません。")
    if merge_collinear:
        return merge_collinear_segments(
            segments,
            endpoint_tolerance_mm=merge_endpoint_tolerance_mm,
            angle_tolerance_degrees=merge_angle_tolerance_degrees,
        )
    return segments
