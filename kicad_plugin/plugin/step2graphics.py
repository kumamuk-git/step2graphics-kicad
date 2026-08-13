from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar

import pcbnew
import wx

try:
    from .projection_geometry import Segment2D, projection_to_segments
except (ImportError, ModuleNotFoundError):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from projection_geometry import Segment2D, projection_to_segments


T = TypeVar("T")
PLUGIN_ID = "jp.tasko.step2graphics"
OCP_REQUIREMENT = "cadquery-ocp-novtk==7.9.3.1.1"
AXES = ["+Z", "-Z", "+X", "-X", "+Y", "-Y"]
AXIS_PLANES = {
    "+Z": "XY平面（上面）",
    "-Z": "XY平面（下面）",
    "+X": "YZ平面（右側面）",
    "-X": "YZ平面（左側面）",
    "+Y": "XZ平面（背面）",
    "-Y": "XZ平面（正面）",
}
LAYERS = ["Dwgs.User", "Edge.Cuts", "Cmts.User", "F.Fab", "B.Fab", "F.SilkS", "B.SilkS"]
LAYER_IDS = {
    "Dwgs.User": pcbnew.Dwgs_User,
    "Edge.Cuts": pcbnew.Edge_Cuts,
    "Cmts.User": pcbnew.Cmts_User,
    "F.Fab": pcbnew.F_Fab,
    "B.Fab": pcbnew.B_Fab,
    "F.SilkS": pcbnew.F_SilkS,
    "B.SilkS": pcbnew.B_SilkS,
}


@dataclass(frozen=True)
class ImportOptions:
    step_path: Path
    axis: str
    layer: str
    line_width_mm: float
    curve_tolerance_mm: float
    center_mm: tuple[float, float]
    include_hidden: bool
    flip_y: bool
    merge_collinear: bool
    merge_endpoint_tolerance_mm: float
    merge_angle_tolerance_degrees: float
    group_created: bool
    select_created: bool


class StepFileDropTarget(wx.FileDropTarget):
    def __init__(self, callback: Callable[[list[str]], bool]):
        super().__init__()
        self._callback = callback

    def OnDropFiles(self, _x, _y, filenames):
        return self._callback(list(filenames))


class ProjectionPreview(wx.Panel):
    def __init__(self, parent):
        super().__init__(parent, size=(-1, 290), style=wx.BORDER_SIMPLE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._segments: list[Segment2D] = []
        self._message = "STEPファイルを選択するか、ここへドラッグ＆ドロップしてください。"
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.Refresh(), event.Skip()))

    def show_message(self, message: str) -> None:
        self._segments = []
        self._message = message
        self.Refresh()

    def show_segments(self, segments: list[Segment2D]) -> None:
        self._segments = segments
        self._message = ""
        self.Refresh()

    def _on_paint(self, _event) -> None:
        dc = wx.AutoBufferedPaintDC(self)
        background = self.GetBackgroundColour()
        dc.SetBackground(wx.Brush(background))
        dc.Clear()

        width, height = self.GetClientSize()
        if not self._segments:
            dc.SetTextForeground(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
            dc.DrawLabel(
                self._message,
                wx.Rect(16, 16, max(1, width - 32), max(1, height - 32)),
                wx.ALIGN_CENTER | wx.ALIGN_CENTER_VERTICAL,
            )
            return

        points = [point for segment in self._segments for point in (segment.start, segment.end)]
        minimum_x = min(point[0] for point in points)
        maximum_x = max(point[0] for point in points)
        minimum_y = min(point[1] for point in points)
        maximum_y = max(point[1] for point in points)
        extent_x = max(maximum_x - minimum_x, 1e-9)
        extent_y = max(maximum_y - minimum_y, 1e-9)
        padding = 22
        scale = min(
            max(1, width - padding * 2) / extent_x,
            max(1, height - padding * 2) / extent_y,
        )
        offset_x = (width - extent_x * scale) * 0.5
        offset_y = (height - extent_y * scale) * 0.5

        def screen(point: tuple[float, float]) -> tuple[int, int]:
            return (
                round(offset_x + (point[0] - minimum_x) * scale),
                round(height - offset_y - (point[1] - minimum_y) * scale),
            )

        visible_pen = wx.Pen(wx.Colour(35, 135, 215), 2)
        hidden_pen = wx.Pen(wx.Colour(145, 145, 145), 1, wx.PENSTYLE_SHORT_DASH)
        for hidden in (True, False):
            dc.SetPen(hidden_pen if hidden else visible_pen)
            for segment in self._segments:
                if segment.hidden == hidden:
                    dc.DrawLine(*screen(segment.start), *screen(segment.end))


class ImportDialog(wx.Dialog):
    def __init__(self):
        super().__init__(None, title="STEP投影をグラフィックとして読み込む")
        self._preview_projection: dict | None = None
        self._preview_key: tuple[str, int, str, float] | None = None
        self._drop_targets: list[StepFileDropTarget] = []

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(
            wx.StaticText(
                self,
                label=(
                    "STEPモデルを指定方向から正投影し、PCBの線グラフィックとして追加します。\n"
                    "STEPファイルはファイル欄またはプレビューへドラッグ＆ドロップできます。"
                ),
            ),
            0,
            wx.ALL | wx.EXPAND,
            12,
        )

        grid = wx.FlexGridSizer(cols=2, hgap=10, vgap=9)
        grid.AddGrowableCol(1, 1)
        self.file_picker = wx.FilePickerCtrl(
            self,
            message="STEPファイルを選択",
            wildcard="STEP files (*.step;*.stp)|*.step;*.stp|All files (*.*)|*.*",
            style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL,
        )
        self.axis = wx.Choice(self, choices=AXES)
        self.axis.SetSelection(0)
        self.layer = wx.Choice(self, choices=LAYERS)
        self.layer.SetSelection(0)
        self.line_width = wx.SpinCtrlDouble(self, min=0.01, max=10.0, initial=0.10, inc=0.01)
        self.line_width.SetDigits(3)
        self.curve_tolerance = wx.SpinCtrlDouble(
            self, min=0.001, max=10.0, initial=0.02, inc=0.01
        )
        self.curve_tolerance.SetDigits(3)
        self.center_x = wx.SpinCtrlDouble(
            self, min=-100000.0, max=100000.0, initial=100.0, inc=1.0
        )
        self.center_y = wx.SpinCtrlDouble(
            self, min=-100000.0, max=100000.0, initial=100.0, inc=1.0
        )
        self.center_x.SetDigits(3)
        self.center_y.SetDigits(3)

        center_row = wx.BoxSizer(wx.HORIZONTAL)
        center_row.Add(wx.StaticText(self, label="X"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        center_row.Add(self.center_x, 1, wx.RIGHT, 12)
        center_row.Add(wx.StaticText(self, label="Y"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        center_row.Add(self.center_y, 1)

        for label, control in [
            ("STEPファイル", self.file_picker),
            ("投影方向", self.axis),
            ("追加先レイヤー", self.layer),
            ("線幅 (mm)", self.line_width),
            ("曲線許容差 (mm)", self.curve_tolerance),
        ]:
            grid.Add(wx.StaticText(self, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(control, 1, wx.EXPAND)
        grid.Add(wx.StaticText(self, label="配置中心 (mm)"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(center_row, 1, wx.EXPAND)
        root.Add(grid, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        options_row = wx.BoxSizer(wx.HORIZONTAL)
        self.include_hidden = wx.CheckBox(self, label="隠線も読み込む")
        self.flip_y = wx.CheckBox(self, label="Y軸を反転")
        self.flip_y.SetValue(True)
        self.group_created = wx.CheckBox(self, label="生成アイテムをグループ化")
        self.group_created.SetValue(True)
        self.select_created = wx.CheckBox(self, label="追加後に選択")
        self.select_created.SetValue(True)
        for checkbox in (
            self.include_hidden,
            self.flip_y,
            self.group_created,
            self.select_created,
        ):
            options_row.Add(checkbox, 0, wx.RIGHT, 16)
        root.Add(options_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        merge_box = wx.StaticBoxSizer(wx.HORIZONTAL, self, "直線線分の統合")
        merge_parent = merge_box.GetStaticBox()
        self.merge_collinear = wx.CheckBox(
            merge_parent, label="同一直線上の接続線分を統合"
        )
        self.merge_collinear.SetValue(True)
        self.merge_endpoint_tolerance = wx.SpinCtrlDouble(
            merge_parent, min=0.000001, max=1.0, initial=0.001, inc=0.001
        )
        self.merge_endpoint_tolerance.SetDigits(6)
        self.merge_angle_tolerance = wx.SpinCtrlDouble(
            merge_parent, min=0.0, max=10.0, initial=0.05, inc=0.05
        )
        self.merge_angle_tolerance.SetDigits(3)
        merge_box.Add(self.merge_collinear, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 16)
        merge_box.Add(
            wx.StaticText(merge_parent, label="端点許容差 (mm)"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        merge_box.Add(self.merge_endpoint_tolerance, 0, wx.RIGHT, 12)
        merge_box.Add(
            wx.StaticText(merge_parent, label="角度許容差 (°)"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        merge_box.Add(self.merge_angle_tolerance, 0)
        root.Add(merge_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        preview_header = wx.BoxSizer(wx.HORIZONTAL)
        self.plane_label = wx.StaticText(self, label=self._plane_text())
        self.preview_status = wx.StaticText(self, label="未読み込み")
        preview_button = wx.Button(self, label="プレビュー更新")
        preview_header.Add(self.plane_label, 0, wx.ALIGN_CENTER_VERTICAL)
        preview_header.AddStretchSpacer(1)
        preview_header.Add(self.preview_status, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        preview_header.Add(preview_button, 0)
        root.Add(preview_header, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        self.preview = ProjectionPreview(self)
        root.Add(self.preview, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)

        root.Add(self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.EXPAND, 12)
        self.SetSizer(root)
        self.SetSize((760, 720))
        self.SetMinSize((700, 650))
        self.FindWindowById(wx.ID_OK).SetLabel("読み込む")

        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        preview_button.Bind(wx.EVT_BUTTON, self._on_preview)
        self.file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, self._on_file_changed)
        self.axis.Bind(wx.EVT_CHOICE, self._on_axis_changed)
        for control in (self.include_hidden, self.flip_y, self.merge_collinear):
            control.Bind(wx.EVT_CHECKBOX, self._on_preview_option_changed)
        for control in (self.merge_endpoint_tolerance, self.merge_angle_tolerance):
            control.Bind(wx.EVT_SPINCTRLDOUBLE, self._on_preview_option_changed)

        for target_window in (self, self.file_picker, self.preview):
            drop_target = StepFileDropTarget(self._on_files_dropped)
            target_window.SetDropTarget(drop_target)
            self._drop_targets.append(drop_target)

    def _plane_text(self) -> str:
        axis = self.axis.GetStringSelection() or "+Z"
        return f"投影面: {AXIS_PLANES[axis]} / 視線 {axis}"

    def _step_path(self) -> Path:
        path = Path(self.file_picker.GetPath())
        if not path.is_file():
            raise ValueError("存在するSTEPファイルを選択してください。")
        if path.suffix.lower() not in {".step", ".stp"}:
            raise ValueError("拡張子 .step または .stp のファイルを選択してください。")
        return path

    def _calculation_key(self) -> tuple[str, int, str, float]:
        path = self._step_path()
        return (
            str(path.resolve()),
            path.stat().st_mtime_ns,
            self.axis.GetStringSelection(),
            self.curve_tolerance.GetValue(),
        )

    def _on_files_dropped(self, filenames: list[str]) -> bool:
        for filename in filenames:
            path = Path(filename)
            if path.is_file() and path.suffix.lower() in {".step", ".stp"}:
                self.file_picker.SetPath(str(path))
                wx.CallAfter(self._refresh_preview)
                return True
        self.preview.show_message("STEP/STPファイルだけをドロップできます。")
        self.preview_status.SetLabel("非対応ファイル")
        return False

    def _on_file_changed(self, _event) -> None:
        self._refresh_preview()

    def _on_axis_changed(self, _event) -> None:
        self.plane_label.SetLabel(self._plane_text())
        if self.file_picker.GetPath():
            self._refresh_preview()

    def _on_preview_option_changed(self, _event) -> None:
        self._draw_cached_preview()

    def _on_preview(self, _event) -> None:
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self.plane_label.SetLabel(self._plane_text())
        try:
            key = self._calculation_key()
            path = self._step_path()
            if key != self._preview_key:
                self.preview_status.SetLabel("投影計算中…")
                self._preview_projection = _run_with_progress(
                    "STEPを読み込んで投影プレビューを計算しています…",
                    lambda: _calculate_projection_values(
                        path,
                        self.axis.GetStringSelection(),
                        self.curve_tolerance.GetValue(),
                    ),
                )
                self._preview_key = key
            self._draw_cached_preview()
        except Exception as exc:
            self._preview_projection = None
            self._preview_key = None
            self.preview_status.SetLabel("プレビュー失敗")
            self.preview.show_message(str(exc))

    def _draw_cached_preview(self) -> None:
        if self._preview_projection is None:
            return
        try:
            segments = projection_to_segments(
                self._preview_projection,
                center_mm=(0.0, 0.0),
                include_hidden=self.include_hidden.GetValue(),
                flip_y=self.flip_y.GetValue(),
                merge_collinear=self.merge_collinear.GetValue(),
                merge_endpoint_tolerance_mm=self.merge_endpoint_tolerance.GetValue(),
                merge_angle_tolerance_degrees=self.merge_angle_tolerance.GetValue(),
            )
            points = [point for segment in segments for point in (segment.start, segment.end)]
            width = max(point[0] for point in points) - min(point[0] for point in points)
            height = max(point[1] for point in points) - min(point[1] for point in points)
            self.preview.show_segments(segments)
            self.preview_status.SetLabel(f"{width:.2f} × {height:.2f} mm / {len(segments):,}線分")
        except Exception as exc:
            self.preview_status.SetLabel("プレビュー失敗")
            self.preview.show_message(str(exc))

    def _on_ok(self, _event) -> None:
        try:
            self.options()
        except ValueError as exc:
            wx.MessageBox(str(exc), "入力エラー", wx.OK | wx.ICON_ERROR, parent=self)
            return
        self.EndModal(wx.ID_OK)

    def options(self) -> ImportOptions:
        return ImportOptions(
            step_path=self._step_path(),
            axis=self.axis.GetStringSelection(),
            layer=self.layer.GetStringSelection(),
            line_width_mm=self.line_width.GetValue(),
            curve_tolerance_mm=self.curve_tolerance.GetValue(),
            center_mm=(self.center_x.GetValue(), self.center_y.GetValue()),
            include_hidden=self.include_hidden.GetValue(),
            flip_y=self.flip_y.GetValue(),
            merge_collinear=self.merge_collinear.GetValue(),
            merge_endpoint_tolerance_mm=self.merge_endpoint_tolerance.GetValue(),
            merge_angle_tolerance_degrees=self.merge_angle_tolerance.GetValue(),
            group_created=self.group_created.GetValue(),
            select_created=self.select_created.GetValue(),
        )

    def cached_projection(self) -> dict | None:
        try:
            if self._preview_key == self._calculation_key():
                return self._preview_projection
        except (OSError, ValueError):
            pass
        return None


def _run_with_progress(message: str, operation: Callable[[], T]) -> T:
    state: dict[str, object] = {}
    finished = threading.Event()

    def worker() -> None:
        try:
            state["result"] = operation()
        except BaseException as exc:
            state["error"] = exc
        finally:
            finished.set()

    progress = wx.ProgressDialog(
        "STEP投影を処理中",
        message,
        maximum=100,
        style=wx.PD_APP_MODAL | wx.PD_ELAPSED_TIME,
    )
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        while not finished.wait(0.08):
            progress.Pulse(message)
            wx.YieldIfNeeded()
    finally:
        progress.Destroy()

    if "error" in state:
        raise state["error"]  # type: ignore[misc]
    return state["result"]  # type: ignore[return-value]


def _base_python() -> Path:
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        config = Path(appdata) / "kicad" / "10.0" / "kicad_common.json"
        try:
            configured = json.loads(config.read_text(encoding="utf-8"))["api"]["interpreter_path"]
            configured_path = Path(configured)
            candidates.extend([configured_path.with_name("python.exe"), configured_path])
        except (OSError, KeyError, TypeError, ValueError):
            pass
    executable = Path(sys.executable)
    candidates.extend([executable.with_name("python.exe"), executable.with_name("pythonw.exe")])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("KiCadで使用するPythonインタープリターが見つかりません。")


def _runtime_python() -> Path:
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        raise RuntimeError("LOCALAPPDATAが設定されていません。")
    environment = Path(localappdata) / "KiCad" / "10.0" / "python-environments" / PLUGIN_ID
    python = environment / "Scripts" / "python.exe"
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    if not python.is_file():
        result = subprocess.run(
            [str(_base_python()), "-m", "venv", "--system-site-packages", str(environment)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=no_window,
        )
        if result.returncode != 0:
            raise RuntimeError("STEP解析環境を作成できません。\n" + (result.stderr or result.stdout))

    check = subprocess.run(
        [str(python), "-c", "import OCP"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=no_window,
    )
    if check.returncode != 0:
        install = subprocess.run(
            [str(python), "-m", "pip", "install", "--only-binary=:all:", OCP_REQUIREMENT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=no_window,
        )
        if install.returncode != 0:
            raise RuntimeError(
                "OpenCASCADEをインストールできません。\n" + (install.stderr or install.stdout)
            )
    return python


def _calculate_projection_values(step_path: Path, axis: str, tolerance_mm: float) -> dict:
    python = _runtime_python()
    worker = Path(__file__).with_name("projection_worker.py")
    fd, output_name = tempfile.mkstemp(prefix="step2graphics-", suffix=".json")
    os.close(fd)
    output = Path(output_name)
    try:
        result = subprocess.run(
            [str(python), str(worker), str(step_path), axis, str(tolerance_mm), str(output)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise RuntimeError("STEPの正投影に失敗しました。\n" + (result.stderr or result.stdout))
        return json.loads(output.read_text(encoding="utf-8"))
    finally:
        try:
            output.unlink()
        except OSError:
            pass


def _calculate_projection(options: ImportOptions) -> dict:
    return _calculate_projection_values(
        options.step_path,
        options.axis,
        options.curve_tolerance_mm,
    )


@dataclass(frozen=True)
class AddResult:
    segment_count: int
    group_name: str | None


def _add_segments(
    board,
    segments: list[Segment2D],
    *,
    source_name: str,
    layer_name: str,
    line_width_mm: float,
    group_created: bool,
    select_created: bool,
) -> AddResult:
    layer = LAYER_IDS.get(layer_name)
    if layer is None:
        raise ValueError(f"KiCadレイヤー名が不正です: {layer_name}")

    created = []
    group = None
    group_name = None
    try:
        for segment in segments:
            shape = pcbnew.PCB_SHAPE(board)
            shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
            shape.SetStart(
                pcbnew.VECTOR2I(pcbnew.FromMM(segment.start[0]), pcbnew.FromMM(segment.start[1]))
            )
            shape.SetEnd(
                pcbnew.VECTOR2I(pcbnew.FromMM(segment.end[0]), pcbnew.FromMM(segment.end[1]))
            )
            shape.SetLayer(layer)
            shape.SetWidth(pcbnew.FromMM(line_width_mm))
            board.Add(shape)
            created.append(shape)

        if group_created:
            group_name = f"STEP投影: {source_name}"
            group = pcbnew.PCB_GROUP(board)
            group.SetName(group_name)
            board.Add(group)
            for shape in created:
                group.AddItem(shape)
    except Exception:
        if group is not None:
            for shape in created:
                try:
                    group.RemoveItem(shape)
                except Exception:
                    pass
            try:
                board.Remove(group)
            except Exception:
                pass
        for shape in reversed(created):
            try:
                board.Remove(shape)
            except Exception:
                pass
        raise

    if select_created:
        if group is not None:
            group.SetSelected()
        else:
            for shape in created:
                shape.SetSelected()
    pcbnew.Refresh()
    return AddResult(segment_count=len(created), group_name=group_name)


def run() -> None:
    board = pcbnew.GetBoard()
    if board is None:
        wx.MessageBox("PCBを開いてから実行してください。", "STEP投影", wx.OK | wx.ICON_ERROR)
        return

    dialog = ImportDialog()
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return
        options = dialog.options()
        projection = dialog.cached_projection()
    finally:
        dialog.Destroy()

    try:
        if projection is None:
            projection = _run_with_progress(
                "STEPを読み込んで正投影を計算しています…（初回は環境作成に時間がかかります）",
                lambda: _calculate_projection(options),
            )
        segments = projection_to_segments(
            projection,
            center_mm=options.center_mm,
            include_hidden=options.include_hidden,
            flip_y=options.flip_y,
            merge_collinear=options.merge_collinear,
            merge_endpoint_tolerance_mm=options.merge_endpoint_tolerance_mm,
            merge_angle_tolerance_degrees=options.merge_angle_tolerance_degrees,
        )
        result = _add_segments(
            board,
            segments,
            source_name=options.step_path.name,
            layer_name=options.layer,
            line_width_mm=options.line_width_mm,
            group_created=options.group_created,
            select_created=options.select_created,
        )
    except Exception as exc:
        wx.MessageBox(str(exc), "STEP投影の読み込みに失敗", wx.OK | wx.ICON_ERROR)
        return

    group_text = f"\nグループ: {result.group_name}" if result.group_name else ""
    wx.MessageBox(
        f"{result.segment_count:,} 本の線分を {options.layer} に追加しました。{group_text}",
        "STEP投影の読み込み完了",
        wx.OK | wx.ICON_INFORMATION,
    )


class StepProjectionPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = "STEP投影をグラフィックとして読み込む"
        self.category = "Import"
        self.description = "STEPモデルの正投影をPCBグラフィックとして追加します"
        self.show_toolbar_button = False

    def Run(self):
        run()
