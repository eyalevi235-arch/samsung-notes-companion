"""Samsung Notes companion: toolbar, split canvases, and S Pen ink."""

from __future__ import annotations

import io
import json
import math
import os
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window
from kivy.graphics import Color, Line, PopMatrix, PushMatrix, Rectangle, Scale, Translate
from kivy.input.motionevent import MotionEvent
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

Point = Tuple[float, float]
Rgba = Tuple[float, float, float, float]
StrokeRecord = Dict[str, Any]

LETTERBOX: Rgba = (0.90, 0.90, 0.91, 1.0)
PAGE_WHITE: Rgba = (1.0, 1.0, 1.0, 1.0)
SPEN_ERASER_WIDTH = 15.0
TOOL_FINGER = 1
TOOL_STYLUS = 2
TOOL_ERASER = 4
MIN_SCALE = 0.45
MAX_SCALE = 6.0
DASH_LENGTH = 18.0
GAP_LENGTH = 12.0
COLOR_BLACK: Rgba = (0.0, 0.0, 0.0, 1.0)
COLOR_RED: Rgba = (0.90, 0.22, 0.22, 1.0)
COLOR_BLUE: Rgba = (0.12, 0.23, 0.54, 1.0)
BTN_IDLE: Rgba = (0.88, 0.88, 0.90, 1.0)
BTN_ACTIVE: Rgba = (0.55, 0.72, 0.95, 1.0)

OPEN_REQUEST = 4101
SAVE_REQUEST = 4102
SPEN_KEYCODES = {110, 139, 188, 189, 308, 309}

SAVE_TYPES: Sequence[Tuple[str, str, str]] = (
    (".notes", "application/json", "Companion (*.notes)"),
    (".json", "application/json", "JSON (*.json)"),
    (".pdf", "application/pdf", "PDF (*.pdf)"),
    (".sdocx", "application/octet-stream", "Samsung Notes (*.sdocx)"),
    (".png", "image/png", "PNG image (*.png)"),
)


def is_android() -> bool:
    return platform == "android"


def _dist2(left: Sequence[float], right: Sequence[float]) -> float:
    dx = float(left[0]) - float(right[0])
    dy = float(left[1]) - float(right[1])
    return dx * dx + dy * dy


def dashed_polylines(
    points: Sequence[Sequence[float]],
    dash_len: float = DASH_LENGTH,
    gap_len: float = GAP_LENGTH,
) -> List[List[float]]:
    """Split a polyline into visible dash segments (works on Android GLES)."""
    if len(points) < 2:
        return []
    dashes: List[List[float]] = []
    drawing = True
    remaining = dash_len
    current = [float(points[0][0]), float(points[0][1])]
    cursor = (float(points[0][0]), float(points[0][1]))

    for raw in points[1:]:
        target = (float(raw[0]), float(raw[1]))
        while True:
            dx = target[0] - cursor[0]
            dy = target[1] - cursor[1]
            seg_len = math.hypot(dx, dy)
            if seg_len <= 1e-6:
                break
            step = min(remaining, seg_len)
            ratio = step / seg_len
            cursor = (cursor[0] + dx * ratio, cursor[1] + dy * ratio)
            if drawing:
                current.extend([cursor[0], cursor[1]])
            remaining -= step
            if remaining > 1e-6:
                break
            if drawing and len(current) >= 4:
                dashes.append(current)
            drawing = not drawing
            remaining = dash_len if drawing else gap_len
            current = [cursor[0], cursor[1]]
    if drawing and len(current) >= 4:
        dashes.append(current)
    return dashes


def _jpeg_pages_to_pdf(pages: Sequence[Tuple[bytes, int, int]]) -> bytes:
    """Write a simple PDF 1.4 file that embeds one JPEG image per page."""
    if not pages:
        pages = [(b"", 100, 100)]
    objects: List[bytes] = []

    def add(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + index * 3} 0 R" for index in range(len(pages)))
    add(
        f"<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>".encode("ascii")
    )
    for index, (jpeg, width, height) in enumerate(pages):
        page_id = 3 + index * 3
        img_id = page_id + 2
        add(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
                f"/Resources << /XObject << /Im0 {img_id} 0 R >> >> "
                f"/Contents {page_id + 1} 0 R >>"
            ).encode("ascii")
        )
        stream = f"q {width} 0 0 {height} 0 0 cm /Im0 Do Q".encode("ascii")
        add(
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )
        add(
            (
                f"<< /Type /XObject /Subtype /Image /Width {width} "
                f"/Height {height} /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                f"/Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n"
            ).encode("ascii")
            + jpeg
            + b"\nendstream"
        )
    body = b""
    offsets = [0]
    cursor = 0
    header = b"%PDF-1.4\n"
    cursor += len(header)
    for index, obj in enumerate(objects, start=1):
        offsets.append(cursor)
        chunk = f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
        body += chunk
        cursor += len(chunk)
    xref_pos = cursor
    xref = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
    for offset in offsets[1:]:
        xref += f"{offset:010d} 00000 n \n".encode("ascii")
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode("ascii")
    return header + body + xref + trailer


class SPenAnnotationCanvas(Widget):
    """Page-aligned canvas: S Pen draws, fingers pan/pinch, view is shared."""

    ink_width = NumericProperty(2.5)
    min_width = NumericProperty(1.0)
    max_width = NumericProperty(6.0)
    show_document_image = BooleanProperty(False)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.strokes: List[StrokeRecord] = []
        self.current_stroke: List[Point] = []
        self._bg_rect: Optional[Rectangle] = None
        self._live_color: Rgba = COLOR_BLACK
        self._live_width: float = 2.5
        self._live_dashed: bool = False
        self._bg_texture: Any = None
        with self.canvas.before:
            Color(*LETTERBOX)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._on_geom, size=self._on_geom)
        app = App.get_running_app()
        app.bind(
            view_scale=self._on_view,
            view_pan_x=self._on_view,
            view_pan_y=self._on_view,
            page_width=self._on_view,
            page_height=self._on_view,
        )
        Clock.schedule_once(lambda _dt: self.redraw_all(), 0)

    def _on_geom(self, *_args: Any) -> None:
        if self._bg_rect is not None:
            self._bg_rect.pos = self.pos
            self._bg_rect.size = self.size
        self.redraw_all()

    def _on_view(self, *_args: Any) -> None:
        self.redraw_all()

    def set_background_image(self, path: str) -> None:
        image = CoreImage(path)
        self._bg_texture = image.texture
        app = App.get_running_app()
        app.page_width = float(image.texture.size[0])
        app.page_height = float(image.texture.size[1])
        self.redraw_all()

    def _page_metrics(self) -> Tuple[float, float, float, float, float, float, float]:
        app = App.get_running_app()
        page_w = max(1.0, float(app.page_width))
        page_h = max(1.0, float(app.page_height))
        width, height = float(self.width), float(self.height)
        fit = min(width / page_w, height / page_h)
        scale = fit * float(app.view_scale)
        disp_w, disp_h = page_w * scale, page_h * scale
        origin_x = self.x + (width - disp_w) / 2.0 + float(app.view_pan_x)
        origin_y = self.y + (height - disp_h) / 2.0 + float(app.view_pan_y)
        return origin_x, origin_y, disp_w, disp_h, scale, page_w, page_h

    def to_doc(self, x: float, y: float) -> Point:
        origin_x, origin_y, _dw, _dh, scale, _pw, _ph = self._page_metrics()
        if scale <= 1e-6:
            return (0.0, 0.0)
        return ((x - origin_x) / scale, (y - origin_y) / scale)

    def _classify(self, touch: MotionEvent) -> str:
        if getattr(touch, "is_mouse_scrolling", False):
            return "wheel"
        button = str(getattr(touch, "button", None) or "").lower()
        app = App.get_running_app()
        if button == "right" or getattr(app, "spen_button_held", False):
            return "eraser"
        if not is_android():
            return "stylus"
        tool = int(getattr(app, "tool_type", 0) or 0)
        if tool == TOOL_ERASER:
            return "eraser"
        if tool == TOOL_STYLUS:
            return "stylus"
        return "finger"

    def _line_width_for_touch(self, touch: MotionEvent) -> float:
        if "pressure" in getattr(touch, "profile", []):
            pressure = max(0.0, min(1.0, float(touch.pressure)))
            span = self.max_width - self.min_width
            return float(self.min_width + span * pressure)
        return float(self.ink_width)

    def _should_erase(self, touch: MotionEvent) -> bool:
        app = App.get_running_app()
        if getattr(touch, "button", None) == "right":
            return True
        if bool(getattr(app, "spen_button_held", False)):
            return True
        if bool(getattr(app, "is_eraser", False)):
            return True
        return int(getattr(app, "tool_type", 0) or 0) == TOOL_ERASER

    def _draw_record(self, record: StrokeRecord) -> None:
        color = tuple(record.get("color", COLOR_BLACK))
        width = float(record.get("width", self.ink_width))
        points = record.get("points") or []
        if len(points) < 2:
            return
        Color(*color)
        if record.get("dashed"):
            for dash in dashed_polylines(points):
                Line(points=dash, width=width, cap="round", joint="round")
        else:
            flat: List[float] = []
            for point in points:
                flat.extend([float(point[0]), float(point[1])])
            Line(points=flat, width=width, cap="round", joint="round")

    def redraw_all(self) -> None:
        origin_x, origin_y, _dw, _dh, scale, page_w, page_h = self._page_metrics()
        self.canvas.clear()
        with self.canvas:
            PushMatrix()
            Translate(origin_x, origin_y)
            Scale(scale, scale, 1)
            Color(*PAGE_WHITE)
            Rectangle(pos=(0, 0), size=(page_w, page_h))
            if self.show_document_image and self._bg_texture is not None:
                Color(1, 1, 1, 1)
                Rectangle(texture=self._bg_texture, pos=(0, 0), size=(page_w, page_h))
            for record in self.strokes:
                self._draw_record(record)
            if len(self.current_stroke) >= 2:
                self._draw_record(
                    {
                        "points": [list(point) for point in self.current_stroke],
                        "color": list(self._live_color),
                        "width": self._live_width,
                        "dashed": self._live_dashed,
                    }
                )
            PopMatrix()

    def _erase_at(self, x: float, y: float, radius: float) -> None:
        radius_sq = radius * radius
        kept: List[StrokeRecord] = []
        changed = False
        for record in self.strokes:
            fragment: List[List[float]] = []
            pieces: List[List[List[float]]] = []
            for point in record.get("points") or []:
                if _dist2(point, (x, y)) <= radius_sq:
                    changed = True
                    if len(fragment) >= 2:
                        pieces.append(fragment)
                    fragment = []
                else:
                    fragment.append([float(point[0]), float(point[1])])
            if len(fragment) >= 2:
                pieces.append(fragment)
            for piece in pieces:
                clone = dict(record)
                clone["points"] = piece
                kept.append(clone)
        if changed:
            self.strokes = kept
            self.redraw_all()

    def _begin_pinch(self, app: Any) -> None:
        points = list(app._fingers.values())
        if len(points) < 2:
            return
        dist = math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1])
        app._pinch_dist = max(dist, 1.0)
        app._pinch_scale = float(app.view_scale)
        app._pinch_mid = (
            (points[0][0] + points[1][0]) / 2.0,
            (points[0][1] + points[1][1]) / 2.0,
        )
        app._pinch_doc = self.to_doc(*app._pinch_mid)

    def _update_pinch(self, app: Any) -> None:
        points = list(app._fingers.values())
        if len(points) < 2 or not getattr(app, "_pinch_dist", 0):
            return
        dist = math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1])
        mid = (
            (points[0][0] + points[1][0]) / 2.0,
            (points[0][1] + points[1][1]) / 2.0,
        )
        new_scale = max(
            MIN_SCALE,
            min(MAX_SCALE, app._pinch_scale * (dist / app._pinch_dist)),
        )
        app.view_scale = new_scale
        doc_x, doc_y = app._pinch_doc
        _ox, _oy, _dw, _dh, scale, page_w, page_h = self._page_metrics()
        fit_x = self.x + (self.width - page_w * scale) / 2.0
        fit_y = self.y + (self.height - page_h * scale) / 2.0
        app.view_pan_x = mid[0] - fit_x - doc_x * scale
        app.view_pan_y = mid[1] - fit_y - doc_y * scale

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        kind = self._classify(touch)
        if kind == "wheel":
            app = App.get_running_app()
            factor = 1.12 if touch.button == "scrollup" else 0.89
            app.view_scale = max(MIN_SCALE, min(MAX_SCALE, app.view_scale * factor))
            return True
        if kind == "finger":
            app = App.get_running_app()
            touch.grab(self)
            app._fingers[touch.uid] = (touch.x, touch.y)
            if len(app._fingers) >= 2:
                touch.ud["mode"] = "pinch"
                self._begin_pinch(app)
            else:
                touch.ud["mode"] = "pan"
                touch.ud["last"] = (touch.x, touch.y)
            return True

        touch.grab(self)
        doc = self.to_doc(touch.x, touch.y)
        if kind == "eraser" or self._should_erase(touch):
            touch.ud["erasing"] = True
            _ox, _oy, _dw, _dh, scale, _pw, _ph = self._page_metrics()
            self._erase_at(doc[0], doc[1], SPEN_ERASER_WIDTH / max(scale, 0.01))
            return True

        app = App.get_running_app()
        self._live_color = tuple(getattr(app, "current_color", COLOR_BLACK))
        self._live_width = self._line_width_for_touch(touch)
        self._live_dashed = bool(getattr(app, "is_dashed", False))
        self.current_stroke = [doc]
        return True

    def on_touch_move(self, touch: MotionEvent) -> bool:
        if touch.grab_current is not self:
            return super().on_touch_move(touch)
        app = App.get_running_app()
        mode = touch.ud.get("mode")
        if mode == "pan":
            last = touch.ud.get("last", (touch.x, touch.y))
            app.view_pan_x += touch.x - last[0]
            app.view_pan_y += touch.y - last[1]
            touch.ud["last"] = (touch.x, touch.y)
            return True
        if mode == "pinch" or touch.uid in getattr(app, "_fingers", {}):
            app._fingers[touch.uid] = (touch.x, touch.y)
            if len(app._fingers) >= 2:
                self._update_pinch(app)
            return True
        if touch.ud.get("erasing"):
            doc = self.to_doc(touch.x, touch.y)
            _ox, _oy, _dw, _dh, scale, _pw, _ph = self._page_metrics()
            self._erase_at(doc[0], doc[1], SPEN_ERASER_WIDTH / max(scale, 0.01))
            return True
        self.current_stroke.append(self.to_doc(touch.x, touch.y))
        self.redraw_all()
        return True

    def on_touch_up(self, touch: MotionEvent) -> bool:
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        app = App.get_running_app()
        app._fingers.pop(touch.uid, None)
        if touch.ud.get("mode") in {"pan", "pinch"}:
            if len(app._fingers) >= 2:
                self._begin_pinch(app)
            return True
        if touch.ud.get("erasing"):
            return True
        if len(self.current_stroke) >= 2:
            self.strokes.append(
                {
                    "points": [list(point) for point in self.current_stroke],
                    "color": list(self._live_color),
                    "width": self._live_width,
                    "dashed": self._live_dashed,
                    "eraser": False,
                }
            )
        self.current_stroke = []
        self.redraw_all()
        return True

    def serialized_strokes(self) -> List[StrokeRecord]:
        return json.loads(json.dumps(self.strokes))

    def load_strokes(self, records: Sequence[StrokeRecord]) -> None:
        self.strokes = [dict(record) for record in records]
        self.redraw_all()


class RootLayout(BoxLayout):
    """Light-themed shell: toolbar, PDF canvas, collapsible notes panel."""

    notes_expanded = BooleanProperty(True)

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", dp(6))
        kwargs.setdefault("padding", dp(6))
        super().__init__(**kwargs)

        self.pdf_canvas = SPenAnnotationCanvas(show_document_image=True)
        self.notes_canvas = SPenAnnotationCanvas(show_document_image=False)
        self.side_panel = self._build_side_panel()
        self.status_label = Label(
            text="",
            size_hint_y=None,
            height=dp(22),
            color=(0.2, 0.2, 0.22, 1),
            halign="left",
            valign="middle",
        )
        self.tool_buttons: Dict[str, Button] = {}
        self.page_label = Label(
            text="אין PDF פתוח",
            size_hint_x=0.4,
            color=(0.2, 0.2, 0.22, 1),
        )
        self.add_widget(self._build_toolbar())
        self.add_widget(self._build_page_bar())
        self.add_widget(self._build_workspace())
        self.add_widget(self.status_label)
        self.refresh_tool_styles()
        Window.bind(size=lambda *_args: self.apply_orientation())
        Clock.schedule_once(lambda _dt: self.apply_orientation(), 0)

    def set_status(self, message: str) -> None:
        self.status_label.text = message

    def _build_toolbar(self) -> BoxLayout:
        app = App.get_running_app()
        toolbar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(4),
        )
        actions: Sequence[Tuple[str, str, Any]] = (
            ("open", "Open PDF", app.open_pdf),
            ("save", "Save .notes", app.save_document),
            ("save_as", "Save As", app.save_document_as),
            ("black", "Black", app.set_color_black),
            ("red", "Red", app.set_color_red),
            ("blue", "Blue", app.set_color_blue),
            ("dashed", "Dashed line", app.toggle_dashed),
            ("eraser", "Eraser", app.enable_eraser),
            ("toggle", "Toggle Notes", self.toggle_notes),
        )
        for key, label, handler in actions:
            button = Button(text=label, color=(0.12, 0.12, 0.14, 1))
            button.bind(on_release=handler)
            toolbar.add_widget(button)
            self.tool_buttons[key] = button
        return toolbar

    def refresh_tool_styles(self) -> None:
        app = App.get_running_app()
        mapping = {
            "black": app.current_color == COLOR_BLACK and not app.is_eraser,
            "red": app.current_color == COLOR_RED and not app.is_eraser,
            "blue": app.current_color == COLOR_BLUE and not app.is_eraser,
            "dashed": bool(app.is_dashed) and not app.is_eraser,
            "eraser": bool(app.is_eraser),
        }
        for key, button in self.tool_buttons.items():
            active = mapping.get(key, False)
            button.background_color = BTN_ACTIVE if active else BTN_IDLE

    def _build_side_panel(self) -> BoxLayout:
        panel = BoxLayout(
            orientation="vertical",
            size_hint_x=0.32,
            spacing=dp(4),
            padding=dp(4),
        )
        panel.add_widget(
            Label(
                text="Notes",
                size_hint_y=None,
                height=dp(28),
                bold=True,
                color=(0.2, 0.2, 0.22, 1),
            )
        )
        panel.add_widget(self.notes_canvas)
        return panel

    def _build_page_bar(self) -> BoxLayout:
        app = App.get_running_app()
        bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(36),
            spacing=dp(6),
        )
        prev_btn = Button(text="עמוד קודם", size_hint_x=0.3)
        next_btn = Button(text="עמוד הבא", size_hint_x=0.3)
        prev_btn.bind(on_release=app.prev_pdf_page)
        next_btn.bind(on_release=app.next_pdf_page)
        bar.add_widget(prev_btn)
        bar.add_widget(self.page_label)
        bar.add_widget(next_btn)
        return bar

    def _build_workspace(self) -> BoxLayout:
        self.workspace = BoxLayout(orientation="horizontal", spacing=dp(6))
        self.workspace.add_widget(self.pdf_canvas)
        self.workspace.add_widget(self.side_panel)
        return self.workspace

    def apply_orientation(self, *_args: Any) -> None:
        """Stack the notes panel under the PDF in portrait; side-by-side in landscape."""
        portrait = Window.height > Window.width
        self.workspace.orientation = "vertical" if portrait else "horizontal"
        if not self.notes_expanded:
            self.side_panel.opacity = 0
            self.side_panel.disabled = True
            if portrait:
                self.side_panel.size_hint = (1, 0)
                self.pdf_canvas.size_hint = (1, 1)
            else:
                self.side_panel.size_hint = (0, 1)
                self.pdf_canvas.size_hint = (1, 1)
            return
        self.side_panel.opacity = 1
        self.side_panel.disabled = False
        if portrait:
            self.pdf_canvas.size_hint = (1, 0.72)
            self.side_panel.size_hint = (1, 0.28)
        else:
            self.pdf_canvas.size_hint = (0.68, 1)
            self.side_panel.size_hint = (0.32, 1)

    def toggle_notes(self, *_args: Any) -> None:
        self.notes_expanded = not self.notes_expanded
        self.apply_orientation()

    def set_page_status(self, index: int, count: int) -> None:
        if count <= 0:
            self.page_label.text = "אין PDF פתוח"
            return
        self.page_label.text = f"עמוד {index + 1} מתוך {count}"


class SamsungNotesCompanionApp(App):
    """Application state and entry point for the companion client."""

    view_scale = NumericProperty(1.0)
    view_pan_x = NumericProperty(0.0)
    view_pan_y = NumericProperty(0.0)
    page_width = NumericProperty(800.0)
    page_height = NumericProperty(1100.0)
    tool_type = NumericProperty(0)

    def build(self) -> RootLayout:
        Window.clearcolor = (0.95, 0.95, 0.95, 1)
        self.title = "Samsung Notes Companion"
        self.current_color: Rgba = COLOR_BLACK
        self.is_eraser: bool = False
        self.is_dashed: bool = False
        self.spen_button_held: bool = False
        self.pointer_count = 1
        self._fingers: Dict[Any, Tuple[float, float]] = {}
        self.pdf_path: Optional[str] = None
        self._pdf_page_index: int = 0
        self._pdf_page_count: int = 0
        self._page_strokes: Dict[int, List[StrokeRecord]] = {}
        self._notes_strokes: Dict[int, List[StrokeRecord]] = {}
        self._pending_save: Optional[Tuple[str, str]] = None
        self._stylus_listener: Any = None
        self.root_layout = RootLayout()
        Window.bind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)
        if is_android():
            self._setup_android()
        return self.root_layout

    def _notify(self, message: str) -> None:
        self.root_layout.set_status(message)
        if not is_android():
            return
        try:
            from android.runnable import run_on_ui_thread
            from jnius import autoclass

            Toast = autoclass("android.widget.Toast")
            String = autoclass("java.lang.String")
            activity = autoclass("org.kivy.android.PythonActivity").mActivity

            @run_on_ui_thread
            def _toast() -> None:
                Toast.makeText(activity, String(message), Toast.LENGTH_SHORT).show()

            _toast()
        except Exception:
            pass

    def _on_key_down(self, *_args: Any, **kwargs: Any) -> bool:
        key = _args[1] if len(_args) > 1 else None
        code = key[0] if isinstance(key, (tuple, list)) else key
        try:
            if int(code) in SPEN_KEYCODES:
                self.spen_button_held = True
        except (TypeError, ValueError):
            pass
        return False

    def _on_key_up(self, *_args: Any, **kwargs: Any) -> bool:
        key = _args[1] if len(_args) > 1 else None
        code = key[0] if isinstance(key, (tuple, list)) else key
        try:
            if int(code) in SPEN_KEYCODES:
                self.spen_button_held = False
        except (TypeError, ValueError):
            pass
        return False

    def _setup_android(self) -> None:
        try:
            from android import activity

            activity.bind(on_activity_result=self._on_activity_result)
        except Exception:
            pass
        self._attach_spen_listeners()

    def _update_spen_from_motion(self, event: Any) -> None:
        try:
            state = int(event.getButtonState())
            tool = int(event.getToolType(0))
            self.pointer_count = int(event.getPointerCount())
        except Exception:
            return
        self.tool_type = tool
        stylus_bits = 0x02 | 0x20 | 0x40
        self.spen_button_held = bool(state & stylus_bits) or tool == TOOL_ERASER

    def _attach_spen_listeners(self) -> None:
        try:
            from android.runnable import run_on_ui_thread
            from jnius import PythonJavaClass, autoclass, java_method

            app = self

            class StylusListener(PythonJavaClass):
                __javacontext__ = "app"
                __javainterfaces__ = [
                    "android.view.View$OnGenericMotionListener",
                    "android.view.View$OnHoverListener",
                    "android.view.View$OnTouchListener",
                ]

                @java_method("(Landroid/view/View;Landroid/view/MotionEvent;)Z")
                def onGenericMotion(self, _view, event):
                    app._update_spen_from_motion(event)
                    return False

                @java_method("(Landroid/view/View;Landroid/view/MotionEvent;)Z")
                def onHover(self, _view, event):
                    app._update_spen_from_motion(event)
                    return False

                @java_method("(Landroid/view/View;Landroid/view/MotionEvent;)Z")
                def onTouch(self, _view, event):
                    app._update_spen_from_motion(event)
                    return False

            listener = StylusListener()
            self._stylus_listener = listener
            activity = autoclass("org.kivy.android.PythonActivity").mActivity

            @run_on_ui_thread
            def _attach() -> None:
                view = activity.getWindow().getDecorView()
                view.setOnGenericMotionListener(listener)
                view.setOnHoverListener(listener)
                view.setOnTouchListener(listener)

            _attach()
        except Exception:
            pass

    def _on_activity_result(
        self, request_code: int, result_code: int, intent: Any
    ) -> None:
        Clock.schedule_once(
            lambda _dt: self._handle_activity_result(
                request_code, result_code, intent
            )
        )

    def _handle_activity_result(
        self, request_code: int, result_code: int, intent: Any
    ) -> None:
        try:
            from jnius import autoclass

            activity_cls = autoclass("android.app.Activity")
            if result_code != activity_cls.RESULT_OK or intent is None:
                self._notify("הפעולה בוטלה")
                return
            uri = intent.getData()
            if uri is None:
                return
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            flags = intent.getFlags()
            take = autoclass("android.content.Intent")
            grant = take.FLAG_GRANT_READ_URI_PERMISSION | (
                take.FLAG_GRANT_WRITE_URI_PERMISSION
            )
            try:
                activity.getContentResolver().takePersistableUriPermission(
                    uri, flags & grant
                )
            except Exception:
                pass
            if request_code == OPEN_REQUEST:
                self._open_android_uri(uri)
            elif request_code == SAVE_REQUEST and self._pending_save:
                self._write_android_uri(uri, *self._pending_save)
                self._pending_save = None
        except Exception as exc:
            self._notify(f"שגיאה בפתיחת הקובץ: {exc}")

    def _copy_uri_to_temp(self, uri: Any, suffix: str) -> str:
        from jnius import autoclass

        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        resolver = activity.getContentResolver()
        source = resolver.openInputStream(uri)
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        handle.close()
        dest = autoclass("java.io.FileOutputStream")(handle.name)
        copied = False
        try:
            file_utils = autoclass("android.os.FileUtils")
            file_utils.copy(source, dest)
            copied = True
        except Exception:
            pass
        if not copied:
            data = bytes()
            chunk = source.read()
            while chunk != -1:
                data += bytes([chunk & 0xFF])
                chunk = source.read()
            with open(handle.name, "wb") as out:
                out.write(data)
        dest.close()
        source.close()
        return handle.name

    def _open_pdf_pfd(self, uri: Any = None) -> Any:
        from jnius import autoclass

        activity = self._android_activity()
        resolver = activity.getContentResolver()
        if uri is not None:
            return resolver.openFileDescriptor(uri, "r")
        path = self.pdf_path or ""
        if path.startswith("content:") or path.startswith("file:"):
            parsed = autoclass("android.net.Uri").parse(path)
            return resolver.openFileDescriptor(parsed, "r")
        file_cls = autoclass("java.io.File")
        pfd_cls = autoclass("android.os.ParcelFileDescriptor")
        return pfd_cls.open(file_cls(path), pfd_cls.MODE_READ_ONLY)

    def _pdf_page_count_from(self, uri: Any = None) -> int:
        from jnius import autoclass

        pfd = self._open_pdf_pfd(uri)
        renderer = autoclass("android.graphics.pdf.PdfRenderer")(pfd)
        count = int(renderer.getPageCount())
        renderer.close()
        pfd.close()
        return count

    def _render_pdf_page(self, index: int, uri: Any = None) -> Optional[str]:
        try:
            from jnius import autoclass

            pfd = self._open_pdf_pfd(uri)
            renderer = autoclass("android.graphics.pdf.PdfRenderer")(pfd)
            page = renderer.openPage(int(index))
            scale = 2
            width = max(1, int(page.getWidth() * scale))
            height = max(1, int(page.getHeight() * scale))
            bitmap_cls = autoclass("android.graphics.Bitmap")
            config = autoclass("android.graphics.Bitmap$Config")
            bitmap = bitmap_cls.createBitmap(width, height, config.ARGB_8888)
            matrix = autoclass("android.graphics.Matrix")()
            matrix.setScale(float(scale), float(scale))
            page.render(bitmap, None, matrix, 1)
            page.close()
            renderer.close()
            pfd.close()
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            handle.close()
            stream = autoclass("java.io.FileOutputStream")(handle.name)
            fmt = autoclass("android.graphics.Bitmap$CompressFormat")
            bitmap.compress(fmt.PNG, 100, stream)
            stream.close()
            return handle.name
        except Exception:
            return None

    def _stash_current_page_strokes(self) -> None:
        self._page_strokes[self._pdf_page_index] = (
            self.root_layout.pdf_canvas.serialized_strokes()
        )
        self._notes_strokes[self._pdf_page_index] = (
            self.root_layout.notes_canvas.serialized_strokes()
        )

    def _reset_view(self) -> None:
        self.view_scale = 1.0
        self.view_pan_x = 0.0
        self.view_pan_y = 0.0

    def _show_pdf_page(self, index: int, uri: Any = None) -> None:
        if self._pdf_page_count <= 0:
            return
        index = max(0, min(index, self._pdf_page_count - 1))
        self._stash_current_page_strokes()
        self._pdf_page_index = index
        preview = self._render_pdf_page(index, uri)
        if preview:
            self.root_layout.pdf_canvas.set_background_image(preview)
        self.root_layout.pdf_canvas.load_strokes(
            self._page_strokes.get(index, [])
        )
        self.root_layout.notes_canvas.load_strokes(
            self._notes_strokes.get(index, [])
        )
        self.root_layout.set_page_status(index, self._pdf_page_count)

    def prev_pdf_page(self, *_args: Any) -> None:
        if self._pdf_page_count <= 0:
            self._notify("קודם פתחו קובץ PDF")
            return
        self._show_pdf_page(self._pdf_page_index - 1)

    def next_pdf_page(self, *_args: Any) -> None:
        if self._pdf_page_count <= 0:
            self._notify("קודם פתחו קובץ PDF")
            return
        self._show_pdf_page(self._pdf_page_index + 1)

    def _uri_is_pdf(self, uri: Any) -> bool:
        try:
            mime = str(self._android_activity().getContentResolver().getType(uri) or "")
            if "pdf" in mime.lower():
                return True
        except Exception:
            pass
        name = str(uri.toString()).lower()
        return name.endswith(".pdf") or "/pdf" in name or "pdf" in name

    def _open_android_uri(self, uri: Any) -> None:
        display = str(uri.getLastPathSegment() or uri.toString())
        if self._uri_is_pdf(uri):
            try:
                self.pdf_path = str(uri.toString())
                self._page_strokes = {}
                self._notes_strokes = {}
                self._pdf_page_index = 0
                self._reset_view()
                self._pdf_page_count = self._pdf_page_count_from(uri)
                self.root_layout.pdf_canvas.load_strokes([])
                self.root_layout.notes_canvas.load_strokes([])
                self._show_pdf_page(0, uri)
                self._notify(f"PDF נפתח לכתיבה: {display}")
            except Exception as exc:
                self._notify(f"לא ניתן להציג את ה-PDF: {exc}")
            return
        lower = display.lower()
        if ".sdocx" in lower:
            suffix = ".sdocx"
        elif ".notes" in lower:
            suffix = ".notes"
        else:
            suffix = ".json"
        try:
            path = self._copy_uri_to_temp(uri, suffix)
            self._load_notes_file(path)
            self._notify(f"נפתח: {display}")
        except Exception as exc:
            self._notify(f"לא ניתן לפתוח את הקובץ: {exc}")

    def _write_android_uri(self, uri: Any, extension: str, mime: str) -> None:
        from jnius import autoclass

        handle = tempfile.NamedTemporaryFile(delete=False, suffix=extension)
        handle.close()
        self._write_local_path(handle.name, extension)
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        resolver = activity.getContentResolver()
        source = autoclass("java.io.FileInputStream")(handle.name)
        dest = resolver.openOutputStream(uri)
        autoclass("android.os.FileUtils").copy(source, dest)
        source.close()
        dest.close()
        self._notify("הקובץ נשמר")

    def _document_bytes(self, extension: str) -> bytes:
        if extension == ".png":
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            handle.close()
            self.root_layout.workspace.export_to_png(handle.name)
            with open(handle.name, "rb") as png:
                return png.read()
        if extension == ".pdf":
            return self._export_pdf_bytes()
        if extension == ".sdocx":
            return self._export_sdocx_bytes()
        text = json.dumps(self._document_payload(), indent=2)
        return text.encode("utf-8")

    def _document_payload(self) -> Dict[str, Any]:
        self._stash_current_page_strokes()
        return {
            "pdf_path": self.pdf_path,
            "pdf_page_index": self._pdf_page_index,
            "pdf_page_count": self._pdf_page_count,
            "view_scale": float(self.view_scale),
            "pdf_pages": {
                str(index): strokes
                for index, strokes in self._page_strokes.items()
            },
            "notes_pages": {
                str(index): strokes
                for index, strokes in self._notes_strokes.items()
            },
            "pdf_canvas": self.root_layout.pdf_canvas.serialized_strokes(),
            "notes_canvas": self.root_layout.notes_canvas.serialized_strokes(),
        }

    def _stroke_on_image(self, image: Any, strokes: Sequence[StrokeRecord]) -> None:
        from PIL import ImageDraw

        drawer = ImageDraw.Draw(image)
        height = image.size[1]
        for record in strokes:
            points = record.get("points") or []
            if len(points) < 2:
                continue
            color = record.get("color", COLOR_BLACK)
            fill = tuple(max(0, min(255, int(c * 255))) for c in color[:3])
            width = max(1, int(record.get("width", 2)))
            xy = [(float(p[0]), height - float(p[1])) for p in points]
            if record.get("dashed"):
                dashes = dashed_polylines(points)
                for dash in dashes:
                    pair = [
                        (dash[i], height - dash[i + 1])
                        for i in range(0, len(dash) - 1, 2)
                    ]
                    if len(pair) >= 2:
                        drawer.line(pair, fill=fill, width=width)
            else:
                drawer.line(xy, fill=fill, width=width)

    def _render_export_pngs(self) -> List[Tuple[bytes, int, int]]:
        from PIL import Image

        self._stash_current_page_strokes()
        pages: List[Tuple[bytes, int, int]] = []
        count = max(1, int(self._pdf_page_count) or 1)
        for index in range(count):
            background = None
            if self.pdf_path and is_android():
                preview = self._render_pdf_page(index)
                if preview:
                    background = Image.open(preview).convert("RGB")
            if background is None:
                background = Image.new(
                    "RGB",
                    (int(self.page_width), int(self.page_height)),
                    (255, 255, 255),
                )
            self._stroke_on_image(background, self._page_strokes.get(index, []))
            notes = Image.new("RGB", background.size, (255, 255, 255))
            self._stroke_on_image(notes, self._notes_strokes.get(index, []))
            for image in (background, notes):
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=88)
                pages.append((buffer.getvalue(), image.size[0], image.size[1]))
        return pages

    def _export_pdf_bytes(self) -> bytes:
        pages = self._render_export_pngs()
        return _jpeg_pages_to_pdf(pages)

    def _export_sdocx_bytes(self) -> bytes:
        payload = self._document_payload()
        pdf_bytes = self._export_pdf_bytes()
        buffer = io.BytesIO()
        page_ids = [str(uuid.uuid4()) for _ in range(max(1, self._pdf_page_count or 1))]
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("companion.json", json.dumps(payload, indent=2))
            archive.writestr("Document.pdf", pdf_bytes)
            archive.writestr("note.note", f"Samsung Notes Companion\n{self.title}\n".encode("utf-8"))
            archive.writestr("pageIdInfo.dat", "\n".join(page_ids).encode("utf-8"))
            archive.writestr("media/mediaInfo.dat", b"")
            archive.writestr("end_tag.bin", b"SNOTE")
            for index, page_id in enumerate(page_ids):
                preview = None
                if self.pdf_path and is_android():
                    preview = self._render_pdf_page(index)
                if preview:
                    with open(preview, "rb") as handle:
                        archive.writestr(f"media/{page_id}.png", handle.read())
        return buffer.getvalue()

    def _load_notes_file(self, path: str) -> None:
        if path.lower().endswith(".sdocx"):
            self._load_sdocx_file(path)
            return
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self._apply_payload(payload)

    def _apply_payload(self, payload: Dict[str, Any]) -> None:
        self.pdf_path = payload.get("pdf_path")
        self._page_strokes = {
            int(key): value for key, value in (payload.get("pdf_pages") or {}).items()
        }
        self._notes_strokes = {
            int(key): value for key, value in (payload.get("notes_pages") or {}).items()
        }
        self.root_layout.pdf_canvas.load_strokes(payload.get("pdf_canvas") or [])
        self.root_layout.notes_canvas.load_strokes(
            payload.get("notes_canvas") or []
        )

    def _load_sdocx_file(self, path: str) -> None:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if "companion.json" in names:
                payload = json.loads(archive.read("companion.json").decode("utf-8"))
                self._apply_payload(payload)
            if "Document.pdf" in names:
                handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
                handle.write(archive.read("Document.pdf"))
                handle.close()
                self.pdf_path = handle.name
                if is_android():
                    self._pdf_page_count = self._pdf_page_count_from()
                    self._show_pdf_page(self._pdf_page_index)

    def _android_activity(self) -> Any:
        from jnius import autoclass

        return autoclass("org.kivy.android.PythonActivity").mActivity

    def _launch_android_intent(self, intent: Any, request_code: int) -> None:
        from android.runnable import run_on_ui_thread

        activity = self._android_activity()

        @run_on_ui_thread
        def _start() -> None:
            activity.startActivityForResult(intent, request_code)

        _start()

    def _start_android_open(self) -> None:
        from jnius import autoclass

        Intent = autoclass("android.content.Intent")
        intent = Intent(Intent.ACTION_GET_CONTENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("*/*")
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        self._launch_android_intent(intent, OPEN_REQUEST)

    def _start_android_save(self, extension: str, mime: str) -> None:
        from jnius import autoclass

        self._pending_save = (extension, mime)
        Intent = autoclass("android.content.Intent")
        String = autoclass("java.lang.String")
        intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType(mime)
        intent.putExtra(Intent.EXTRA_TITLE, String(f"my_drawing{extension}"))
        intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        self._launch_android_intent(intent, SAVE_REQUEST)

    def _desktop_start_dir(self) -> str:
        for candidate in (
            Path.home() / "Documents",
            Path.home() / "Download",
            Path.home() / "Downloads",
            Path.home(),
        ):
            if candidate.is_dir():
                return str(candidate)
        return os.getcwd()

    def _desktop_open_dialog(self) -> None:
        chooser = FileChooserListView(
            path=self._desktop_start_dir(),
            filters=["*.pdf", "*.notes", "*.json", "*.sdocx", "*"],
        )
        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        buttons = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        popup = Popup(title="Open file", content=body, size_hint=(0.94, 0.94))

        def _load(_instance: Button) -> None:
            if chooser.selection:
                self._open_local_path(chooser.selection[0])
            popup.dismiss()

        load_btn = Button(text="Open")
        cancel_btn = Button(text="Cancel")
        load_btn.bind(on_release=_load)
        cancel_btn.bind(on_release=lambda _btn: popup.dismiss())
        buttons.add_widget(load_btn)
        buttons.add_widget(cancel_btn)
        body.add_widget(chooser)
        body.add_widget(buttons)
        popup.open()

    def _open_local_path(self, path: str) -> None:
        lower = path.lower()
        if lower.endswith(".pdf"):
            self.pdf_path = path
            self._page_strokes = {}
            self._notes_strokes = {}
            self._pdf_page_index = 0
            self._reset_view()
            if is_android():
                try:
                    self._pdf_page_count = self._pdf_page_count_from()
                    self.root_layout.pdf_canvas.load_strokes([])
                    self.root_layout.notes_canvas.load_strokes([])
                    self._show_pdf_page(0)
                    self._notify(f"PDF נפתח לכתיבה: {os.path.basename(path)}")
                    return
                except Exception as exc:
                    self._notify(f"לא ניתן להציג את ה-PDF: {exc}")
                    return
            self._notify(f"נבחר PDF: {os.path.basename(path)}")
            return
        if lower.endswith((".notes", ".json", ".sdocx")):
            self._load_notes_file(path)
            self._notify(f"נפתח: {os.path.basename(path)}")
            return
        self._notify("סוג הקובץ אינו נתמך")

    def _desktop_save_dialog(self, default_ext: str = ".notes") -> None:
        chooser = FileChooserListView(path=self._desktop_start_dir())
        name_input = TextInput(
            text=f"my_drawing{default_ext}",
            multiline=False,
            size_hint_y=None,
            height=dp(40),
        )
        spinner = Spinner(
            text=SAVE_TYPES[0][2],
            values=[item[2] for item in SAVE_TYPES],
            size_hint_y=None,
            height=dp(40),
        )
        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        buttons = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        popup = Popup(title="Save As", content=body, size_hint=(0.94, 0.94))

        def _ext_for_label(label: str) -> Tuple[str, str]:
            for ext, mime, title in SAVE_TYPES:
                if title == label:
                    return ext, mime
            return ".notes", "application/json"

        def _on_type(_spinner: Spinner, value: str) -> None:
            ext, _mime = _ext_for_label(value)
            stem = Path(name_input.text).stem or "my_drawing"
            name_input.text = f"{stem}{ext}"

        spinner.bind(text=_on_type)

        def _save(_instance: Button) -> None:
            ext, _mime = _ext_for_label(spinner.text)
            directory = chooser.path
            if chooser.selection and os.path.isdir(chooser.selection[0]):
                directory = chooser.selection[0]
            filename = name_input.text.strip() or f"my_drawing{ext}"
            if not filename.lower().endswith(ext):
                filename += ext
            path = os.path.join(directory, filename)
            self._write_local_path(path, ext)
            popup.dismiss()

        save_btn = Button(text="Save")
        cancel_btn = Button(text="Cancel")
        save_btn.bind(on_release=_save)
        cancel_btn.bind(on_release=lambda _btn: popup.dismiss())
        buttons.add_widget(save_btn)
        buttons.add_widget(cancel_btn)
        body.add_widget(chooser)
        body.add_widget(spinner)
        body.add_widget(name_input)
        body.add_widget(buttons)
        popup.open()

    def _write_local_path(self, path: str, extension: str) -> None:
        data = self._document_bytes(extension)
        if extension in {".png", ".pdf", ".sdocx"}:
            with open(path, "wb") as handle:
                handle.write(data)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(data.decode("utf-8"))
        self._notify(f"נשמר: {path}")

    def open_pdf(self, *_args: Any) -> None:
        if is_android():
            try:
                self._start_android_open()
                return
            except Exception as exc:
                self._notify(f"לא ניתן לפתוח את ספריית הקבצים: {exc}")
                return
        self._desktop_open_dialog()

    def save_document(self, *_args: Any) -> None:
        if is_android():
            try:
                self._start_android_save(".notes", "application/json")
                return
            except Exception as exc:
                self._notify(f"לא ניתן לשמור: {exc}")
                return
        self._desktop_save_dialog(".notes")

    def save_document_as(self, *_args: Any) -> None:
        if not is_android():
            self._desktop_save_dialog(".notes")
            return

        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        popup = Popup(title="Save As — choose file type", content=body, size_hint=(0.75, 0.7))
        for ext, mime, title in SAVE_TYPES:
            button = Button(text=title, size_hint_y=None, height=dp(44))

            def _pick(_btn: Button, extension: str = ext, media: str = mime) -> None:
                popup.dismiss()
                self._start_android_save(extension, media)

            button.bind(on_release=_pick)
            body.add_widget(button)
        popup.open()

    def set_color_black(self, *_args: Any) -> None:
        self.is_eraser = False
        self.current_color = COLOR_BLACK
        self.root_layout.refresh_tool_styles()

    def set_color_red(self, *_args: Any) -> None:
        self.is_eraser = False
        self.current_color = COLOR_RED
        self.root_layout.refresh_tool_styles()

    def set_color_blue(self, *_args: Any) -> None:
        self.is_eraser = False
        self.current_color = COLOR_BLUE
        self.root_layout.refresh_tool_styles()

    def toggle_dashed(self, *_args: Any) -> None:
        self.is_dashed = not self.is_dashed
        if self.is_dashed:
            self.is_eraser = False
        self.root_layout.refresh_tool_styles()

    def enable_eraser(self, *_args: Any) -> None:
        self.is_eraser = True
        self.root_layout.refresh_tool_styles()


if __name__ == "__main__":
    SamsungNotesCompanionApp().run()
