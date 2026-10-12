"""Samsung Notes companion: toolbar, split canvases, and S Pen ink."""

from __future__ import annotations

import io
import json
import math
import os
import tempfile

os.environ["SDL_ANDROID_SEPARATE_MOUSE_AND_TOUCH"] = "1"
os.environ["SDL_TOUCH_MOUSE_EVENTS"] = "0"
os.environ["SDL_MOUSE_TOUCH_EVENTS"] = "0"
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics import (
    Color,
    Ellipse,
    Line,
    PopMatrix,
    PushMatrix,
    Rectangle,
    Scale,
    StencilPop,
    StencilPush,
    StencilUnUse,
    StencilUse,
    Translate,
    Triangle,
)
from kivy.input.motionevent import MotionEvent
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.floatlayout import FloatLayout
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
GRID_LINE: Rgba = (0.78, 0.84, 0.92, 1.0)
HEADER_BG: Rgba = (1.0, 1.0, 1.0, 1.0)
TOOLBAR_BG: Rgba = (0.10, 0.10, 0.10, 1.0)
TOOL_IDLE: Rgba = (0.10, 0.10, 0.10, 1.0)
TOOL_ACTIVE: Rgba = (0.28, 0.28, 0.28, 1.0)
SPEN_ERASER_WIDTH = 15.0
TOOL_FINGER = 1
TOOL_STYLUS = 2
TOOL_ERASER = 4
MIN_SCALE = 0.45
MAX_SCALE = 6.0
PAGE_GAP = 28.0
DASH_LENGTH = 18.0
GAP_LENGTH = 12.0
COLOR_BLACK: Rgba = (0.0, 0.0, 0.0, 1.0)
COLOR_BLUE: Rgba = (0.10, 0.38, 0.92, 1.0)
COLOR_GREEN: Rgba = (0.22, 0.70, 0.32, 1.0)
COLOR_RED: Rgba = (0.90, 0.18, 0.22, 1.0)
COLOR_PURPLE: Rgba = (0.58, 0.22, 0.82, 1.0)
INK_COLORS: Sequence[Tuple[str, Rgba]] = (
    ("black", COLOR_BLACK),
    ("blue", COLOR_BLUE),
    ("green", COLOR_GREEN),
    ("red", COLOR_RED),
    ("purple", COLOR_PURPLE),
)
HOVER_ACTIONS = {7, 9, 10}
UP_ACTIONS = {1, 6}

OPEN_REQUEST = 4101
SAVE_REQUEST = 4102
SPEN_KEYCODES = {110, 139, 188, 189, 308, 309}

SAVE_TYPES: Sequence[Tuple[str, str, str]] = (
    (".pdf", "application/pdf", "PDF (*.pdf)"),
    (".sdocx", "application/octet-stream", "Samsung Notes (*.sdocx)"),
    (".json", "application/json", "JSON (*.json)"),
    (".png", "image/png", "PNG image (*.png)"),
)


def is_android() -> bool:
    return platform == "android"


def _first_existing(paths: Sequence[str]) -> Optional[str]:
    for path in paths:
        if os.path.isfile(path):
            return path
    return None


def resolve_latin_font() -> Optional[str]:
    return _first_existing(
        (
            "/system/fonts/Roboto-Regular.ttf",
            "/system/fonts/NotoSans-Regular.ttf",
            "/system/fonts/DroidSans.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
        )
    )


def resolve_hebrew_font() -> Optional[str]:
    return _first_existing(
        (
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
            "/system/fonts/NotoSansHebrew-Regular.ttf",
            "/system/fonts/NotoSansHebrew-VF.ttf",
            "/system/fonts/SamsungSans-Regular.ttf",
            "/system/fonts/Roboto-Regular.ttf",
        )
    )


def apply_ui_font() -> None:
    latin = resolve_latin_font()
    hebrew = resolve_hebrew_font()
    try:
        if latin:
            LabelBase.register(name="LatinFont", fn_regular=latin)
        if hebrew:
            LabelBase.register(name="HebrewFont", fn_regular=hebrew)
    except Exception:
        pass


def set_latin_font(widget: Any) -> None:
    try:
        widget.font_name = "LatinFont"
    except Exception:
        pass


def set_hebrew_font(widget: Any) -> None:
    try:
        widget.font_name = "HebrewFont"
    except Exception:
        pass


def _dist2(left: Sequence[float], right: Sequence[float]) -> float:
    dx = float(left[0]) - float(right[0])
    dy = float(left[1]) - float(right[1])
    return dx * dx + dy * dy


def _dist_point_seg2(
    point: Sequence[float], start: Sequence[float], end: Sequence[float]
) -> float:
    px, py = float(point[0]), float(point[1])
    ax, ay = float(start[0]), float(start[1])
    bx, by = float(end[0]), float(end[1])
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length <= 1e-8:
        return _dist2(point, start)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return (px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2


def _image_rgb_on_white(source: Any) -> Any:
    from PIL import Image

    image = Image.open(source) if isinstance(source, (str, Path)) else source
    if image.mode == "RGB":
        return image
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.split()[3])
    return background


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
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
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


class ToolIcon(ButtonBehavior, Widget):
    """Vector toolbar icon that does not depend on device fonts."""

    kind = StringProperty("pen")
    selected = BooleanProperty(False)
    on_dark = BooleanProperty(True)

    def __init__(self, kind: str, **kwargs: Any) -> None:
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(44), dp(36)))
        super().__init__(**kwargs)
        self.kind = kind
        self.bind(pos=self._redraw, size=self._redraw, selected=self._redraw, on_dark=self._redraw)
        Clock.schedule_once(lambda _dt: self._redraw(), 0)

    def _redraw(self, *_args: Any) -> None:
        self.canvas.clear()
        pad = dp(8)
        x, y = self.x + pad, self.y + pad
        w, h = self.width - 2 * pad, self.height - 2 * pad
        cx, cy = self.center_x, self.center_y
        ink = (1, 1, 1, 1) if self.on_dark else (0.15, 0.15, 0.17, 1)
        bg = TOOL_ACTIVE if self.selected else (TOOL_IDLE if self.on_dark else (1, 1, 1, 1))
        with self.canvas:
            Color(*bg)
            Rectangle(pos=self.pos, size=self.size)
            Color(*ink)
            kind = self.kind
            if kind == "pan":
                Line(points=[cx - w * 0.35, cy, cx + w * 0.35, cy], width=1.4)
                Line(points=[cx, cy - h * 0.35, cx, cy + h * 0.35], width=1.4)
                Line(points=[cx - w * 0.35, cy, cx - w * 0.18, cy + h * 0.12], width=1.2)
                Line(points=[cx - w * 0.35, cy, cx - w * 0.18, cy - h * 0.12], width=1.2)
                Line(points=[cx + w * 0.35, cy, cx + w * 0.18, cy + h * 0.12], width=1.2)
                Line(points=[cx + w * 0.35, cy, cx + w * 0.18, cy - h * 0.12], width=1.2)
            elif kind == "pen":
                Line(points=[x + w * 0.2, y + h * 0.15, x + w * 0.72, y + h * 0.72], width=1.5)
                Triangle(
                    points=[
                        x + w * 0.72,
                        y + h * 0.72,
                        x + w * 0.88,
                        y + h * 0.62,
                        x + w * 0.82,
                        y + h * 0.88,
                    ]
                )
            elif kind == "dashed":
                Line(points=[x, cy, x + w * 0.28, cy], width=1.4)
                Line(points=[x + w * 0.42, cy, x + w * 0.62, cy], width=1.4)
                Line(points=[x + w * 0.76, cy, x + w, cy], width=1.4)
            elif kind == "eraser":
                Line(rectangle=(x + w * 0.15, y + h * 0.25, w * 0.7, h * 0.5), width=1.3)
            elif kind == "hide":
                Line(points=[cx - w * 0.28, cy + h * 0.12, cx, cy - h * 0.18, cx + w * 0.28, cy + h * 0.12], width=1.4)
            elif kind == "restore":
                Line(points=[cx - w * 0.28, cy - h * 0.12, cx, cy + h * 0.18, cx + w * 0.28, cy - h * 0.12], width=1.4)
            elif kind == "plus":
                Line(points=[cx - w * 0.28, cy, cx + w * 0.28, cy], width=1.5)
                Line(points=[cx, cy - h * 0.28, cx, cy + h * 0.28], width=1.5)
            elif kind == "save":
                Line(points=[cx, cy + h * 0.28, cx, cy - h * 0.1], width=1.5)
                Line(points=[cx - w * 0.18, cy + h * 0.08, cx, cy - h * 0.12, cx + w * 0.18, cy + h * 0.08], width=1.3)
                Line(points=[cx - w * 0.28, y + h * 0.08, cx + w * 0.28, y + h * 0.08], width=1.3)
            elif kind == "notes":
                Line(rectangle=(x + w * 0.08, y + h * 0.1, w * 0.35, h * 0.8), width=1.2)
                Line(rectangle=(x + w * 0.55, y + h * 0.1, w * 0.35, h * 0.8), width=1.2)


class ColorDot(ButtonBehavior, Widget):
    """Round ink swatch; a white ring marks the selected color."""

    rgba = ListProperty([0.0, 0.0, 0.0, 1.0])
    selected = BooleanProperty(False)

    def __init__(self, rgba: Rgba, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.rgba = list(rgba)
        self.size_hint = (None, None)
        self.size = (dp(30), dp(30))
        with self.canvas:
            self._fill = Color(*self.rgba)
            self._dot = Ellipse()
            self._ring = Color(1, 1, 1, 0)
            self._ring_line = Line(width=1.4)
        self.bind(pos=self._sync, size=self._sync, selected=self._sync, rgba=self._sync)
        Clock.schedule_once(lambda _dt: self._sync(), 0)

    def _sync(self, *_args: Any) -> None:
        pad = dp(5)
        self._fill.rgba = self.rgba
        self._dot.pos = (self.x + pad, self.y + pad)
        self._dot.size = (self.width - 2 * pad, self.height - 2 * pad)
        cx, cy = self.center_x, self.center_y
        radius = min(self.width, self.height) / 2.0 - dp(2)
        self._ring.a = 1.0 if self.selected else 0.0
        self._ring_line.circle = (cx, cy, radius)


class SPenAnnotationCanvas(Widget):
    """Page-aligned canvas: one contact draws, two contacts pan/pinch."""

    ink_width = NumericProperty(2.5)
    min_width = NumericProperty(1.0)
    max_width = NumericProperty(6.0)
    show_document_image = BooleanProperty(False)
    show_grid = BooleanProperty(False)
    view_role = StringProperty("pdf")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.strokes: List[StrokeRecord] = []
        self.current_stroke: List[Point] = []
        self._bg_rect: Optional[Rectangle] = None
        self._live_color: Rgba = COLOR_BLACK
        self._live_width: float = 2.5
        self._live_dashed: bool = False
        self._page_textures: List[Any] = []
        with self.canvas.before:
            Color(*LETTERBOX)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._on_geom, size=self._on_geom)
        app = App.get_running_app()
        if self.view_role == "notes":
            app.bind(
                notes_scale=self._on_view,
                notes_pan_x=self._on_view,
                view_pan_y=self._on_view,
                notes_page_width=self._on_view,
                page_width=self._on_view,
                page_height=self._on_view,
                page_count=self._on_view,
            )
        else:
            app.bind(
                view_scale=self._on_view,
                view_pan_x=self._on_view,
                view_pan_y=self._on_view,
                page_width=self._on_view,
                page_height=self._on_view,
                page_count=self._on_view,
            )
        self.bind(show_grid=self._on_view, show_document_image=self._on_view)
        Clock.schedule_once(lambda _dt: self.redraw_all(), 0)

    def _on_geom(self, *_args: Any) -> None:
        if self._bg_rect is not None:
            self._bg_rect.pos = self.pos
            self._bg_rect.size = self.size
        self.redraw_all()

    def _on_view(self, *_args: Any) -> None:
        self.redraw_all()

    def collide_point(self, x: float, y: float) -> bool:
        if self.disabled or self.opacity <= 0 or self.width <= 1 or self.height <= 1:
            return False
        return super().collide_point(x, y)

    def _scale_value(self) -> float:
        app = App.get_running_app()
        if self.view_role == "notes":
            return float(app.notes_scale)
        return float(app.view_scale)

    def _pan_value(self) -> Tuple[float, float]:
        app = App.get_running_app()
        if self.view_role == "notes":
            return float(app.notes_pan_x), float(app.view_pan_y)
        return float(app.view_pan_x), float(app.view_pan_y)

    def _set_scale(self, value: float) -> None:
        app = App.get_running_app()
        value = max(MIN_SCALE, min(MAX_SCALE, value))
        if self.view_role == "notes":
            app.notes_scale = value
        else:
            app.view_scale = value
        app.clamp_view(self)

    def _add_pan(self, dx: float, dy: float) -> None:
        app = App.get_running_app()
        if self.view_role == "notes":
            app.notes_pan_x += dx
        else:
            app.view_pan_x += dx
        app.view_pan_y += dy
        app.clamp_view(self)

    def _set_pan(self, pan_x: float, pan_y: float) -> None:
        app = App.get_running_app()
        if self.view_role == "notes":
            app.notes_pan_x = pan_x
        else:
            app.view_pan_x = pan_x
        app.view_pan_y = pan_y
        app.clamp_view(self)

    def set_page_images(self, paths: Sequence[str]) -> None:
        textures: List[Any] = []
        for path in paths:
            try:
                textures.append(CoreImage(path).texture)
            except Exception:
                continue
        self._page_textures = textures
        app = App.get_running_app()
        if textures:
            app.page_width = float(textures[0].size[0])
            app.page_height = float(textures[0].size[1])
            app.page_count = max(1, len(textures))
        self.redraw_all()

    def set_blank_notebook(self, count: int, width: float = 0.0, height: float = 0.0) -> None:
        self._page_textures = []
        app = App.get_running_app()
        app.page_count = max(1, int(count))
        if self.view_role == "notes" and width > 0:
            app.notes_page_width = max(1.0, float(width))
        elif width > 0 and height > 0:
            app.page_width = max(1.0, float(width))
            app.page_height = max(1.0, float(height))
        self.redraw_all()

    def _notebook_height(self, page_h: float) -> float:
        count = max(1, int(App.get_running_app().page_count))
        return count * page_h + (count - 1) * PAGE_GAP

    def _page_origin_y(self, index: int, page_h: float) -> float:
        count = max(1, int(App.get_running_app().page_count))
        return (count - 1 - index) * (page_h + PAGE_GAP)

    def _page_metrics(self) -> Tuple[float, float, float, float, float, float, float]:
        app = App.get_running_app()
        if self.view_role == "notes":
            page_w = max(1.0, float(app.notes_page_width))
        else:
            page_w = max(1.0, float(app.page_width))
        page_h = max(1.0, float(app.page_height))
        notebook_h = self._notebook_height(page_h)
        width, height = float(self.width), float(self.height)
        fit = width / page_w if page_w else 1.0
        scale = fit * self._scale_value()
        disp_w = page_w * scale
        disp_h = notebook_h * scale
        pan_x, pan_y = self._pan_value()
        origin_x = self.x + (width - disp_w) / 2.0 + pan_x
        origin_y = self.y + height - disp_h + pan_y
        return origin_x, origin_y, disp_w, disp_h, scale, page_w, page_h

    def to_doc(self, x: float, y: float) -> Point:
        origin_x, origin_y, _dw, _dh, scale, _pw, _ph = self._page_metrics()
        if scale <= 1e-6:
            return (0.0, 0.0)
        return ((x - origin_x) / scale, (y - origin_y) / scale)

    def _classify(self, touch: MotionEvent) -> str:
        if getattr(touch, "is_mouse_scrolling", False):
            return "wheel"
        app = App.get_running_app()
        pointers = getattr(app, "_pointers", {})
        if len(pointers) >= 1 and touch.uid not in pointers:
            return "finger"
        button = str(getattr(touch, "button", None) or "").lower()
        if button in {"right", "middle", "alt"} or getattr(app, "spen_button_held", False):
            return "eraser"
        return "stylus"

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
        count = max(1, int(App.get_running_app().page_count))
        self.canvas.clear()
        with self.canvas:
            StencilPush()
            Color(1, 1, 1, 1)
            Rectangle(pos=self.pos, size=self.size)
            StencilUse()
            PushMatrix()
            Translate(origin_x, origin_y)
            Scale(scale, scale, 1)
            for index in range(count):
                page_y = self._page_origin_y(index, page_h)
                Color(*PAGE_WHITE)
                Rectangle(pos=(0, page_y), size=(page_w, page_h))
                has_page_image = (
                    self.show_document_image
                    and index < len(self._page_textures)
                    and self._page_textures[index] is not None
                )
                if has_page_image:
                    Color(1, 1, 1, 1)
                    Rectangle(
                        texture=self._page_textures[index],
                        pos=(0, page_y),
                        size=(page_w, page_h),
                    )
                elif self.show_grid:
                    self._draw_grid(page_w, page_h, page_y)
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
            StencilUnUse()
            StencilPop()

    def _draw_grid(self, page_w: float, page_h: float, page_y: float) -> None:
        step = max(24.0, min(page_w, page_h) / 22.0)
        Color(*GRID_LINE)
        x = 0.0
        while x <= page_w + 0.5:
            Line(points=[x, page_y, x, page_y + page_h], width=1.0)
            x += step
        y = page_y
        top = page_y + page_h
        while y <= top + 0.5:
            Line(points=[0.0, y, page_w, y], width=1.0)
            y += step

    def _start_view_gesture(self, touch: MotionEvent) -> None:
        app = App.get_running_app()
        touch.grab(self)
        app._fingers[touch.uid] = (touch.x, touch.y)
        if len(app._fingers) >= 2:
            touch.ud["mode"] = "pinch"
            self._begin_pinch(app)
            return
        touch.ud["mode"] = "pan"
        touch.ud["last"] = (touch.x, touch.y)

    def _erase_at(self, x: float, y: float, radius: float) -> None:
        radius_sq = radius * radius
        eraser = (x, y)
        kept: List[StrokeRecord] = []
        changed = False
        for record in self.strokes:
            fragment: List[List[float]] = []
            pieces: List[List[List[float]]] = []
            points = record.get("points") or []
            previous: Optional[Sequence[float]] = None
            for point in points:
                hit = _dist2(point, eraser) <= radius_sq
                if not hit and previous is not None:
                    hit = _dist_point_seg2(eraser, previous, point) <= radius_sq
                previous = point
                if hit:
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
        app._pinch_scale = self._scale_value()
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
        self._set_scale(new_scale)
        doc_x, doc_y = app._pinch_doc
        _ox, _oy, _dw, _dh, scale, page_w, page_h = self._page_metrics()
        notebook_h = self._notebook_height(page_h)
        fit_x = self.x + (self.width - page_w * scale) / 2.0
        fit_y = self.y + self.height - notebook_h * scale
        self._set_pan(mid[0] - fit_x - doc_x * scale, mid[1] - fit_y - doc_y * scale)

    def _begin_two_finger_view(self, touch: MotionEvent) -> None:
        app = App.get_running_app()
        app._multitouch = True
        self.current_stroke = []
        self.redraw_all()
        app._fingers = dict(app._pointers)
        touch.ud["mode"] = "pinch"
        self._begin_pinch(app)

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        app = App.get_running_app()
        kind = self._classify(touch)
        if kind == "wheel":
            factor = 1.12 if touch.button == "scrollup" else 0.89
            self._set_scale(self._scale_value() * factor)
            return True
        touch.grab(self)
        app._pointers[touch.uid] = (touch.x, touch.y)
        if len(app._pointers) >= 2:
            self._begin_two_finger_view(touch)
            return True
        tool_mode = str(getattr(app, "tool_mode", "none"))
        doc = self.to_doc(touch.x, touch.y)
        if kind == "eraser" or tool_mode == "eraser" or bool(getattr(app, "is_eraser", False)):
            touch.ud["erasing"] = True
            _ox, _oy, _dw, _dh, scale, _pw, _ph = self._page_metrics()
            radius = max(SPEN_ERASER_WIDTH, 36.0) / max(scale, 0.01)
            self._erase_at(doc[0], doc[1], radius)
            return True
        if tool_mode == "none":
            self._start_view_gesture(touch)
            return True
        if tool_mode != "pen":
            self._start_view_gesture(touch)
            return True
        self._live_color = tuple(getattr(app, "current_color", COLOR_BLACK))
        self._live_width = self._line_width_for_touch(touch)
        self._live_dashed = bool(getattr(app, "is_dashed", False))
        self.current_stroke = [doc]
        return True

    def on_touch_move(self, touch: MotionEvent) -> bool:
        if touch.grab_current is not self:
            return super().on_touch_move(touch)
        app = App.get_running_app()
        if touch.uid in getattr(app, "_pointers", {}):
            app._pointers[touch.uid] = (touch.x, touch.y)
        if bool(getattr(app, "_multitouch", False)) or len(getattr(app, "_pointers", {})) >= 2:
            if len(app._pointers) >= 2:
                app._fingers = dict(app._pointers)
                self._update_pinch(app)
            return True
        mode = touch.ud.get("mode")
        if mode == "pan":
            last = touch.ud.get("last", (touch.x, touch.y))
            self._add_pan(touch.x - last[0], touch.y - last[1])
            touch.ud["last"] = (touch.x, touch.y)
            return True
        if touch.ud.get("erasing"):
            doc = self.to_doc(touch.x, touch.y)
            _ox, _oy, _dw, _dh, scale, _pw, _ph = self._page_metrics()
            radius = max(SPEN_ERASER_WIDTH, 36.0) / max(scale, 0.01)
            self._erase_at(doc[0], doc[1], radius)
            return True
        self.current_stroke.append(self.to_doc(touch.x, touch.y))
        self.redraw_all()
        return True

    def on_touch_up(self, touch: MotionEvent) -> bool:
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        app = App.get_running_app()
        app._pointers.pop(touch.uid, None)
        app._fingers.pop(touch.uid, None)
        if not app._pointers:
            app._multitouch = False
            app._fingers.clear()
        if bool(getattr(app, "_multitouch", False)):
            if len(app._pointers) >= 2:
                app._fingers = dict(app._pointers)
                self._begin_pinch(app)
            return True
        if touch.ud.get("mode") in {"pan", "pinch"}:
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


class RootLayout(FloatLayout):
    """Notebook workspace with a Samsung Notes-style overlay chrome."""

    notes_expanded = BooleanProperty(True)
    toolbar_visible = BooleanProperty(True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.pdf_canvas = SPenAnnotationCanvas(show_document_image=True, view_role="pdf")
        self.notes_canvas = SPenAnnotationCanvas(
            show_document_image=False, show_grid=True, view_role="notes"
        )
        self.side_panel = self.notes_canvas
        self.tool_buttons: Dict[str, Any] = {}
        self.color_dots: Dict[str, ColorDot] = {}
        self.workspace = FloatLayout()
        self.pdf_canvas.size_hint = (1, 1)
        self.notes_canvas.size_hint = (None, None)
        self.workspace.add_widget(self.pdf_canvas)
        self.workspace.add_widget(self.notes_canvas)
        self.chrome = BoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=dp(84),
            pos_hint={"x": 0, "top": 1},
            spacing=0,
        )
        self.chrome.add_widget(self._build_header())
        self.chrome.add_widget(self._build_toolbar())
        self.restore_btn = ToolIcon(
            "restore",
            on_dark=True,
            size_hint=(None, None),
            size=(dp(48), dp(32)),
            pos_hint={"center_x": 0.5, "top": 1},
        )
        self.restore_btn.opacity = 0
        self.restore_btn.disabled = True
        self.restore_btn.bind(on_release=self.show_toolbar)
        self.add_widget(self.workspace)
        self.add_widget(self.chrome)
        self.add_widget(self.restore_btn)
        self.refresh_tool_styles()
        self.bind(size=self._fit_workspace, pos=self._fit_workspace)
        Window.bind(size=lambda *_args: self.apply_orientation())
        Clock.schedule_once(lambda _dt: self.apply_orientation(), 0)

    def _fit_workspace(self, *_args: Any) -> None:
        self.workspace.size = self.size
        self.workspace.pos = self.pos
        self.pdf_canvas.size = self.size
        self.pdf_canvas.pos = self.pos
        self.dock_notes()

    def set_status(self, message: str) -> None:
        self.status_label.text = message

    def _build_header(self) -> BoxLayout:
        app = App.get_running_app()
        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            padding=(dp(8), 0, dp(12), 0),
            spacing=dp(4),
        )
        with header.canvas.before:
            Color(*HEADER_BG)
            self._header_bg = Rectangle()
        header.bind(
            pos=lambda *_args: setattr(self._header_bg, "pos", header.pos),
            size=lambda *_args: setattr(self._header_bg, "size", header.size),
        )
        for key, kind, handler in (
            ("open", "plus", app.open_pdf),
            ("save_as", "save", app.save_document_as),
            ("toggle", "notes", self.toggle_notes),
        ):
            button = ToolIcon(kind, on_dark=False, size=(dp(44), dp(36)))
            button.bind(on_release=handler)
            header.add_widget(button)
            self.tool_buttons[key] = button
        self.status_label = Label(
            text="",
            color=(0.35, 0.35, 0.38, 1),
            font_size=dp(13),
            halign="right",
            valign="middle",
        )
        set_hebrew_font(self.status_label)
        self.title_button = Button(
            text=f"{app.document_title}  >",
            color=(0.12, 0.12, 0.14, 1),
            font_size=dp(16),
            bold=True,
            size_hint_x=None,
            width=dp(160),
            background_normal="",
            background_down="",
            background_color=(1, 1, 1, 1),
            halign="right",
        )
        set_hebrew_font(self.title_button)
        self.title_button.bind(on_release=app.rename_document)
        header.add_widget(self.status_label)
        header.add_widget(self.title_button)
        return header

    def _build_toolbar(self) -> BoxLayout:
        app = App.get_running_app()
        toolbar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            padding=(dp(8), dp(4)),
            spacing=dp(2),
        )
        with toolbar.canvas.before:
            Color(*TOOLBAR_BG)
            self._toolbar_bg = Rectangle()
        toolbar.bind(
            pos=lambda *_args: setattr(self._toolbar_bg, "pos", toolbar.pos),
            size=lambda *_args: setattr(self._toolbar_bg, "size", toolbar.size),
        )
        actions: Sequence[Tuple[str, str, Any]] = (
            ("pan", "pan", app.clear_tool),
            ("pen", "pen", app.select_pen),
            ("dashed", "dashed", app.toggle_dashed),
            ("eraser", "eraser", app.enable_eraser),
        )
        for key, kind, handler in actions:
            button = ToolIcon(kind, on_dark=True)
            button.bind(on_press=handler)
            toolbar.add_widget(button)
            self.tool_buttons[key] = button
        for key, rgba in INK_COLORS:
            dot = ColorDot(rgba)
            dot.bind(on_release=lambda _dot, name=key: app.set_ink_color(name))
            toolbar.add_widget(dot)
            self.color_dots[key] = dot
        hide_btn = ToolIcon("hide", on_dark=True)
        hide_btn.bind(on_release=self.hide_toolbar)
        toolbar.add_widget(Widget())
        toolbar.add_widget(hide_btn)
        self.tool_buttons["hide"] = hide_btn
        return toolbar

    def hide_toolbar(self, *_args: Any) -> None:
        self.toolbar_visible = False
        self.chrome.opacity = 0
        self.chrome.disabled = True
        self.chrome.height = 0
        self.restore_btn.opacity = 1
        self.restore_btn.disabled = False

    def show_toolbar(self, *_args: Any) -> None:
        self.toolbar_visible = True
        self.chrome.opacity = 1
        self.chrome.disabled = False
        self.chrome.height = dp(84)
        self.restore_btn.opacity = 0
        self.restore_btn.disabled = True

    def refresh_tool_styles(self) -> None:
        app = App.get_running_app()
        pen_on = app.tool_mode == "pen"
        mapping = {
            "pan": app.tool_mode == "none",
            "pen": pen_on and not app.is_dashed,
            "dashed": pen_on and bool(app.is_dashed),
            "eraser": app.tool_mode == "eraser",
        }
        for key, button in self.tool_buttons.items():
            if key in {"open", "save_as", "toggle", "hide"}:
                continue
            if isinstance(button, ToolIcon):
                button.selected = mapping.get(key, False)
        for key, rgba in INK_COLORS:
            dot = self.color_dots.get(key)
            if dot is None:
                continue
            dot.selected = pen_on and tuple(app.current_color) == tuple(rgba)

    def apply_orientation(self, *_args: Any) -> None:
        self.pdf_canvas.size_hint = (1, 1)
        self.dock_notes()

    def dock_notes(self) -> None:
        self.notes_canvas.size_hint = (None, None)
        self.notes_canvas.height = self.height
        self.notes_canvas.y = self.y
        if not self.notes_expanded:
            self.notes_canvas.opacity = 0
            self.notes_canvas.disabled = True
            self.notes_canvas.width = 0
            self.notes_canvas.x = self.x - dp(4)
            return
        self.notes_canvas.opacity = 1
        self.notes_canvas.disabled = False
        width = min(dp(360), max(dp(170), self.width * 0.30))
        self.notes_canvas.width = width
        self.notes_canvas.x = self.x
        self.sync_notes_page_size()

    def sync_notes_page_size(self) -> None:
        app = App.get_running_app()
        pdf_w = max(1.0, float(self.pdf_canvas.width))
        notes_w = max(1.0, float(self.notes_canvas.width))
        width = max(1.0, notes_w * float(app.page_width) / pdf_w)
        if abs(float(app.notes_page_width) - width) > 0.5:
            app.notes_page_width = width

    def toggle_notes(self, *_args: Any) -> None:
        self.notes_expanded = not self.notes_expanded
        self.dock_notes()
        Clock.schedule_once(lambda _dt: App.get_running_app().clamp_view(), 0)

    def refresh_title(self) -> None:
        app = App.get_running_app()
        self.title_button.text = f"{app.document_title}  >"

    def set_page_status(self, index: int, count: int) -> None:
        if count <= 0:
            self.set_status("")
            return
        self.set_status(f"{count} עמודים")


class SamsungNotesCompanionApp(App):
    """Application state and entry point for the companion client."""

    view_scale = NumericProperty(1.0)
    view_pan_x = NumericProperty(0.0)
    view_pan_y = NumericProperty(0.0)
    notes_scale = NumericProperty(1.0)
    notes_pan_x = NumericProperty(0.0)
    notes_pan_y = NumericProperty(0.0)
    notes_page_width = NumericProperty(280.0)
    page_width = NumericProperty(800.0)
    page_height = NumericProperty(1100.0)
    page_count = NumericProperty(1)
    tool_type = NumericProperty(0)
    document_title = StringProperty("כותרת")

    def build(self) -> RootLayout:
        apply_ui_font()
        Window.clearcolor = LETTERBOX
        self.title = "Samsung Notes Companion"
        self.tool_mode: str = "none"
        self.current_color: Rgba = COLOR_BLACK
        self.is_eraser: bool = False
        self.is_dashed: bool = False
        self.spen_button_held: bool = False
        self.pointer_count = 1
        self.down_tool_type = 0
        self.down_source = 0
        self.input_source = 0
        self.has_finger_pointer = False
        self.pen_in_range = False
        self.hover_tool = 0
        self._fingers: Dict[Any, Tuple[float, float]] = {}
        self._pointers: Dict[Any, Tuple[float, float]] = {}
        self._multitouch = False
        self.pdf_path: Optional[str] = None
        self._pdf_local_path: Optional[str] = None
        self._pdf_page_index: int = 0
        self._pdf_page_count: int = 0
        self._page_strokes: Dict[int, List[StrokeRecord]] = {}
        self._notes_strokes: Dict[int, List[StrokeRecord]] = {}
        self._pending_save: Optional[Tuple[str, str]] = None
        self._stylus_listener: Any = None
        self.document_title = "כותרת"
        self.root_layout = RootLayout()
        Window.bind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)
        if is_android():
            self._setup_android()
        return self.root_layout

    def _file_stem(self) -> str:
        raw = (self.document_title or "כותרת").strip() or "כותרת"
        cleaned = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in raw)
        return cleaned.strip() or "כותרת"

    def _set_title_from_filename(self, name: str) -> None:
        base = str(name).replace("\\", "/").split("/")[-1].split(":")[-1]
        stem = Path(base).stem.strip() or "כותרת"
        self.document_title = stem
        self.root_layout.refresh_title()

    def clamp_view(self, canvas: Optional[SPenAnnotationCanvas] = None, *_args: Any) -> None:
        root = getattr(self, "root_layout", None)
        if root is None:
            return
        targets = [canvas] if isinstance(canvas, SPenAnnotationCanvas) else [
            root.pdf_canvas,
            root.notes_canvas,
        ]
        for item in targets:
            if item is None or item.width <= 1 or item.height <= 1:
                continue
            self._clamp_canvas(item)
        if root.pdf_canvas.width > 1:
            self._clamp_shared_y(root.pdf_canvas)
        if canvas is None:
            root.dock_notes()

    def _clamp_canvas(self, canvas: SPenAnnotationCanvas) -> None:
        _ox, _oy, disp_w, disp_h, _scale, _pw, _ph = canvas._page_metrics()
        board_x, board_y = float(canvas.x), float(canvas.y)
        board_w, board_h = float(canvas.width), float(canvas.height)
        base_x = canvas.x + (canvas.width - disp_w) / 2.0
        base_y = canvas.y + canvas.height - disp_h
        if disp_w <= board_w:
            min_x, max_x = board_x - base_x, board_x + board_w - disp_w - base_x
        else:
            min_x, max_x = board_x + board_w - disp_w - base_x, board_x - base_x
        if disp_h <= board_h:
            min_y, max_y = board_y - base_y, board_y + board_h - disp_h - base_y
        else:
            min_y, max_y = board_y + board_h - disp_h - base_y, board_y - base_y
        if min_x > max_x:
            min_x, max_x = max_x, min_x
        if min_y > max_y:
            min_y, max_y = max_y, min_y
        pan_x, pan_y = canvas._pan_value()
        if min_x > max_x:
            pan_x = (min_x + max_x) / 2.0
        else:
            pan_x = min(max(pan_x, min_x), max_x)
        if min_y > max_y:
            pan_y = (min_y + max_y) / 2.0
        else:
            pan_y = min(max(pan_y, min_y), max_y)
        if canvas.view_role == "notes":
            if abs(float(self.notes_pan_x) - pan_x) > 0.01:
                self.notes_pan_x = pan_x
            return
        if abs(float(self.view_pan_x) - pan_x) > 0.01:
            self.view_pan_x = pan_x
        if abs(float(self.view_pan_y) - pan_y) > 0.01:
            self.view_pan_y = pan_y

    def _clamp_shared_y(self, canvas: SPenAnnotationCanvas) -> None:
        _ox, _oy, _dw, disp_h, _scale, _pw, _ph = canvas._page_metrics()
        board_y = float(canvas.y)
        board_h = float(canvas.height)
        base_y = canvas.y + canvas.height - disp_h
        if disp_h <= board_h:
            min_y, max_y = board_y - base_y, board_y + board_h - disp_h - base_y
        else:
            min_y, max_y = board_y + board_h - disp_h - base_y, board_y - base_y
        if min_y > max_y:
            min_y, max_y = max_y, min_y
        if min_y > max_y:
            pan_y = (min_y + max_y) / 2.0
        else:
            pan_y = min(max(float(self.view_pan_y), min_y), max_y)
        if abs(float(self.view_pan_y) - pan_y) > 0.01:
            self.view_pan_y = pan_y

    def rename_document(self, *_args: Any) -> None:
        field = TextInput(
            text=self.document_title,
            multiline=False,
            font_size=dp(18),
            size_hint_y=None,
            height=dp(44),
        )
        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        buttons = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = Popup(title="שם המסמך", content=body, size_hint=(0.8, 0.4))

        def _save(_btn: Button) -> None:
            name = field.text.strip() or "כותרת"
            self.document_title = name
            self.root_layout.refresh_title()
            popup.dismiss()

        save_btn = Button(text="שמירה")
        cancel_btn = Button(text="ביטול")
        save_btn.bind(on_release=_save)
        cancel_btn.bind(on_release=lambda _btn: popup.dismiss())
        buttons.add_widget(save_btn)
        buttons.add_widget(cancel_btn)
        body.add_widget(Label(text="בחרו שם למסמך", size_hint_y=None, height=dp(28)))
        body.add_widget(field)
        body.add_widget(buttons)
        popup.open()

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
        action_down = 0
        action_pointer_down = 5
        try:
            state = int(event.getButtonState())
            action = int(event.getActionMasked())
            index = int(event.getActionIndex())
            count = int(event.getPointerCount())
            tool = int(event.getToolType(index))
            source = int(event.getSource())
            tools = [int(event.getToolType(i)) for i in range(count)]
        except Exception:
            return
        stylus_bits = 0x02 | 0x20 | 0x40
        self.spen_button_held = bool(state & stylus_bits) or tool == TOOL_ERASER
        if action in HOVER_ACTIONS:
            self.pen_in_range = tool in (TOOL_STYLUS, TOOL_ERASER) or bool(
                source & 0x4002
            )
            self.hover_tool = tool
            return
        self.pointer_count = count
        self.has_finger_pointer = TOOL_FINGER in tools
        if action in UP_ACTIONS:
            if count <= 1:
                self.down_tool_type = 0
                self.down_source = 0
                self.tool_type = 0
                self.has_finger_pointer = False
            return
        self.tool_type = tool
        if action in (action_down, action_pointer_down):
            self.down_tool_type = tool
            self.down_source = source

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
                ]

                @java_method("(Landroid/view/View;Landroid/view/MotionEvent;)Z")
                def onGenericMotion(self, _view, event):
                    app._update_spen_from_motion(event)
                    return False

                @java_method("(Landroid/view/View;Landroid/view/MotionEvent;)Z")
                def onHover(self, _view, event):
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
            scale = 2.0
            width = max(1, int(round(float(page.getWidth()) * scale)))
            height = max(1, int(round(float(page.getHeight()) * scale)))
            bitmap_cls = autoclass("android.graphics.Bitmap")
            config = autoclass("android.graphics.Bitmap$Config")
            bitmap = bitmap_cls.createBitmap(width, height, config.ARGB_8888)
            bitmap.eraseColor(-1)
            clip = autoclass("android.graphics.Rect")(0, 0, width, height)
            # Null transform lets PdfRenderer fit the page into the bitmap.
            # An extra Matrix scale on an already-sized bitmap crops the form
            # to a white corner.
            try:
                page.render(bitmap, clip, None, 1)
            except Exception:
                matrix = autoclass("android.graphics.Matrix")()
                page.render(bitmap, clip, matrix, 1)
            page.close()
            renderer.close()
            pfd.close()
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            handle.close()
            stream = autoclass("java.io.FileOutputStream")(handle.name)
            fmt = autoclass("android.graphics.Bitmap$CompressFormat")
            bitmap.compress(fmt.JPEG, 95, stream)
            stream.close()
            try:
                bitmap.recycle()
            except Exception:
                pass
            self._overlay_acroform_fields(handle.name, int(index))
            return handle.name
        except Exception:
            return None

    def _remember_pdf_file(self, path: Optional[str]) -> None:
        self._pdf_local_path = path if path and os.path.isfile(path) else None

    def _overlay_acroform_fields(self, image_path: str, index: int) -> None:
        pdf_path = self._pdf_local_path or (
            self.pdf_path if self.pdf_path and os.path.isfile(self.pdf_path) else None
        )
        if not pdf_path:
            return
        try:
            from PIL import Image, ImageDraw, ImageFont
            from pypdf import PdfReader
        except Exception:
            return
        try:
            reader = PdfReader(pdf_path)
            if getattr(reader, "is_encrypted", False):
                try:
                    reader.decrypt("")
                except Exception:
                    pass
            if index >= len(reader.pages):
                return
            page = reader.pages[index]
            box = page.mediabox
            pdf_w = max(1.0, float(box.width))
            pdf_h = max(1.0, float(box.height))
            image = Image.open(image_path).convert("RGB")
            scale_x = image.size[0] / pdf_w
            scale_y = image.size[1] / pdf_h
            drawer = ImageDraw.Draw(image)
            font_path = resolve_hebrew_font() or resolve_latin_font()
            annots = page.get("/Annots") or []
            for annot_ref in annots:
                try:
                    annot = annot_ref.get_object()
                except Exception:
                    continue
                if str(annot.get("/Subtype", "")) != "/Widget":
                    continue
                value = annot.get("/V")
                if value is None:
                    value = annot.get("/DV")
                text = str(value or "").replace("/", "").strip()
                if not text or text.lower() in {"off", "none", "null"}:
                    continue
                rect = [float(item) for item in (annot.get("/Rect") or [])]
                if len(rect) != 4:
                    continue
                left = min(rect[0], rect[2]) * scale_x
                right = max(rect[0], rect[2]) * scale_x
                top = image.size[1] - max(rect[1], rect[3]) * scale_y
                bottom = image.size[1] - min(rect[1], rect[3]) * scale_y
                box_h = max(8.0, bottom - top)
                font = None
                if font_path:
                    try:
                        font = ImageFont.truetype(font_path, max(10, int(box_h * 0.55)))
                    except Exception:
                        font = None
                drawer.text((left + 2, top + 1), text, fill=(20, 20, 20), font=font)
            image.save(image_path, format="JPEG", quality=95)
        except Exception:
            return

    def _stacked_to_pages(
        self, strokes: Sequence[StrokeRecord]
    ) -> Dict[int, List[StrokeRecord]]:
        count = max(1, int(self.page_count or self._pdf_page_count or 1))
        page_h = max(1.0, float(self.page_height))
        span = page_h + PAGE_GAP
        pages: Dict[int, List[StrokeRecord]] = {index: [] for index in range(count)}
        for record in strokes:
            points = record.get("points") or []
            if not points:
                continue
            from_bottom = int(float(points[0][1]) // span)
            from_bottom = max(0, min(count - 1, from_bottom))
            page = count - 1 - from_bottom
            origin_y = from_bottom * span
            clone = dict(record)
            clone["points"] = [
                [float(point[0]), float(point[1]) - origin_y] for point in points
            ]
            pages.setdefault(page, []).append(clone)
        return pages

    def _pages_to_stacked(
        self, pages: Dict[int, List[StrokeRecord]]
    ) -> List[StrokeRecord]:
        count = max(1, int(self.page_count or self._pdf_page_count or 1))
        page_h = max(1.0, float(self.page_height))
        stacked: List[StrokeRecord] = []
        for index, records in pages.items():
            origin_y = (count - 1 - int(index)) * (page_h + PAGE_GAP)
            for record in records:
                clone = dict(record)
                clone["points"] = [
                    [float(point[0]), float(point[1]) + origin_y]
                    for point in (record.get("points") or [])
                ]
                stacked.append(clone)
        return stacked

    def _stash_current_page_strokes(self) -> None:
        self._page_strokes = self._stacked_to_pages(
            self.root_layout.pdf_canvas.serialized_strokes()
        )
        self._notes_strokes = self._stacked_to_pages(
            self.root_layout.notes_canvas.serialized_strokes()
        )

    def _reset_view(self) -> None:
        self.view_scale = 1.0
        self.view_pan_x = 0.0
        self.view_pan_y = 0.0
        self.notes_scale = 1.0
        self.notes_pan_x = 0.0
        self.notes_pan_y = 0.0
        Clock.schedule_once(lambda _dt: self.clamp_view(), 0)

    def _load_notebook(self, uri: Any = None) -> None:
        if self._pdf_page_count <= 0:
            return
        self.page_count = int(self._pdf_page_count)
        paths: List[str] = []
        for index in range(self._pdf_page_count):
            preview = self._render_pdf_page(index, uri)
            if preview:
                paths.append(preview)
        if paths:
            self.root_layout.pdf_canvas.set_page_images(paths)
        else:
            self.root_layout.pdf_canvas.set_blank_notebook(
                self._pdf_page_count, self.page_width, self.page_height
            )
        self.root_layout.notes_canvas.set_blank_notebook(self._pdf_page_count)
        self.root_layout.sync_notes_page_size()
        self.root_layout.pdf_canvas.load_strokes(
            self._pages_to_stacked(self._page_strokes)
        )
        self.root_layout.notes_canvas.load_strokes(
            self._pages_to_stacked(self._notes_strokes)
        )
        Clock.schedule_once(lambda _dt: self.root_layout.sync_notes_page_size(), 0)
        self.root_layout.set_page_status(0, self._pdf_page_count)

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
                try:
                    self._remember_pdf_file(self._copy_uri_to_temp(uri, ".pdf"))
                except Exception:
                    self._pdf_local_path = None
                self._page_strokes = {}
                self._notes_strokes = {}
                self._pdf_page_index = 0
                self._reset_view()
                self._pdf_page_count = self._pdf_page_count_from(uri)
                self.root_layout.pdf_canvas.load_strokes([])
                self.root_layout.notes_canvas.load_strokes([])
                self._load_notebook(uri)
                self._set_title_from_filename(display)
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
            "document_title": self.document_title,
            "notes_page_width": float(self.notes_page_width),
        }

    def _draw_notes_grid_pil(self, image: Any) -> None:
        from PIL import ImageDraw

        drawer = ImageDraw.Draw(image)
        width, height = image.size
        step = max(12, min(width, height) // 22)
        color = (199, 214, 235)
        x = 0
        while x <= width:
            drawer.line([(x, 0), (x, height)], fill=color, width=1)
            x += step
        y = 0
        while y <= height:
            drawer.line([(0, y), (width, y)], fill=color, width=1)
            y += step

    def _stroke_on_image(
        self,
        image: Any,
        strokes: Sequence[StrokeRecord],
        page_w: float = 0.0,
        page_h: float = 0.0,
    ) -> None:
        from PIL import ImageDraw

        drawer = ImageDraw.Draw(image)
        width, height = image.size
        scale_x = width / page_w if page_w > 1 else 1.0
        scale_y = height / page_h if page_h > 1 else 1.0
        for record in strokes:
            points = record.get("points") or []
            if len(points) < 2:
                continue
            color = record.get("color", COLOR_BLACK)
            fill = tuple(max(0, min(255, int(c * 255))) for c in color[:3])
            stroke_w = max(1, int(record.get("width", 2) * max(scale_x, scale_y)))
            xy = [
                (float(p[0]) * scale_x, height - float(p[1]) * scale_y) for p in points
            ]
            if record.get("dashed"):
                dashes = dashed_polylines(points)
                for dash in dashes:
                    pair = [
                        (dash[i] * scale_x, height - dash[i + 1] * scale_y)
                        for i in range(0, len(dash) - 1, 2)
                    ]
                    if len(pair) >= 2:
                        drawer.line(pair, fill=fill, width=stroke_w)
            else:
                drawer.line(xy, fill=fill, width=stroke_w)

    def _texture_to_rgb(self, texture: Any) -> Optional[Any]:
        from PIL import Image

        try:
            image = Image.frombytes("RGBA", tuple(texture.size), bytes(texture.pixels))
            image = image.transpose(Image.FLIP_TOP_BOTTOM)
            return _image_rgb_on_white(image)
        except Exception:
            return None

    def _export_document_page(self, index: int) -> Optional[Any]:
        textures = getattr(self.root_layout.pdf_canvas, "_page_textures", [])
        if 0 <= index < len(textures) and textures[index] is not None:
            converted = self._texture_to_rgb(textures[index])
            if converted is not None:
                return converted
        if self.pdf_path and is_android():
            preview = self._render_pdf_page(index)
            if preview:
                return _image_rgb_on_white(preview)
        return None

    def _render_export_pngs(self) -> List[Tuple[bytes, int, int]]:
        from PIL import Image

        self._stash_current_page_strokes()
        pages: List[Tuple[bytes, int, int]] = []
        count = max(1, int(self._pdf_page_count) or 1)
        for index in range(count):
            background = self._export_document_page(index)
            if background is None:
                background = Image.new(
                    "RGB",
                    (int(self.page_width), int(self.page_height)),
                    (255, 255, 255),
                )
            self._stroke_on_image(
                background,
                self._page_strokes.get(index, []),
                float(self.page_width),
                float(self.page_height),
            )
            notes_h = int(max(1, self.page_height))
            notes_w = int(max(1, round(float(self.notes_page_width))))
            notes_native = Image.new("RGB", (notes_w, notes_h), (255, 255, 255))
            self._draw_notes_grid_pil(notes_native)
            self._stroke_on_image(
                notes_native,
                self._notes_strokes.get(index, []),
                float(notes_w),
                float(notes_h),
            )
            export_notes_h = background.size[1]
            export_notes_w = max(1, int(round(notes_w * export_notes_h / max(notes_h, 1))))
            notes = notes_native.resize((export_notes_w, export_notes_h), Image.LANCZOS)
            combined = Image.new(
                "RGB",
                (notes.size[0] + background.size[0], background.size[1]),
                (255, 255, 255),
            )
            combined.paste(notes, (0, 0))
            combined.paste(background, (notes.size[0], 0))
            buffer = io.BytesIO()
            combined.save(
                buffer, format="JPEG", quality=92, optimize=False, progressive=False
            )
            pages.append((buffer.getvalue(), combined.size[0], combined.size[1]))
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
        self._pdf_page_index = int(payload.get("pdf_page_index") or 0)
        self._pdf_page_count = int(payload.get("pdf_page_count") or 1)
        self.page_count = max(1, self._pdf_page_count)
        self._page_strokes = {
            int(key): value for key, value in (payload.get("pdf_pages") or {}).items()
        }
        self._notes_strokes = {
            int(key): value for key, value in (payload.get("notes_pages") or {}).items()
        }
        pdf_strokes = self._pages_to_stacked(self._page_strokes) or (
            payload.get("pdf_canvas") or []
        )
        notes_strokes = self._pages_to_stacked(self._notes_strokes) or (
            payload.get("notes_canvas") or []
        )
        self.root_layout.notes_canvas.set_blank_notebook(self.page_count)
        self.root_layout.sync_notes_page_size()
        if payload.get("document_title"):
            self.document_title = str(payload.get("document_title"))
            self.root_layout.refresh_title()
        self.root_layout.pdf_canvas.load_strokes(pdf_strokes)
        self.root_layout.notes_canvas.load_strokes(notes_strokes)
        self.root_layout.set_page_status(0, self.page_count)

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
                self._remember_pdf_file(handle.name)
                if is_android():
                    self._pdf_page_count = self._pdf_page_count_from()
                    self._load_notebook()

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
        intent.putExtra(Intent.EXTRA_TITLE, String(f"{self._file_stem()}{extension}"))
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
            self._remember_pdf_file(path)
            self._page_strokes = {}
            self._notes_strokes = {}
            self._pdf_page_index = 0
            self._reset_view()
            if is_android():
                try:
                    self._pdf_page_count = self._pdf_page_count_from()
                    self.root_layout.pdf_canvas.load_strokes([])
                    self.root_layout.notes_canvas.load_strokes([])
                    self._load_notebook()
                    self._set_title_from_filename(path)
                    self._notify(f"PDF נפתח לכתיבה: {os.path.basename(path)}")
                    return
                except Exception as exc:
                    self._notify(f"לא ניתן להציג את ה-PDF: {exc}")
                    return
            self._set_title_from_filename(path)
            self._notify(f"נבחר PDF: {os.path.basename(path)}")
            return
        if lower.endswith((".notes", ".json", ".sdocx")):
            self._load_notes_file(path)
            self._notify(f"נפתח: {os.path.basename(path)}")
            return
        self._notify("סוג הקובץ אינו נתמך")

    def _desktop_save_dialog(self, default_ext: str = ".pdf") -> None:
        chooser = FileChooserListView(path=self._desktop_start_dir())
        name_input = TextInput(
            text=f"{self._file_stem()}{default_ext}",
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
            return ".pdf", "application/pdf"

        def _on_type(_spinner: Spinner, value: str) -> None:
            ext, _mime = _ext_for_label(value)
            stem = Path(name_input.text).stem or self._file_stem()
            name_input.text = f"{stem}{ext}"

        spinner.bind(text=_on_type)

        def _save(_instance: Button) -> None:
            ext, _mime = _ext_for_label(spinner.text)
            directory = chooser.path
            if chooser.selection and os.path.isdir(chooser.selection[0]):
                directory = chooser.selection[0]
            filename = name_input.text.strip() or f"{self._file_stem()}{ext}"
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

    def save_document_as(self, *_args: Any) -> None:
        if not is_android():
            self._desktop_save_dialog(".pdf")
            return

        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        popup = Popup(title="Save As", content=body, size_hint=(0.75, 0.7))
        set_latin_font(popup)
        for ext, mime, title in SAVE_TYPES:
            button = Button(text=title, size_hint_y=None, height=dp(44))
            set_latin_font(button)

            def _pick(_btn: Button, extension: str = ext, media: str = mime) -> None:
                popup.dismiss()
                self._start_android_save(extension, media)

            button.bind(on_release=_pick)
            body.add_widget(button)
        popup.open()

    def clear_tool(self, *_args: Any) -> None:
        self.tool_mode = "none"
        self.is_eraser = False
        self.root_layout.refresh_tool_styles()

    def select_pen(self, *_args: Any) -> None:
        if self.tool_mode == "pen" and not self.is_dashed:
            self.clear_tool()
            return
        self.tool_mode = "pen"
        self.is_eraser = False
        self.is_dashed = False
        self.root_layout.refresh_tool_styles()

    def set_ink_color(self, name: str, *_args: Any) -> None:
        color_map = dict(INK_COLORS)
        color = color_map.get(name, COLOR_BLACK)
        if self.tool_mode == "pen" and tuple(self.current_color) == tuple(color):
            self.clear_tool()
            return
        self.current_color = color
        self.tool_mode = "pen"
        self.is_eraser = False
        self.root_layout.refresh_tool_styles()

    def set_color_black(self, *_args: Any) -> None:
        self.set_ink_color("black")

    def set_color_red(self, *_args: Any) -> None:
        self.set_ink_color("red")

    def set_color_blue(self, *_args: Any) -> None:
        self.set_ink_color("blue")

    def toggle_dashed(self, *_args: Any) -> None:
        if self.tool_mode == "pen" and self.is_dashed:
            self.clear_tool()
            return
        self.is_dashed = True
        self.tool_mode = "pen"
        self.is_eraser = False
        self.root_layout.refresh_tool_styles()

    def enable_eraser(self, *_args: Any) -> None:
        if self.tool_mode == "eraser":
            self.clear_tool()
            return
        self.tool_mode = "eraser"
        self.is_eraser = True
        self.root_layout.refresh_tool_styles()


if __name__ == "__main__":
    SamsungNotesCompanionApp().run()
