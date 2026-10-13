"""Samsung Notes companion: toolbar, split canvases, and S Pen ink."""

from __future__ import annotations

import copy
import io
import json
import math
import os
import tempfile
import unicodedata

os.environ["SDL_ANDROID_SEPARATE_MOUSE_AND_TOUCH"] = "1"
os.environ["SDL_TOUCH_MOUSE_EVENTS"] = "0"
os.environ["SDL_MOUSE_TOUCH_EVENTS"] = "0"
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.graphics.texture import Texture
from kivy.graphics import (
    Color,
    Ellipse,
    Line,
    PopMatrix,
    PushMatrix,
    Rectangle,
    Rotate,
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
from kivy.uix.slider import Slider
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
PDF_RENDER_SCALE = 2.0
PDF_RENDER_MAX_SIDE = 2048.0
PDF_PREVIEW_SCALE = 1.0
PDF_PREVIEW_MAX_SIDE = 900.0
MAX_GPU_PAGES = 5
PAGE_GAP = 28.0
DASH_LENGTH = 18.0
GAP_LENGTH = 12.0
UNDO_LIMIT = 40
HANDLE_SIZE = 16.0
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
SHAPE_TOOLS = frozenset(
    {
        "line",
        "square",
        "rectangle",
        "circle",
        "ellipse",
        "triangle",
        "diamond",
        "pentagon",
        "hexagon",
        "star",
        "arrow",
        "heart",
    }
)
SHAPE_ORDER: Sequence[str] = (
    "line",
    "square",
    "rectangle",
    "circle",
    "ellipse",
    "triangle",
    "diamond",
    "pentagon",
    "hexagon",
    "star",
    "arrow",
    "heart",
)
CHROME_HEIGHT_DP = 136.0
SHAPE_BAR_DP = 40.0
PASTE_HOLD_S = 1.0
HOVER_ACTIONS = {7, 9, 10}
UP_ACTIONS = {1, 6}

OPEN_REQUEST = 4101
SAVE_REQUEST = 4102
IMAGE_REQUEST = 4103
SPEN_KEYCODES = {110, 139, 188, 189, 308, 309}

SAVE_TYPES: Sequence[Tuple[str, str, str]] = (
    (".pdf", "application/pdf", "PDF (*.pdf)"),
    (".sdocx", "application/octet-stream", "Samsung Notes (*.sdocx)"),
    (".json", "application/json", "JSON (*.json)"),
    (".png", "image/png", "PNG image (*.png)"),
)


def is_android() -> bool:
    return platform == "android"


def _is_hover_touch(touch: MotionEvent) -> bool:
    try:
        pressure = float(getattr(touch, "pressure", 1.0) or 0.0)
    except (TypeError, ValueError):
        pressure = 1.0
    if pressure > 0.02:
        return False
    try:
        action = int(getattr(touch, "action", 0) or 0)
    except (TypeError, ValueError):
        action = 0
    if action in HOVER_ACTIONS:
        return True
    return bool(getattr(touch, "is_hovering", False))


def _first_existing(paths: Sequence[str]) -> Optional[str]:
    for path in paths:
        if os.path.isfile(path):
            return path
    return None


_HEBREW_FONT_READY = False
_LATIN_FONT_READY = False


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
    # Explicit files only: scanning /system/fonts and opening Noto/Emoji TTFs
    # with FreeType can native-crash on Android at launch.
    return _first_existing(
        (
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
            "/system/fonts/NotoSansHebrew-Regular.ttf",
            "/system/fonts/DroidSansHebrew.ttf",
            "/system/fonts/NotoSerifHebrew-Regular.ttf",
            "/system/fonts/SamsungOneUI-Regular.ttf",
            "/system/fonts/SamsungOne-400.ttf",
            "/system/fonts/SamsungSans-Regular.ttf",
        )
    )


def apply_ui_font() -> None:
    global _HEBREW_FONT_READY, _LATIN_FONT_READY
    latin = resolve_latin_font()
    hebrew = resolve_hebrew_font()
    try:
        if latin:
            LabelBase.register(name="LatinFont", fn_regular=latin)
            _LATIN_FONT_READY = True
    except Exception:
        _LATIN_FONT_READY = False
    try:
        if hebrew:
            LabelBase.register(name="HebrewFont", fn_regular=hebrew)
            _HEBREW_FONT_READY = True
        elif _LATIN_FONT_READY:
            LabelBase.register(name="HebrewFont", fn_regular=latin)
            _HEBREW_FONT_READY = True
    except Exception:
        _HEBREW_FONT_READY = False


def ui_text(text: str) -> str:
    """Reorder Hebrew for Kivy's LTR renderer so letters read right-to-left."""
    try:
        return _ui_text_body(text)
    except Exception:
        return text


def _strip_bidi_marks(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _strip_markup_tags(text: str) -> str:
    out: List[str] = []
    index = 0
    while index < len(text):
        if text[index] == "[":
            close = text.find("]", index)
            if close != -1:
                index = close + 1
                continue
        out.append(text[index])
        index += 1
    return (
        "".join(out)
        .replace("&bl;", "[")
        .replace("&br;", "]")
        .replace("&amp;", "&")
    )


def _plain_user_text(text: str) -> str:
    cleaned = _strip_markup_tags(_strip_bidi_marks(str(text or "")))
    lowered = cleaned.lower()
    if not cleaned.strip():
        return ""
    if cleaned.startswith("<") or "jnius" in lowered or "javaobject" in lowered or "nativeproxy" in lowered:
        return ""
    return cleaned.strip()


def _java_chars(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        from jnius import autoclass

        converted = autoclass("java.lang.String").valueOf(value)
        return converted if isinstance(converted, str) else str(converted)
    except Exception:
        try:
            return str(value.toString())
        except Exception:
            return ""


def _has_hebrew(text: str) -> bool:
    return any("\u0590" <= ch <= "\u05FF" for ch in text)


def _ui_text_body(text: str) -> str:
    text = _strip_bidi_marks(text)
    if not text or not _has_hebrew(text):
        return text
    chunks: List[str] = []
    buf: List[str] = []
    mode: Optional[bool] = None

    def flush() -> None:
        if not buf or mode is None:
            return
        block = "".join(buf)
        chunks.append(block[::-1] if mode else block)
        buf.clear()

    for ch in text:
        bid = unicodedata.bidirectional(ch)
        if bid in {"R", "AL", "RLE", "RLO"}:
            rtl = True
        elif bid in {"L", "LRE", "LRO", "EN", "AN", "ET", "ES"}:
            rtl = False
        else:
            rtl = True if mode is None else mode
        if mode is None:
            mode = rtl
        elif rtl != mode:
            flush()
            mode = rtl
        buf.append(ch)
    flush()
    chunks.reverse()
    return "".join(chunks)


def set_latin_font(widget: Any) -> None:
    if not _LATIN_FONT_READY:
        return
    try:
        widget.font_name = "LatinFont"
    except Exception:
        pass


def set_hebrew_font(widget: Any) -> None:
    if not _HEBREW_FONT_READY:
        return
    try:
        widget.font_name = "HebrewFont"
    except Exception:
        pass


def apply_hebrew_ui(root: Any, title: Optional[str] = None) -> None:
    """Enable mixed Hebrew/Latin markup on popups, labels, and buttons."""
    if title is not None and hasattr(root, "title"):
        try:
            root.title = mixed_markup(title)
        except Exception:
            pass

    def _apply(_dt: float = 0.0) -> None:
        try:
            widgets = list(root.walk()) if hasattr(root, "walk") else [root]
        except Exception:
            widgets = [root]
        for widget in widgets:
            try:
                if isinstance(widget, TextInput):
                    if _LATIN_FONT_READY:
                        widget.font_name = "LatinFont"
                    continue
                if "filechooser" in type(widget).__module__:
                    continue
                if isinstance(widget, (Label, Button)):
                    widget.markup = True
                    text = str(getattr(widget, "text", "") or "")
                    if text and "[font=" not in text:
                        widget.text = mixed_markup(text)
            except Exception:
                continue

    Clock.schedule_once(_apply, 0)
    Clock.schedule_once(_apply, 0.05)


def focus_system_keyboard(field: TextInput) -> None:
    """Focus a TextInput without fighting an already-open Android IME."""

    def _focus(_dt: float = 0.0) -> None:
        try:
            field.disabled = False
            field.readonly = False
            field.focus = True
        except Exception:
            pass

    Clock.schedule_once(_focus, 0.05)


def mixed_markup(text: str) -> str:
    """Visual Hebrew order, with Latin/digit runs on LatinFont so they are not tofu."""
    visual = ui_text(text)
    if not visual:
        return ""
    parts: List[str] = []
    buf: List[str] = []
    hebrew_run: Optional[bool] = None

    def _escape(chunk: str) -> str:
        return chunk.replace("&", "&amp;").replace("[", "&bl;").replace("]", "&br;")

    def flush() -> None:
        if not buf or hebrew_run is None:
            return
        chunk = _escape("".join(buf))
        if hebrew_run and _HEBREW_FONT_READY:
            parts.append(f"[font=HebrewFont]{chunk}[/font]")
        elif (not hebrew_run) and _LATIN_FONT_READY:
            parts.append(f"[font=LatinFont]{chunk}[/font]")
        else:
            parts.append(chunk)
        buf.clear()

    for ch in visual:
        is_he = "\u0590" <= ch <= "\u05FF"
        is_latin = ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ch.isdigit()
        if ch.isspace() or not (is_he or is_latin):
            # Hebrew-only TTFs often lack U+0020; keep spaces on LatinFont.
            if hebrew_run is True:
                flush()
            hebrew_run = False
            buf.append(ch)
            continue
        if hebrew_run is None:
            hebrew_run = is_he
        elif is_he != hebrew_run:
            flush()
            hebrew_run = is_he
        buf.append(ch)
    flush()
    return "".join(parts)


def _script_runs(text: str) -> List[Tuple[str, Optional[str]]]:
    """Split visual text into Hebrew/Latin runs without markup tags."""
    visual = ui_text(_plain_user_text(text))
    if not visual:
        return []
    runs: List[Tuple[str, Optional[str]]] = []
    buf: List[str] = []
    hebrew_run: Optional[bool] = None

    def flush() -> None:
        if not buf or hebrew_run is None:
            return
        chunk = "".join(buf)
        font: Optional[str] = None
        if hebrew_run and _HEBREW_FONT_READY:
            font = "HebrewFont"
        elif (not hebrew_run) and _LATIN_FONT_READY:
            font = "LatinFont"
        runs.append((chunk, font))
        buf.clear()

    for ch in visual:
        is_he = "\u0590" <= ch <= "\u05FF"
        is_latin = ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ch.isdigit()
        if ch.isspace() or not (is_he or is_latin):
            if hebrew_run is True:
                flush()
            hebrew_run = False
            buf.append(ch)
            continue
        if hebrew_run is None:
            hebrew_run = is_he
        elif is_he != hebrew_run:
            flush()
            hebrew_run = is_he
        buf.append(ch)
    flush()
    return runs


def hsv_to_rgb(hue: float, sat: float, val: float) -> Rgba:
    h = (float(hue) % 1.0) * 6.0
    s = max(0.0, min(1.0, float(sat)))
    v = max(0.0, min(1.0, float(val)))
    chroma = v * s
    x = chroma * (1.0 - abs(h % 2.0 - 1.0))
    m = v - chroma
    idx = int(h)
    if idx == 0:
        r, g, b = chroma, x, 0.0
    elif idx == 1:
        r, g, b = x, chroma, 0.0
    elif idx == 2:
        r, g, b = 0.0, chroma, x
    elif idx == 3:
        r, g, b = 0.0, x, chroma
    elif idx == 4:
        r, g, b = x, 0.0, chroma
    else:
        r, g, b = chroma, 0.0, x
    return (r + m, g + m, b + m, 1.0)


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


def _rotate_point(px: float, py: float, cx: float, cy: float, angle_deg: float) -> Point:
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dx, dy = px - cx, py - cy
    return (cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a)


def _stamp_tex_coords(crop: Sequence[float]) -> List[float]:
    """Map crop UVs so PIL-uploaded textures are not shown upside-down."""
    u0, v0, u1, v1 = [float(v) for v in list(crop)[:4]]
    return [u0, 1.0 - v0, u1, 1.0 - v0, u1, 1.0 - v1, u0, 1.0 - v1]


def _image_rgb_on_white(source: Any) -> Any:
    from PIL import Image, ImageOps

    image = Image.open(source) if isinstance(source, (str, Path)) else source
    try:
        image = ImageOps.exif_transpose(image) or image
    except Exception:
        pass
    if image.mode == "RGB":
        return image
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.split()[3])
    return background


def shape_points(kind: str, start: Point, end: Point) -> List[Point]:
    x0, y0 = float(start[0]), float(start[1])
    x1, y1 = float(end[0]), float(end[1])
    if kind == "line":
        return [(x0, y0), (x1, y1)]
    if kind == "square":
        side = min(abs(x1 - x0), abs(y1 - y0))
        if side < 1.0:
            return [(x0, y0), (x1, y1)]
        x1 = x0 + math.copysign(side, x1 - x0 or 1.0)
        y1 = y0 + math.copysign(side, y1 - y0 or 1.0)
    left, right = (x0, x1) if x0 <= x1 else (x1, x0)
    bottom, top = (y0, y1) if y0 <= y1 else (y1, y0)
    if kind in {"square", "rectangle"}:
        return [
            (left, bottom),
            (right, bottom),
            (right, top),
            (left, top),
            (left, bottom),
        ]
    cx = (left + right) / 2.0
    cy = (bottom + top) / 2.0
    rx = max(1.0, (right - left) / 2.0)
    ry = max(1.0, (top - bottom) / 2.0)
    if kind in {"circle", "ellipse"}:
        steps = 64 if kind == "circle" else 48
        return [
            (cx + rx * math.cos(i * 2.0 * math.pi / steps), cy + ry * math.sin(i * 2.0 * math.pi / steps))
            for i in range(steps + 1)
        ]
    if kind == "triangle":
        return [(cx, top), (left, bottom), (right, bottom), (cx, top)]
    if kind == "diamond":
        return [(cx, top), (right, cy), (cx, bottom), (left, cy), (cx, top)]
    if kind == "pentagon":
        points = [
            (
                cx + rx * math.cos(math.pi / 2.0 + i * 2.0 * math.pi / 5.0),
                cy + ry * math.sin(math.pi / 2.0 + i * 2.0 * math.pi / 5.0),
            )
            for i in range(5)
        ]
        points.append(points[0])
        return points
    if kind == "hexagon":
        points = [
            (cx + rx * math.cos(i * math.pi / 3.0), cy + ry * math.sin(i * math.pi / 3.0))
            for i in range(6)
        ]
        points.append(points[0])
        return points
    if kind == "arrow":
        dx, dy = x1 - x0, y1 - y0
        length = max(1.0, math.hypot(dx, dy))
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        head = min(max(18.0, length * 0.22), length * 0.45)
        wing = head * 0.55
        return [
            (x0, y0),
            (x1, y1),
            (x1 - ux * head + px * wing, y1 - uy * head + py * wing),
            (x1, y1),
            (x1 - ux * head - px * wing, y1 - uy * head - py * wing),
        ]
    if kind == "heart":
        points = []
        for index in range(49):
            t = index * 2.0 * math.pi / 48.0
            hx = 16.0 * math.sin(t) ** 3
            hy = (
                13.0 * math.cos(t)
                - 5.0 * math.cos(2.0 * t)
                - 2.0 * math.cos(3.0 * t)
                - math.cos(4.0 * t)
            )
            points.append((cx + rx * hx / 16.0, cy + ry * hy / 16.0))
        return points
    if kind == "star":
        outer = min(rx, ry)
        inner = outer * 0.42
        points = []
        for index in range(10):
            angle = math.pi / 2.0 + index * math.pi / 5.0
            radius = outer if index % 2 == 0 else inner
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        points.append(points[0])
        return points
    return [(x0, y0), (x1, y1)]


def _pil_to_texture(image: Any) -> Any:
    rgba = image.convert("RGBA")
    texture = Texture.create(size=rgba.size, colorfmt="rgba")
    texture.blit_buffer(rgba.tobytes(), colorfmt="rgba", bufferfmt="ubyte")
    texture.flip_vertical()
    texture.wrap = "clamp_to_edge"
    texture.mag_filter = "linear"
    texture.min_filter = "linear"
    return texture


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
        self.trigger = kwargs.pop("trigger", None)
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(48), dp(44)))
        super().__init__(**kwargs)
        self.kind = kind
        with self.canvas.before:
            self._bg_color = Color(0, 0, 0, 1)
            self._bg_rect = Rectangle()
        self.bind(
            pos=self._redraw,
            size=self._redraw,
            selected=self._sync_bg,
            on_dark=self._redraw,
        )
        Clock.schedule_once(lambda _dt: self._redraw(), 0)

    def collide_point(self, x: float, y: float) -> bool:
        pad = dp(3)
        return self.x - pad <= x <= self.right + pad and self.y - pad <= y <= self.top + pad

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if self.disabled or self.opacity <= 0:
            return False
        if _is_hover_touch(touch):
            return False
        if not self.collide_point(*touch.pos):
            return False
        touch.grab(self)
        trigger = getattr(self, "trigger", None)
        if callable(trigger):
            trigger(self)
        return True

    def on_touch_up(self, touch: MotionEvent) -> bool:
        if touch.grab_current is self:
            touch.ungrab(self)
            return True
        return super().on_touch_up(touch)

    def _sync_bg(self, *_args: Any) -> None:
        bg = TOOL_ACTIVE if self.selected else (TOOL_IDLE if self.on_dark else (1, 1, 1, 1))
        self._bg_color.rgba = bg
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size

    def _redraw(self, *_args: Any) -> None:
        self._sync_bg()
        self.canvas.clear()
        pad = dp(7)
        x, y = self.x + pad, self.y + pad
        w, h = self.width - 2 * pad, self.height - 2 * pad
        cx, cy = self.center_x, self.center_y
        ink = (1, 1, 1, 1) if self.on_dark else (0.15, 0.15, 0.17, 1)
        with self.canvas:
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
            elif kind == "line":
                Line(points=[x + w * 0.08, y + h * 0.18, x + w * 0.92, y + h * 0.82], width=1.4)
            elif kind == "square":
                side = min(w, h) * 0.7
                Line(rectangle=(cx - side / 2.0, cy - side / 2.0, side, side), width=1.3)
            elif kind == "rectangle":
                Line(rectangle=(x + w * 0.08, y + h * 0.22, w * 0.84, h * 0.56), width=1.3)
            elif kind == "circle":
                Line(circle=(cx, cy, min(w, h) * 0.34), width=1.3)
            elif kind == "ellipse":
                oval: List[float] = []
                rx, ry = w * 0.42, h * 0.28
                for index in range(25):
                    angle = index * 2.0 * math.pi / 24.0
                    oval.extend([cx + rx * math.cos(angle), cy + ry * math.sin(angle)])
                Line(points=oval, width=1.3)
            elif kind == "triangle":
                Line(
                    points=[cx, y + h * 0.82, x + w * 0.12, y + h * 0.16, x + w * 0.88, y + h * 0.16, cx, y + h * 0.82],
                    width=1.3,
                )
            elif kind == "diamond":
                Line(points=[cx, y + h * 0.88, x + w * 0.92, cy, cx, y + h * 0.12, x + w * 0.08, cy, cx, y + h * 0.88], width=1.3)
            elif kind == "pentagon":
                pent: List[float] = []
                for index in range(6):
                    angle = math.pi / 2.0 + index * 2.0 * math.pi / 5.0
                    pent.extend([cx + min(w, h) * 0.38 * math.cos(angle), cy + min(w, h) * 0.38 * math.sin(angle)])
                Line(points=pent, width=1.2)
            elif kind == "hexagon":
                hexp: List[float] = []
                for index in range(7):
                    angle = index * math.pi / 3.0
                    hexp.extend([cx + min(w, h) * 0.36 * math.cos(angle), cy + min(w, h) * 0.36 * math.sin(angle)])
                Line(points=hexp, width=1.2)
            elif kind == "arrow":
                Line(points=[x + w * 0.08, y + h * 0.22, x + w * 0.92, y + h * 0.78], width=1.4)
                Line(
                    points=[
                        x + w * 0.62,
                        y + h * 0.82,
                        x + w * 0.92,
                        y + h * 0.78,
                        x + w * 0.78,
                        y + h * 0.48,
                    ],
                    width=1.3,
                )
            elif kind == "heart":
                Line(
                    points=[
                        cx,
                        y + h * 0.12,
                        x + w * 0.08,
                        y + h * 0.48,
                        x + w * 0.18,
                        y + h * 0.82,
                        cx,
                        y + h * 0.58,
                        x + w * 0.82,
                        y + h * 0.82,
                        x + w * 0.92,
                        y + h * 0.48,
                        cx,
                        y + h * 0.12,
                    ],
                    width=1.2,
                )
            elif kind == "text":
                Line(points=[x + w * 0.18, y + h * 0.82, x + w * 0.82, y + h * 0.82], width=1.4)
                Line(points=[cx, y + h * 0.82, cx, y + h * 0.22], width=1.4)
                tex = self._caption_texture("א", ink)
                if tex is not None:
                    tw, th = float(tex.size[0]), float(tex.size[1])
                    scale = min(w * 0.42 / max(1.0, tw), h * 0.32 / max(1.0, th))
                    Color(*ink)
                    Rectangle(
                        texture=tex,
                        pos=(x + w * 0.58, y + h * 0.04),
                        size=(tw * scale, th * scale),
                    )
            elif kind == "star":
                outer = min(w, h) * 0.38
                inner = outer * 0.42
                star: List[float] = []
                for index in range(10):
                    angle = math.pi / 2.0 + index * math.pi / 5.0
                    radius = outer if index % 2 == 0 else inner
                    star.extend([cx + radius * math.cos(angle), cy + radius * math.sin(angle)])
                star.extend(star[:2])
                Line(points=star, width=1.2)
            elif kind == "image":
                Line(rectangle=(x + w * 0.08, y + h * 0.18, w * 0.84, h * 0.64), width=1.3)
                Line(circle=(x + w * 0.3, y + h * 0.62, min(w, h) * 0.08), width=1.2)
                Line(
                    points=[
                        x + w * 0.12,
                        y + h * 0.22,
                        x + w * 0.42,
                        y + h * 0.48,
                        x + w * 0.62,
                        y + h * 0.34,
                        x + w * 0.88,
                        y + h * 0.58,
                    ],
                    width=1.2,
                )
            elif kind == "fit":
                mx, my = x + w * 0.38, y + h * 0.58
                radius = min(w, h) * 0.26
                Line(circle=(mx, my, radius), width=1.3)
                Line(
                    points=[
                        mx + radius * 0.62,
                        my - radius * 0.62,
                        x + w * 0.92,
                        y + h * 0.08,
                    ],
                    width=1.5,
                )
                tex = self._caption_texture("100%", ink)
                if tex is not None:
                    tw, th = float(tex.size[0]), float(tex.size[1])
                    scale = min(w * 0.72 / max(1.0, tw), h * 0.34 / max(1.0, th))
                    Color(*ink)
                    Rectangle(
                        texture=tex,
                        pos=(cx - tw * scale / 2.0, y + h * 0.02),
                        size=(tw * scale, th * scale),
                    )
            elif kind == "palette":
                Line(circle=(cx, cy, min(w, h) * 0.34), width=1.3)
                Line(circle=(cx, cy, min(w, h) * 0.16), width=1.2)
            elif kind == "shapes":
                Line(rectangle=(x + w * 0.08, y + h * 0.12, w * 0.42, h * 0.42), width=1.2)
                Line(circle=(x + w * 0.72, y + h * 0.32, min(w, h) * 0.16), width=1.2)
                Line(
                    points=[cx, y + h * 0.92, x + w * 0.18, y + h * 0.52, x + w * 0.82, y + h * 0.52, cx, y + h * 0.92],
                    width=1.2,
                )
            elif kind == "lasso":
                box_x, box_y, box_w, box_h = x + w * 0.04, y + h * 0.28, w * 0.62, h * 0.58
                dash = max(3.0, box_w / 9.0)
                for edge in (
                    (box_x, box_y + box_h, box_x + box_w, box_y + box_h),
                    (box_x + box_w, box_y + box_h, box_x + box_w, box_y),
                    (box_x + box_w, box_y, box_x, box_y),
                    (box_x, box_y, box_x, box_y + box_h),
                ):
                    x0, y0, x1, y1 = edge
                    length = max(1.0, math.hypot(x1 - x0, y1 - y0))
                    ux, uy = (x1 - x0) / length, (y1 - y0) / length
                    t = 0.0
                    drawing = True
                    while t < length:
                        nxt = min(length, t + dash)
                        if drawing:
                            Line(
                                points=[x0 + ux * t, y0 + uy * t, x0 + ux * nxt, y0 + uy * nxt],
                                width=1.15,
                            )
                        drawing = not drawing
                        t = nxt
                hx, hy = x + w * 0.78, y + h * 0.22
                Line(circle=(hx, hy + h * 0.16, min(w, h) * 0.07), width=1.15)
                Line(rectangle=(hx - w * 0.08, hy, w * 0.16, h * 0.18), width=1.15)
                Line(points=[hx - w * 0.08, hy + h * 0.08, hx - w * 0.18, hy + h * 0.18], width=1.1)
            elif kind == "undo":
                self._horseshoe(cx, cy, min(w, h) * 0.34, True)
            elif kind == "redo":
                self._horseshoe(cx, cy, min(w, h) * 0.34, False)
            elif kind == "copy":
                Line(rectangle=(x + w * 0.08, y + h * 0.22, w * 0.58, h * 0.62), width=1.2)
                Line(rectangle=(x + w * 0.32, y + h * 0.08, w * 0.58, h * 0.62), width=1.2)
            elif kind == "cut":
                Line(points=[x + w * 0.18, y + h * 0.18, x + w * 0.82, y + h * 0.82], width=1.3)
                Line(points=[x + w * 0.18, y + h * 0.82, x + w * 0.82, y + h * 0.18], width=1.3)
                Line(circle=(x + w * 0.22, y + h * 0.22, min(w, h) * 0.12), width=1.15)
                Line(circle=(x + w * 0.22, y + h * 0.78, min(w, h) * 0.12), width=1.15)
            elif kind == "trash":
                Line(rectangle=(x + w * 0.22, y + h * 0.12, w * 0.56, h * 0.58), width=1.2)
                Line(points=[x + w * 0.16, y + h * 0.72, x + w * 0.84, y + h * 0.72], width=1.3)
                Line(rectangle=(x + w * 0.38, y + h * 0.78, w * 0.24, h * 0.12), width=1.15)
            elif kind == "paste":
                Line(rectangle=(x + w * 0.18, y + h * 0.08, w * 0.64, h * 0.72), width=1.2)
                Line(rectangle=(x + w * 0.32, y + h * 0.68, w * 0.36, h * 0.22), width=1.2)

    def _horseshoe(self, cx: float, cy: float, radius: float, undo: bool) -> None:
        points: List[float] = []
        start = math.radians(40.0 if undo else 140.0)
        sweep = math.radians(230.0)
        direction = 1.0 if undo else -1.0
        steps = 18
        for index in range(steps + 1):
            angle = start + direction * sweep * index / steps
            points.extend([cx + radius * math.cos(angle), cy + radius * math.sin(angle)])
        Line(points=points, width=1.45)
        end_angle = start + direction * sweep
        ex = cx + radius * math.cos(end_angle)
        ey = cy + radius * math.sin(end_angle)
        tangent = end_angle + (math.pi / 2.0 if undo else -math.pi / 2.0)
        head = radius * 0.55
        wing = radius * 0.32
        tx, ty = math.cos(tangent), math.sin(tangent)
        px, py = -ty, tx
        Triangle(
            points=[
                ex + tx * head * 0.15,
                ey + ty * head * 0.15,
                ex - tx * head + px * wing,
                ey - ty * head + py * wing,
                ex - tx * head - px * wing,
                ey - ty * head - py * wing,
            ]
        )

    def _caption_texture(self, text: str, color: Sequence[float]) -> Any:
        key = (text, tuple(color), int(self.width), int(self.height))
        cached = getattr(self, "_caption_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        try:
            from kivy.core.text import Label as CoreLabel

            kwargs: Dict[str, Any] = {
                "text": text,
                "font_size": 11,
                "color": tuple(color),
                "bold": True,
            }
            if _LATIN_FONT_READY:
                kwargs["font_name"] = "LatinFont"
            label = CoreLabel(**kwargs)
            label.refresh()
            texture = label.texture
        except Exception:
            texture = None
        self._caption_cache = (key, texture)
        return texture


class AbsorbLayout(BoxLayout):
    """Toolbar container that keeps touches from falling through to the canvas."""

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if self.disabled or self.opacity <= 0 or not self.collide_point(*touch.pos):
            return False
        if _is_hover_touch(touch):
            return True
        super().on_touch_down(touch)
        return True

    def on_touch_move(self, touch: MotionEvent) -> bool:
        if self.disabled or self.opacity <= 0:
            return False
        if self.collide_point(*touch.pos) or touch.grab_current is not None:
            super().on_touch_move(touch)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch: MotionEvent) -> bool:
        if self.disabled or self.opacity <= 0:
            return False
        if self.collide_point(*touch.pos) or touch.grab_current is not None:
            super().on_touch_up(touch)
            return True
        return super().on_touch_up(touch)


class FloatingChip(ButtonBehavior, BoxLayout):
    """On-canvas copy/paste control with a large hit target."""

    def __init__(self, kind: str, caption: str, **kwargs: Any) -> None:
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(118), dp(44)))
        kwargs.setdefault("padding", (dp(6), dp(4)))
        kwargs.setdefault("spacing", dp(4))
        super().__init__(**kwargs)
        with self.canvas.before:
            self._bg = Color(0.12, 0.12, 0.14, 0.94)
            self._rect = Rectangle()
        self.icon = ToolIcon(kind, on_dark=True, size=(dp(36), dp(32)))
        self.label = Label(
            text=mixed_markup(caption),
            markup=True,
            color=(1, 1, 1, 1),
            font_size=dp(14),
            halign="center",
            valign="middle",
        )
        self.add_widget(self.icon)
        self.add_widget(self.label)
        self.bind(pos=self._sync, size=self._sync)
        Clock.schedule_once(lambda _dt: self._sync(), 0)

    def _sync(self, *_args: Any) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size
        self.label.text_size = (self.label.width, self.label.height)

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if self.disabled or self.opacity <= 0:
            return False
        if _is_hover_touch(touch):
            return False
        if not self.collide_point(*touch.pos):
            return False
        self.dispatch("on_release")
        return True


class SelectionBar(BoxLayout):
    """Icon-only copy / cut / delete bar above a lasso selection."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(136), dp(44)))
        kwargs.setdefault("spacing", dp(2))
        kwargs.setdefault("padding", (dp(4), dp(4)))
        super().__init__(**kwargs)
        with self.canvas.before:
            self._bg = Color(0.12, 0.12, 0.14, 0.94)
            self._rect = Rectangle()
        self.bind(pos=self._sync, size=self._sync)
        app = App.get_running_app()
        for kind, handler in (
            ("copy", app.copy_selection),
            ("cut", app.cut_selection),
            ("trash", app.delete_selection),
        ):
            self.add_widget(ToolIcon(kind, on_dark=True, size=(dp(40), dp(36)), trigger=handler))
        Clock.schedule_once(lambda _dt: self._sync(), 0)

    def _sync(self, *_args: Any) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if self.disabled or self.opacity <= 0:
            return False
        if _is_hover_touch(touch):
            return False
        if not self.collide_point(*touch.pos):
            return False
        super().on_touch_down(touch)
        return True


class ColorDot(ButtonBehavior, Widget):
    """Round ink swatch; a white ring marks the selected color."""

    rgba = ListProperty([0.0, 0.0, 0.0, 1.0])
    selected = BooleanProperty(False)

    def __init__(self, rgba: Rgba, **kwargs: Any) -> None:
        self.trigger = kwargs.pop("trigger", None)
        super().__init__(**kwargs)
        self.rgba = list(rgba)
        self.size_hint = (None, None)
        self.size = (dp(36), dp(36))
        with self.canvas:
            self._fill = Color(*self.rgba)
            self._dot = Ellipse()
            self._ring = Color(1, 1, 1, 0)
            self._ring_line = Line(width=1.4)
        self.bind(pos=self._sync, size=self._sync, selected=self._sync, rgba=self._sync)
        Clock.schedule_once(lambda _dt: self._sync(), 0)

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if self.disabled or self.opacity <= 0:
            return False
        if _is_hover_touch(touch):
            return False
        if not self.collide_point(*touch.pos):
            return False
        trigger = getattr(self, "trigger", None)
        if callable(trigger):
            trigger(self)
            return True
        return super().on_touch_down(touch)

    def _sync(self, *_args: Any) -> None:
        pad = dp(5)
        self._fill.rgba = self.rgba
        self._dot.pos = (self.x + pad, self.y + pad)
        self._dot.size = (self.width - 2 * pad, self.height - 2 * pad)
        cx, cy = self.center_x, self.center_y
        radius = min(self.width, self.height) / 2.0 - dp(2)
        self._ring.a = 1.0 if self.selected else 0.0
        self._ring_line.circle = (cx, cy, radius)


class InkColorPicker(BoxLayout):
    """Hue bar + saturation/value square for an exact ink color."""

    hue = NumericProperty(0.0)
    sat = NumericProperty(1.0)
    val = NumericProperty(1.0)

    def __init__(self, rgb: Sequence[float], **kwargs: Any) -> None:
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", dp(8))
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(220))
        super().__init__(**kwargs)
        self.hue, self.sat, self.val = self._rgb_to_hsv(rgb)
        row = BoxLayout(orientation="horizontal", spacing=dp(8))
        self.sv = Widget()
        self.hue_bar = Widget(size_hint_x=None, width=dp(28))
        self.preview = Widget(size_hint_y=None, height=dp(28))
        row.add_widget(self.sv)
        row.add_widget(self.hue_bar)
        self.add_widget(row)
        self.add_widget(self.preview)
        self.sv.bind(pos=self._paint, size=self._paint)
        self.hue_bar.bind(pos=self._paint, size=self._paint)
        self.bind(hue=self._paint, sat=self._paint, val=self._paint)
        Clock.schedule_once(lambda _dt: self._paint(), 0)

    def rgb(self) -> Rgba:
        return hsv_to_rgb(self.hue, self.sat, self.val)

    def _rgb_to_hsv(self, rgb: Sequence[float]) -> Tuple[float, float, float]:
        r, g, b = [max(0.0, min(1.0, float(c))) for c in list(rgb)[:3]]
        mx, mn = max(r, g, b), min(r, g, b)
        df = mx - mn
        if df < 1e-6:
            hue = 0.0
        elif mx == r:
            hue = ((g - b) / df) % 6.0 / 6.0
        elif mx == g:
            hue = (((b - r) / df) + 2.0) / 6.0
        else:
            hue = (((r - g) / df) + 4.0) / 6.0
        sat = 0.0 if mx < 1e-6 else df / mx
        return (hue, sat, mx)

    def _sv_texture(self) -> Any:
        size = 96
        pixels = bytearray()
        for row in range(size):
            val = 1.0 - row / float(size - 1)
            for col in range(size):
                sat = col / float(size - 1)
                r, g, b, _a = hsv_to_rgb(self.hue, sat, val)
                pixels.extend(
                    (int(r * 255), int(g * 255), int(b * 255), 255)
                )
        texture = Texture.create(size=(size, size), colorfmt="rgba")
        texture.blit_buffer(bytes(pixels), colorfmt="rgba", bufferfmt="ubyte")
        texture.flip_vertical()
        return texture

    def _hue_texture(self) -> Any:
        height = 96
        pixels = bytearray()
        for row in range(height):
            hue = 1.0 - row / float(height - 1)
            r, g, b, _a = hsv_to_rgb(hue, 1.0, 1.0)
            for _col in range(8):
                pixels.extend((int(r * 255), int(g * 255), int(b * 255), 255))
        texture = Texture.create(size=(8, height), colorfmt="rgba")
        texture.blit_buffer(bytes(pixels), colorfmt="rgba", bufferfmt="ubyte")
        texture.flip_vertical()
        return texture

    def _paint(self, *_args: Any) -> None:
        rgb = self.rgb()
        self.sv.canvas.clear()
        with self.sv.canvas:
            Color(1, 1, 1, 1)
            Rectangle(texture=self._sv_texture(), pos=self.sv.pos, size=self.sv.size)
            Color(1, 1, 1, 1)
            mark_x = self.sv.x + self.sat * max(1.0, self.sv.width)
            mark_y = self.sv.y + self.val * max(1.0, self.sv.height)
            Line(circle=(mark_x, mark_y, dp(5)), width=1.2)
            Color(0, 0, 0, 1)
            Line(circle=(mark_x, mark_y, dp(6)), width=0.8)
        self.hue_bar.canvas.clear()
        with self.hue_bar.canvas:
            Color(1, 1, 1, 1)
            Rectangle(texture=self._hue_texture(), pos=self.hue_bar.pos, size=self.hue_bar.size)
            Color(1, 1, 1, 1)
            hy = self.hue_bar.y + self.hue * max(1.0, self.hue_bar.height)
            Line(
                points=[self.hue_bar.x, hy, self.hue_bar.right, hy],
                width=1.4,
            )
        self.preview.canvas.clear()
        with self.preview.canvas:
            Color(*rgb)
            Rectangle(pos=self.preview.pos, size=self.preview.size)

    def on_touch_down(self, touch: MotionEvent) -> bool:
        return self._handle_touch(touch) or super().on_touch_down(touch)

    def on_touch_move(self, touch: MotionEvent) -> bool:
        return self._handle_touch(touch) or super().on_touch_move(touch)

    def _handle_touch(self, touch: MotionEvent) -> bool:
        if self.hue_bar.collide_point(*touch.pos):
            self.hue = max(0.0, min(1.0, (touch.y - self.hue_bar.y) / max(1.0, self.hue_bar.height)))
            return True
        if self.sv.collide_point(*touch.pos):
            self.sat = max(0.0, min(1.0, (touch.x - self.sv.x) / max(1.0, self.sv.width)))
            self.val = max(0.0, min(1.0, (touch.y - self.sv.y) / max(1.0, self.sv.height)))
            return True
        return False


class SliderGlyph(Widget):
    """Tiny legend next to a slider: width, opacity, or dash gap."""

    kind = StringProperty("width")
    amount = NumericProperty(1.0)

    def __init__(self, kind: str, **kwargs: Any) -> None:
        kwargs.setdefault("size_hint", (None, None))
        kwargs.setdefault("size", (dp(28), dp(28)))
        super().__init__(**kwargs)
        self.kind = kind
        self.bind(pos=self._redraw, size=self._redraw, amount=self._redraw, kind=self._redraw)
        Clock.schedule_once(lambda _dt: self._redraw(), 0)

    def _redraw(self, *_args: Any) -> None:
        self.canvas.clear()
        cx, cy = self.center_x, self.center_y
        with self.canvas:
            Color(1, 1, 1, 1)
            kind = self.kind
            if kind == "width":
                thick = max(1.2, min(8.0, float(self.amount) * 0.45))
                Line(points=[self.x + dp(3), cy, self.right - dp(3), cy], width=thick)
            elif kind == "opacity":
                Color(1, 1, 1, max(0.15, min(1.0, float(self.amount))))
                Ellipse(pos=(cx - dp(8), cy - dp(8)), size=(dp(16), dp(16)))
                Color(1, 1, 1, 1)
                Line(circle=(cx, cy, dp(8)), width=1.1)
            else:
                gap = max(4.0, float(self.amount) * 0.35)
                x = self.x + dp(3)
                right = self.right - dp(3)
                while x < right:
                    end = min(right, x + dp(6))
                    Line(points=[x, cy, end, cy], width=1.3)
                    x = end + gap


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
        self._image_rects: Dict[int, Rectangle] = {}
        self._tx: Optional[Translate] = None
        self._sc: Optional[Scale] = None
        self._clip_rect: Optional[Rectangle] = None
        self._live_color_instr: Optional[Color] = None
        self._live_line: Optional[Line] = None
        self._grid_tex: Any = None
        self._grid_tex_key: Optional[Tuple[int, int]] = None
        self._queued_vis: Optional[Tuple[int, int]] = None
        self._stamp_textures: Dict[str, Any] = {}
        self._page_num_textures: Dict[int, Any] = {}
        self._text_textures: Dict[Tuple[Any, ...], Any] = {}
        self.selected_ids: List[int] = []
        self._undo_stack: List[List[StrokeRecord]] = []
        self._redo_stack: List[List[StrokeRecord]] = []
        self._paste_clock: Any = None
        self._gesture_snapshot = False
        with self.canvas.before:
            Color(*LETTERBOX)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._on_geom, size=self._on_geom)
        app = App.get_running_app()
        if self.view_role == "notes":
            app.bind(
                notes_scale=self._apply_transform,
                notes_pan_x=self._apply_transform,
                view_pan_y=self._apply_transform,
                notes_page_width=self.redraw_all,
                page_width=self.redraw_all,
                page_height=self.redraw_all,
                page_count=self.redraw_all,
            )
        else:
            app.bind(
                view_scale=self._apply_transform,
                view_pan_x=self._apply_transform,
                view_pan_y=self._apply_transform,
                page_width=self.redraw_all,
                page_height=self.redraw_all,
                page_count=self.redraw_all,
            )
        self.bind(show_grid=self.redraw_all, show_document_image=self.redraw_all)
        Clock.schedule_once(lambda _dt: self.redraw_all(), 0)

    def _on_geom(self, *_args: Any) -> None:
        if self._bg_rect is not None:
            self._bg_rect.pos = self.pos
            self._bg_rect.size = self.size
        if self._clip_rect is not None:
            self._clip_rect.pos = self.pos
            self._clip_rect.size = self.size
        self._apply_transform()

    def _apply_transform(self, *_args: Any) -> None:
        if self._tx is None or self._sc is None:
            self.redraw_all()
            return
        origin_x, origin_y, _dw, _dh, scale, _pw, _ph = self._page_metrics()
        self._tx.x = origin_x
        self._tx.y = origin_y
        try:
            self._sc.xyz = (scale, scale, 1.0)
        except Exception:
            self._sc.x = scale
            self._sc.y = scale
        if self.view_role != "pdf":
            return
        app = App.get_running_app()
        vis = self._visible_pages()
        if vis != self._queued_vis:
            self._queued_vis = vis
            if hasattr(app, "request_visible_pages"):
                app.request_visible_pages()

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
        from PIL import Image

        textures: List[Any] = []
        for path in paths:
            try:
                textures.append(_pil_to_texture(_image_rgb_on_white(Image.open(path))))
            except Exception:
                continue
        self._page_textures = textures
        app = App.get_running_app()
        if textures:
            app.page_width = float(textures[0].size[0])
            app.page_height = float(textures[0].size[1])
            app.page_count = max(1, len(textures))
        self.redraw_all()

    def set_page_image_at(self, index: int, path: str, total: int) -> None:
        from PIL import Image

        total = max(1, int(total))
        while len(self._page_textures) < total:
            self._page_textures.append(None)
        try:
            texture = _pil_to_texture(_image_rgb_on_white(Image.open(path)))
        except Exception:
            return
        self._page_textures[index] = texture
        app = App.get_running_app()
        if int(app.page_count) != total:
            app.page_count = total
        rect = self._image_rects.get(index)
        if rect is not None:
            rect.texture = texture
        else:
            self.redraw_all()

    def set_blank_notebook(self, count: int, width: float = 0.0, height: float = 0.0) -> None:
        self._page_textures = [None] * max(1, int(count))
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

    def from_doc(self, x: float, y: float) -> Point:
        origin_x, origin_y, _dw, _dh, scale, _pw, _ph = self._page_metrics()
        return (origin_x + x * scale, origin_y + y * scale)

    def _cancel_paste_hold(self) -> None:
        clock = getattr(self, "_paste_clock", None)
        if clock is not None:
            clock.cancel()
            self._paste_clock = None

    def _arm_paste_hold(self, touch: MotionEvent) -> None:
        app = App.get_running_app()
        if not getattr(app, "_clipboard", None):
            return
        self._cancel_paste_hold()
        touch.ud["hold_origin"] = (touch.x, touch.y)

        def _fire(_dt: float) -> None:
            self._paste_clock = None
            if touch.ud.get("mode") in {"resize", "crop", "rotate", "endpoint", "move", "pinch"}:
                return
            layout = getattr(app, "root_layout", None)
            touch.ud["paste_hold"] = True
            if layout is not None:
                layout.show_paste_chip(self, touch.x, touch.y)

        self._paste_clock = Clock.schedule_once(_fire, PASTE_HOLD_S)

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
        app = App.get_running_app()
        return max(1.0, float(getattr(app, "ink_width", self.ink_width)))

    def _should_erase(self, touch: MotionEvent) -> bool:
        app = App.get_running_app()
        if getattr(touch, "button", None) == "right":
            return True
        if bool(getattr(app, "spen_button_held", False)):
            return True
        if bool(getattr(app, "is_eraser", False)):
            return True
        return int(getattr(app, "tool_type", 0) or 0) == TOOL_ERASER

    def _visible_pages(self) -> Tuple[int, int]:
        app = App.get_running_app()
        count = max(1, int(app.page_count))
        _ox, origin_y, _dw, _dh, scale, _pw, page_h = self._page_metrics()
        if scale <= 1e-6 or self.height <= 1:
            return (0, min(count - 1, 1))
        doc_bottom = (self.y - origin_y) / scale
        doc_top = (self.y + self.height - origin_y) / scale
        if doc_bottom > doc_top:
            doc_bottom, doc_top = doc_top, doc_bottom
        pad = page_h
        first = last = None
        for index in range(count):
            y0 = self._page_origin_y(index, page_h)
            y1 = y0 + page_h
            if y1 >= doc_bottom - pad and y0 <= doc_top + pad:
                if first is None:
                    first = index
                last = index
        if first is None or last is None:
            return (0, 0)
        if last - first > MAX_GPU_PAGES - 1:
            mid = (doc_bottom + doc_top) / 2.0
            best = first
            best_dist = 1e12
            for index in range(first, last + 1):
                center = self._page_origin_y(index, page_h) + page_h / 2.0
                dist = abs(center - mid)
                if dist < best_dist:
                    best_dist = dist
                    best = index
            first = max(first, best - 2)
            last = min(last, best + 2)
        return (first, last)

    def evict_page_textures(self, keep: Sequence[int]) -> None:
        keep_set = set(keep)
        loaded = [index for index, tex in enumerate(self._page_textures) if tex is not None]
        if len(loaded) <= MAX_GPU_PAGES:
            return
        for index in loaded:
            if index in keep_set:
                continue
            self._page_textures[index] = None

    def _stamp_texture(self, path: str) -> Optional[Any]:
        cached = self._stamp_textures.get(path)
        if cached is not None:
            return cached
        try:
            from PIL import Image

            texture = _pil_to_texture(_image_rgb_on_white(Image.open(path)))
        except Exception:
            return None
        self._stamp_textures[path] = texture
        return texture

    def _text_texture(self, record: StrokeRecord) -> Optional[Any]:
        text = str(record.get("text") or "")
        font_size = max(10.0, float(record.get("font_size") or 28.0))
        color = tuple(record.get("color") or COLOR_BLACK)
        key = (text, round(font_size, 2), tuple(round(c, 4) for c in color[:4]))
        cached = self._text_textures.get(key)
        if cached is not None:
            return cached
        try:
            from kivy.uix.label import Label as UiLabel

            plain = _plain_user_text(text)
            ink = color[:4] if len(color) > 3 else color + (1.0,)
            widget = UiLabel(
                text=mixed_markup(plain),
                markup=True,
                font_size=font_size,
                color=ink,
                halign="right" if _has_hebrew(plain) else "left",
                valign="middle",
                size_hint=(None, None),
            )
            if _LATIN_FONT_READY:
                widget.font_name = "LatinFont"
            elif _HEBREW_FONT_READY:
                widget.font_name = "HebrewFont"
            widget.texture_update()
            tw, th = widget.texture_size
            widget.size = (max(1.0, float(tw)), max(1.0, float(th)))
            widget.texture_update()
            texture = widget.texture
            if texture is None or not texture.size[0] or not texture.size[1]:
                raise RuntimeError("empty text texture")
        except Exception:
            try:
                from kivy.core.text import Label as CoreLabel

                plain = _plain_user_text(text)
                kwargs: Dict[str, Any] = {
                    "text": ui_text(plain),
                    "markup": False,
                    "font_size": font_size,
                    "color": color[:4] if len(color) > 3 else color + (1.0,),
                }
                if _has_hebrew(plain) and _HEBREW_FONT_READY:
                    kwargs["font_name"] = "HebrewFont"
                elif _LATIN_FONT_READY:
                    kwargs["font_name"] = "LatinFont"
                label = CoreLabel(**kwargs)
                label.refresh()
                texture = label.texture
            except Exception:
                return None
        if texture is None:
            return None
        self._text_textures[key] = texture
        return texture

    def _page_number_texture(self, number: int) -> Optional[Any]:
        cached = self._page_num_textures.get(number)
        if cached is not None:
            return cached
        try:
            from kivy.core.text import Label as CoreLabel

            kwargs: Dict[str, Any] = {
                "text": str(number),
                "font_size": 42,
                "color": (0.15, 0.15, 0.18, 1),
            }
            if _LATIN_FONT_READY:
                kwargs["font_name"] = "LatinFont"
            label = CoreLabel(**kwargs)
            label.refresh()
            texture = label.texture
        except Exception:
            return None
        self._page_num_textures[number] = texture
        return texture

    def _draw_record(self, record: StrokeRecord) -> None:
        if record.get("kind") in {"image", "text"}:
            rect = record.get("rect") or [0.0, 0.0, 1.0, 1.0]
            x, y, width, height = [float(v) for v in rect[:4]]
            angle = float(record.get("angle") or 0.0)
            if record.get("kind") == "text":
                texture = self._text_texture(record)
                tex_coords = None
            else:
                path = str(record.get("path") or "")
                texture = self._stamp_texture(path) if path else None
                tex_coords = _stamp_tex_coords(record.get("crop") or [0.0, 0.0, 1.0, 1.0])
            if texture is None:
                return
            Color(1, 1, 1, 1)
            PushMatrix()
            Translate(x + width / 2.0, y + height / 2.0)
            if abs(angle) > 0.01:
                Rotate(angle=angle, axis=(0, 0, 1))
            Translate(-width / 2.0, -height / 2.0)
            kwargs: Dict[str, Any] = {
                "texture": texture,
                "pos": (0.0, 0.0),
                "size": (width, height),
            }
            if tex_coords is not None:
                kwargs["tex_coords"] = tex_coords
            Rectangle(**kwargs)
            PopMatrix()
            return
        color = tuple(record.get("color", COLOR_BLACK))
        width = float(record.get("width", self.ink_width))
        points = record.get("points") or []
        if len(points) < 2:
            return
        Color(*color)
        if record.get("dashed"):
            for dash in dashed_polylines(
                points,
                float(record.get("dash_len", DASH_LENGTH)),
                float(record.get("gap_len", GAP_LENGTH)),
            ):
                Line(points=dash, width=width, cap="round", joint="round")
        else:
            flat: List[float] = []
            for point in points:
                flat.extend([float(point[0]), float(point[1])])
            Line(points=flat, width=width, cap="round", joint="round")

    def _grid_texture(self, page_w: float, page_h: float) -> Any:
        key = (max(2, int(round(page_w))), max(2, int(round(page_h))))
        if self._grid_tex is not None and self._grid_tex_key == key:
            return self._grid_tex
        from PIL import Image, ImageDraw

        width, height = key
        cap = 768.0
        scale = min(1.0, cap / float(max(width, height)))
        tw = max(2, int(round(width * scale)))
        th = max(2, int(round(height * scale)))
        image = Image.new("RGB", (tw, th), (255, 255, 255))
        drawer = ImageDraw.Draw(image)
        color = (199, 214, 235)
        step = max(12, min(tw, th) // 22)
        x = 0
        while x <= tw:
            drawer.line([(x, 0), (x, th)], fill=color, width=1)
            x += step
        y = 0
        while y <= th:
            drawer.line([(0, y), (tw, y)], fill=color, width=1)
            y += step
        self._grid_tex = _pil_to_texture(image)
        self._grid_tex_key = key
        return self._grid_tex

    def _live_points_flat(self) -> List[float]:
        flat: List[float] = []
        for point in self.current_stroke:
            flat.extend([float(point[0]), float(point[1])])
        return flat

    def _sync_live(self) -> None:
        if self._live_dashed or self._live_line is None or self._live_color_instr is None:
            self.redraw_all()
            return
        self._live_color_instr.rgba = self._live_color
        self._live_line.points = self._live_points_flat()
        self._live_line.width = max(1.0, float(self._live_width))

    def redraw_all(self, *_args: Any) -> None:
        origin_x, origin_y, _dw, _dh, scale, page_w, page_h = self._page_metrics()
        count = max(1, int(App.get_running_app().page_count))
        grid_tex = self._grid_texture(page_w, page_h) if self.show_grid else None
        self.canvas.clear()
        self._image_rects = {}
        with self.canvas:
            StencilPush()
            Color(1, 1, 1, 1)
            self._clip_rect = Rectangle(pos=self.pos, size=self.size)
            StencilUse()
            PushMatrix()
            self._tx = Translate(origin_x, origin_y)
            self._sc = Scale(scale, scale, 1)
            for index in range(count):
                page_y = self._page_origin_y(index, page_h)
                Color(1, 1, 1, 1)
                has_page_image = (
                    self.show_document_image
                    and index < len(self._page_textures)
                    and self._page_textures[index] is not None
                )
                if has_page_image:
                    rect = Rectangle(
                        texture=self._page_textures[index],
                        pos=(0, page_y),
                        size=(page_w, page_h),
                    )
                elif grid_tex is not None:
                    rect = Rectangle(
                        texture=grid_tex,
                        pos=(0, page_y),
                        size=(page_w, page_h),
                    )
                else:
                    rect = Rectangle(pos=(0, page_y), size=(page_w, page_h))
                self._image_rects[index] = rect
                number_tex = self._page_number_texture(index + 1)
                if number_tex is not None:
                    nw, nh = number_tex.size
                    target_h = max(12.0, page_h * 0.028)
                    target_w = target_h * (float(nw) / max(1.0, float(nh)))
                    Color(0.12, 0.12, 0.14, 0.38)
                    Rectangle(
                        texture=number_tex,
                        pos=(page_w - target_w - page_w * 0.025, page_y + page_h * 0.016),
                        size=(target_w, target_h),
                    )
            for record in self.strokes:
                self._draw_record(record)
            self._draw_selection()
            self._live_color_instr = Color(*self._live_color)
            self._live_line = Line(
                points=self._live_points_flat(),
                width=max(1.0, float(self._live_width)),
                cap="round",
                joint="round",
            )
            PopMatrix()
            StencilUnUse()
            StencilPop()
        layout = getattr(App.get_running_app(), "root_layout", None)
        if layout is not None and hasattr(layout, "sync_floating_tools"):
            Clock.schedule_once(lambda _dt: layout.sync_floating_tools(), 0)

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
            if record.get("kind") in {"image", "text"}:
                rect = record.get("rect") or [0.0, 0.0, 0.0, 0.0]
                x0, y0, width, height = [float(v) for v in rect[:4]]
                if (
                    x0 - radius <= x <= x0 + width + radius
                    and y0 - radius <= y <= y0 + height + radius
                ):
                    changed = True
                    continue
                kept.append(record)
                continue
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

    def _launch_text_tool(self, doc: Point) -> None:
        app = App.get_running_app()
        hit = self._hit_object(doc)
        if hit is not None and self.strokes[hit].get("kind") == "text":
            app.prompt_text_record(self, hit)
            return
        app.prompt_new_text(self, doc)

    def _begin_two_finger_view(self, touch: MotionEvent) -> None:
        self._cancel_paste_hold()
        app = App.get_running_app()
        app._multitouch = True
        self.current_stroke = []
        self._sync_live()
        app._fingers = dict(app._pointers)
        touch.ud["mode"] = "pinch"
        self._begin_pinch(app)

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        if _is_hover_touch(touch):
            return False
        app = App.get_running_app()
        kind = self._classify(touch)
        if kind == "wheel":
            factor = 1.12 if touch.button == "scrollup" else 0.89
            self._set_scale(self._scale_value() * factor)
            return True
        touch.grab(self)
        app._pointers[touch.uid] = (touch.x, touch.y)
        layout = getattr(app, "root_layout", None)
        if layout is not None:
            layout.hide_paste_chip()
        tool_mode = str(getattr(app, "tool_mode", "none"))
        if tool_mode != "text":
            self._arm_paste_hold(touch)
        if len(app._pointers) >= 2:
            self._begin_two_finger_view(touch)
            return True
        doc = self.to_doc(touch.x, touch.y)
        if tool_mode == "lasso":
            handle = self._hit_handle(doc)
            if handle in {"p0", "p1"}:
                self.push_history()
                touch.ud["mode"] = "endpoint"
                touch.ud["handle"] = handle
                return True
            if handle == "rot":
                self.push_history()
                box = self._selection_bbox()
                cx = box[0] + box[2] / 2.0 if box else doc[0]
                cy = box[1] + box[3] / 2.0 if box else doc[1]
                touch.ud["mode"] = "rotate"
                touch.ud["rot_center"] = (cx, cy)
                touch.ud["rot_start"] = math.degrees(math.atan2(doc[1] - cy, doc[0] - cx))
                self._rotate_origin = self._snapshot_selected()
                return True
            if handle in {"tl", "tr", "bl", "br"}:
                self.push_history()
                touch.ud["mode"] = "resize"
                touch.ud["handle"] = handle
                self._resize_origin = self._snapshot_selected()
                return True
            if handle in {"l", "r", "t", "b"}:
                self.push_history()
                touch.ud["handle"] = handle
                self._resize_origin = self._snapshot_selected()
                if self._single_image() is not None:
                    rec = self._single_image()
                    touch.ud["mode"] = "crop"
                    self._crop_origin = (
                        [float(v) for v in (rec.get("rect") or [0, 0, 1, 1])[:4]],
                        [float(v) for v in (rec.get("crop") or [0.0, 0.0, 1.0, 1.0])[:4]],
                        float(rec.get("angle") or 0.0),
                    )
                else:
                    touch.ud["mode"] = "resize"
                return True
            box = self._selection_bbox()
            if box is not None:
                pad = self._handle_size()
                if (
                    box[0] - pad <= doc[0] <= box[0] + box[2] + pad
                    and box[1] - pad <= doc[1] <= box[1] + box[3] + pad
                ):
                    self.push_history()
                    touch.ud["mode"] = "move"
                    touch.ud["last_doc"] = doc
                    return True
            hit = self._hit_object(doc)
            if hit is not None:
                self.selected_ids = [hit]
                self.push_history()
                touch.ud["mode"] = "move"
                touch.ud["last_doc"] = doc
                self.redraw_all()
                return True
            self.selected_ids = []
            self._live_dashed = True
            self._live_color = (0.12, 0.45, 0.95, 0.9)
            self._live_width = 1.2
            self.current_stroke = [doc]
            touch.ud["mode"] = "lasso"
            self.redraw_all()
            return True
        if kind == "eraser" or tool_mode == "eraser" or bool(getattr(app, "is_eraser", False)):
            touch.ud["erasing"] = True
            self.push_history()
            touch.ud["hist"] = True
            _ox, _oy, _dw, _dh, scale, _pw, _ph = self._page_metrics()
            radius = max(SPEN_ERASER_WIDTH, 36.0) / max(scale, 0.01)
            self._erase_at(doc[0], doc[1], radius)
            return True
        if tool_mode == "none":
            self._start_view_gesture(touch)
            return True
        if tool_mode == "text":
            self.current_stroke = []
            self._sync_live()
            touch.ud["mode"] = "text"
            touch.ud["text_doc"] = doc
            self._launch_text_tool(doc)
            touch.ud["text_opened"] = True
            return True
        color = tuple(getattr(app, "current_color", COLOR_BLACK))[:3]
        opacity = max(0.12, min(1.0, float(getattr(app, "ink_opacity", 1.0))))
        self._live_color = (color[0], color[1], color[2], opacity)
        self._live_width = self._line_width_for_touch(touch)
        self._live_dashed = bool(getattr(app, "is_dashed", False))
        self._live_dash_len = float(getattr(app, "dash_length", DASH_LENGTH))
        self._live_gap_len = float(getattr(app, "dash_gap", GAP_LENGTH))
        if tool_mode in SHAPE_TOOLS:
            touch.ud["shape"] = tool_mode
            touch.ud["shape_start"] = doc
            self.current_stroke = [doc]
            return True
        if tool_mode != "pen":
            self._start_view_gesture(touch)
            return True
        self.current_stroke = [doc]
        return True

    def on_touch_move(self, touch: MotionEvent) -> bool:
        if touch.grab_current is not self:
            return super().on_touch_move(touch)
        app = App.get_running_app()
        if touch.uid in getattr(app, "_pointers", {}):
            app._pointers[touch.uid] = (touch.x, touch.y)
        origin = touch.ud.get("hold_origin")
        if origin is not None and math.hypot(touch.x - origin[0], touch.y - origin[1]) > dp(14):
            self._cancel_paste_hold()
        if bool(getattr(app, "_multitouch", False)) or len(getattr(app, "_pointers", {})) >= 2:
            if len(app._pointers) >= 2:
                app._fingers = dict(app._pointers)
                self._update_pinch(app)
            return True
        mode = touch.ud.get("mode")
        if mode == "text":
            return True
        if mode == "pan":
            last = touch.ud.get("last", (touch.x, touch.y))
            self._add_pan(touch.x - last[0], touch.y - last[1])
            touch.ud["last"] = (touch.x, touch.y)
            return True
        if touch.ud.get("mode") == "move":
            doc = self.to_doc(touch.x, touch.y)
            last = touch.ud.get("last_doc", doc)
            self._translate_selected(doc[0] - last[0], doc[1] - last[1])
            touch.ud["last_doc"] = doc
            self.redraw_all()
            return True
        if touch.ud.get("mode") == "resize":
            self._resize_selected(str(touch.ud.get("handle")), self.to_doc(touch.x, touch.y))
            self.redraw_all()
            return True
        if touch.ud.get("mode") == "crop":
            self._crop_image(str(touch.ud.get("handle")), self.to_doc(touch.x, touch.y))
            self.redraw_all()
            return True
        if touch.ud.get("mode") == "rotate":
            self._rotate_selected(self.to_doc(touch.x, touch.y), touch.ud)
            self.redraw_all()
            return True
        if touch.ud.get("mode") == "endpoint":
            self._move_line_endpoint(str(touch.ud.get("handle")), self.to_doc(touch.x, touch.y))
            self.redraw_all()
            return True
        if touch.ud.get("erasing"):
            if not touch.ud.get("hist"):
                self.push_history()
                touch.ud["hist"] = True
            doc = self.to_doc(touch.x, touch.y)
            _ox, _oy, _dw, _dh, scale, _pw, _ph = self._page_metrics()
            radius = max(SPEN_ERASER_WIDTH, 36.0) / max(scale, 0.01)
            self._erase_at(doc[0], doc[1], radius)
            return True
        if touch.ud.get("shape"):
            start = touch.ud.get("shape_start", self.to_doc(touch.x, touch.y))
            self.current_stroke = shape_points(
                str(touch.ud["shape"]), start, self.to_doc(touch.x, touch.y)
            )
            self._sync_live()
            return True
        doc = self.to_doc(touch.x, touch.y)
        if self.current_stroke and _dist2(self.current_stroke[-1], doc) < 2.25:
            return True
        self.current_stroke.append(doc)
        self._sync_live()
        return True

    def on_touch_up(self, touch: MotionEvent) -> bool:
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        self._cancel_paste_hold()
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
        if touch.ud.get("paste_hold"):
            self.current_stroke = []
            return True
        if touch.ud.get("mode") in {"pan", "pinch", "move", "resize", "crop", "rotate", "endpoint"}:
            return True
        if touch.ud.get("mode") == "text":
            self.current_stroke = []
            self._sync_live()
            if not touch.ud.get("text_opened"):
                self._launch_text_tool(touch.ud.get("text_doc", self.to_doc(touch.x, touch.y)))
            return True
        if touch.ud.get("mode") == "lasso":
            poly = list(self.current_stroke)
            self.current_stroke = []
            length = 0.0
            for i in range(1, len(poly)):
                length += math.hypot(poly[i][0] - poly[i - 1][0], poly[i][1] - poly[i - 1][1])
            if length < 24 and poly:
                hit = self._hit_object(poly[-1])
                self.selected_ids = [hit] if hit is not None else []
            else:
                self._select_with_lasso(poly)
            self.redraw_all()
            return True
        if touch.ud.get("erasing"):
            return True
        if len(self.current_stroke) >= 2:
            self.push_history()
            record: StrokeRecord = {
                "points": [list(point) for point in self.current_stroke],
                "color": list(self._live_color),
                "width": self._live_width,
                "dashed": self._live_dashed,
                "dash_len": getattr(self, "_live_dash_len", DASH_LENGTH),
                "gap_len": getattr(self, "_live_gap_len", GAP_LENGTH),
                "eraser": False,
            }
            shape = touch.ud.get("shape")
            if shape:
                record["kind"] = str(shape)
            self.strokes.append(record)
        self.current_stroke = []
        self.redraw_all()
        return True

    def serialized_strokes(self) -> List[StrokeRecord]:
        return json.loads(json.dumps(self.strokes))

    def load_strokes(self, records: Sequence[StrokeRecord]) -> None:
        self.strokes = [dict(record) for record in records]
        self.selected_ids = []
        self.redraw_all()

    def _snapshot_strokes(self) -> List[StrokeRecord]:
        try:
            return json.loads(json.dumps(self.strokes))
        except Exception:
            return copy.deepcopy(self.strokes)

    def push_history(self) -> None:
        self._undo_stack.append(self._snapshot_strokes())
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        app = App.get_running_app()
        app._history_role = self.view_role

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._snapshot_strokes())
        self.strokes = self._undo_stack.pop()
        self.selected_ids = []
        self.redraw_all()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._snapshot_strokes())
        self.strokes = self._redo_stack.pop()
        self.selected_ids = []
        self.redraw_all()
        return True

    def _is_line(self, record: StrokeRecord) -> bool:
        if record.get("kind") in {"image", "text"}:
            return False
        if str(record.get("kind") or "") == "line":
            return True
        points = record.get("points") or []
        return len(points) == 2

    def _single_selected(self) -> Optional[StrokeRecord]:
        if len(self.selected_ids) != 1:
            return None
        index = self.selected_ids[0]
        if not (0 <= index < len(self.strokes)):
            return None
        return self.strokes[index]

    def _single_image(self) -> Optional[StrokeRecord]:
        record = self._single_selected()
        if record is None or record.get("kind") != "image":
            return None
        return record

    def _single_framed(self) -> Optional[StrokeRecord]:
        record = self._single_selected()
        if record is None or record.get("kind") not in {"image", "text"}:
            return None
        return record

    def _record_corners(self, record: StrokeRecord) -> List[Point]:
        if record.get("kind") in {"image", "text"}:
            rect = record.get("rect") or [0.0, 0.0, 0.0, 0.0]
            x, y, width, height = [float(v) for v in rect[:4]]
            angle = float(record.get("angle") or 0.0)
            cx, cy = x + width / 2.0, y + height / 2.0
            local = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
            if abs(angle) < 0.01:
                return local
            return [_rotate_point(px, py, cx, cy, angle) for px, py in local]
        points = record.get("points") or []
        return [(float(p[0]), float(p[1])) for p in points]

    def _record_bbox(self, record: StrokeRecord) -> Optional[Tuple[float, float, float, float]]:
        corners = self._record_corners(record)
        if len(corners) < 2:
            if record.get("kind") in {"image", "text"}:
                rect = record.get("rect") or [0.0, 0.0, 0.0, 0.0]
                return (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
            return None
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        left, bottom = min(xs), min(ys)
        return (left, bottom, max(xs) - left, max(ys) - bottom)

    def _selection_bbox(self) -> Optional[Tuple[float, float, float, float]]:
        boxes = []
        for index in self.selected_ids:
            if 0 <= index < len(self.strokes):
                box = self._record_bbox(self.strokes[index])
                if box is not None:
                    boxes.append(box)
        if not boxes:
            return None
        left = min(box[0] for box in boxes)
        bottom = min(box[1] for box in boxes)
        right = max(box[0] + box[2] for box in boxes)
        top = max(box[1] + box[3] for box in boxes)
        return (left, bottom, right - left, top - bottom)

    def _handle_size(self) -> float:
        _ox, _oy, _dw, _dh, scale, _pw, _ph = self._page_metrics()
        return HANDLE_SIZE / max(scale, 0.05)

    def _handle_centers(self, box: Tuple[float, float, float, float]) -> Dict[str, Tuple[float, float]]:
        x, y, w, h = box
        image = self._single_framed()
        if image is not None:
            rect = [float(v) for v in (image.get("rect") or [0, 0, 1, 1])[:4]]
            angle = float(image.get("angle") or 0.0)
            cx, cy = rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0
            local = {
                "bl": (rect[0], rect[1]),
                "br": (rect[0] + rect[2], rect[1]),
                "tl": (rect[0], rect[1] + rect[3]),
                "tr": (rect[0] + rect[2], rect[1] + rect[3]),
                "l": (rect[0], rect[1] + rect[3] / 2.0),
                "r": (rect[0] + rect[2], rect[1] + rect[3] / 2.0),
                "b": (rect[0] + rect[2] / 2.0, rect[1]),
                "t": (rect[0] + rect[2] / 2.0, rect[1] + rect[3]),
            }
            world = {
                name: _rotate_point(px, py, cx, cy, angle) for name, (px, py) in local.items()
            }
            top = world["t"]
            upx, upy = _rotate_point(cx, cy + rect[3] / 2.0 + self._handle_size() * 1.8, cx, cy, angle)
            world["rot"] = (upx, upy)
            world["_top"] = top
            return world
        centers = {
            "bl": (x, y),
            "br": (x + w, y),
            "tl": (x, y + h),
            "tr": (x + w, y + h),
            "l": (x, y + h / 2.0),
            "r": (x + w, y + h / 2.0),
            "b": (x + w / 2.0, y),
            "t": (x + w / 2.0, y + h),
        }
        centers["rot"] = (x + w / 2.0, y + h + self._handle_size() * 1.8)
        record = self._single_selected()
        if record is not None and self._is_line(record):
            points = record.get("points") or []
            if len(points) >= 2:
                centers["p0"] = (float(points[0][0]), float(points[0][1]))
                centers["p1"] = (float(points[-1][0]), float(points[-1][1]))
        return centers

    def _hit_handle(self, doc: Point) -> Optional[str]:
        if not self.selected_ids:
            return None
        box = self._selection_bbox()
        if box is None:
            return None
        size = self._handle_size()
        centers = self._handle_centers(box)
        priority = ("p0", "p1", "rot", "tl", "tr", "bl", "br", "l", "r", "t", "b")
        for name in priority:
            center = centers.get(name)
            if center is None:
                continue
            if abs(doc[0] - center[0]) <= size and abs(doc[1] - center[1]) <= size:
                return name
        return None

    def _point_in_poly(self, x: float, y: float, poly: Sequence[Point]) -> bool:
        inside = False
        j = len(poly) - 1
        for i, point in enumerate(poly):
            xi, yi = float(point[0]), float(point[1])
            xj, yj = float(poly[j][0]), float(poly[j][1])
            intersect = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            )
            if intersect:
                inside = not inside
            j = i
        return inside

    def _select_with_lasso(self, poly: Sequence[Point]) -> None:
        if len(poly) < 3:
            self.selected_ids = []
            return
        chosen: List[int] = []
        for index, record in enumerate(self.strokes):
            box = self._record_bbox(record)
            if box is None:
                continue
            cx, cy = box[0] + box[2] / 2.0, box[1] + box[3] / 2.0
            if record.get("kind") in {"image", "text"}:
                corners = [
                    (box[0], box[1]),
                    (box[0] + box[2], box[1]),
                    (box[0] + box[2], box[1] + box[3]),
                    (box[0], box[1] + box[3]),
                ]
                if self._point_in_poly(cx, cy, poly) or any(
                    self._point_in_poly(px, py, poly) for px, py in corners
                ):
                    chosen.append(index)
                continue
            points = record.get("points") or []
            hits = sum(1 for point in points if self._point_in_poly(float(point[0]), float(point[1]), poly))
            if hits >= max(1, len(points) // 3):
                chosen.append(index)
        self.selected_ids = chosen

    def _hit_object(self, doc: Point) -> Optional[int]:
        x, y = doc
        pad = self._handle_size()
        for index in range(len(self.strokes) - 1, -1, -1):
            record = self.strokes[index]
            if record.get("kind") in {"image", "text"}:
                rect = [float(v) for v in (record.get("rect") or [0, 0, 0, 0])[:4]]
                angle = float(record.get("angle") or 0.0)
                cx, cy = rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0
                lx, ly = _rotate_point(x, y, cx, cy, -angle)
                if (
                    rect[0] - pad <= lx <= rect[0] + rect[2] + pad
                    and rect[1] - pad <= ly <= rect[1] + rect[3] + pad
                ):
                    return index
                continue
            box = self._record_bbox(record)
            if box is None:
                continue
            if box[0] - pad <= x <= box[0] + box[2] + pad and box[1] - pad <= y <= box[1] + box[3] + pad:
                return index
        return None

    def _translate_record(self, record: StrokeRecord, dx: float, dy: float) -> None:
        if record.get("kind") in {"image", "text"}:
            rect = [float(v) for v in (record.get("rect") or [0, 0, 0, 0])[:4]]
            rect[0] += dx
            rect[1] += dy
            record["rect"] = rect
            record["points"] = [[rect[0], rect[1]], [rect[0] + rect[2], rect[1] + rect[3]]]
            return
        points = record.get("points") or []
        record["points"] = [[float(p[0]) + dx, float(p[1]) + dy] for p in points]

    def _translate_selected(self, dx: float, dy: float) -> None:
        for index in self.selected_ids:
            if 0 <= index < len(self.strokes):
                self._translate_record(self.strokes[index], dx, dy)

    def _snapshot_selected(self) -> Dict[str, Any]:
        items = []
        for index in self.selected_ids:
            if not (0 <= index < len(self.strokes)):
                continue
            record = self.strokes[index]
            items.append(
                {
                    "index": index,
                    "rect": [float(v) for v in (record.get("rect") or [0, 0, 0, 0])[:4]],
                    "crop": [float(v) for v in (record.get("crop") or [0.0, 0.0, 1.0, 1.0])[:4]],
                    "points": [list(p) for p in (record.get("points") or [])],
                    "angle": float(record.get("angle") or 0.0),
                    "font_size": float(record.get("font_size") or 28.0),
                    "kind": record.get("kind"),
                }
            )
        box = self._selection_bbox() or (0.0, 0.0, 1.0, 1.0)
        return {"box": list(box), "items": items}

    def _scaled_box(
        self, handle: str, origin: Sequence[float], doc: Point, keep_aspect: bool
    ) -> List[float]:
        ox, oy, ow, oh = [float(v) for v in origin[:4]]
        min_size = 12.0
        nx, ny, nw, nh = ox, oy, ow, oh
        local = doc
        if "l" in handle:
            nx = min(local[0], ox + ow - min_size)
            nw = ox + ow - nx
        if "r" in handle:
            nw = max(min_size, local[0] - ox)
        if "b" in handle:
            ny = min(local[1], oy + oh - min_size)
            nh = oy + oh - ny
        if "t" in handle:
            nh = max(min_size, local[1] - oy)
        if keep_aspect and oh > 1:
            ratio = ow / oh
            if handle in {"tr", "br"}:
                nh = max(min_size, nw / ratio)
                if handle == "tr":
                    ny = oy + oh - nh
            elif handle in {"tl", "bl"}:
                nw = max(min_size, nh * ratio)
                if handle == "tl":
                    nx = ox + ow - nw
                    ny = oy + oh - nh
                elif handle == "bl":
                    nx = ox + ow - nw
        return [nx, ny, nw, nh]

    def _resize_selected(self, handle: str, doc: Point) -> None:
        snap = getattr(self, "_resize_origin", None)
        if not snap:
            return
        image = self._single_framed()
        if image is not None and len(snap["items"]) == 1:
            item = snap["items"][0]
            ox, oy, ow, oh = item["rect"]
            cx, cy = ox + ow / 2.0, oy + oh / 2.0
            angle = item["angle"]
            local = _rotate_point(doc[0], doc[1], cx, cy, -angle)
            nx, ny, nw, nh = self._scaled_box(handle, item["rect"], local, handle in {"tl", "tr", "bl", "br"})
            image["rect"] = [nx, ny, nw, nh]
            image["points"] = [[nx, ny], [nx + nw, ny + nh]]
            if image.get("kind") == "text":
                image["font_size"] = max(10.0, float(item.get("font_size") or 28.0) * (nh / max(oh, 1.0)))
                self._text_textures.clear()
            return
        ox, oy, ow, oh = [float(v) for v in snap["box"][:4]]
        nx, ny, nw, nh = self._scaled_box(handle, snap["box"], doc, handle in {"tl", "tr", "bl", "br"})
        sx = nw / max(ow, 1e-3)
        sy = nh / max(oh, 1e-3)
        for item in snap["items"]:
            record = self.strokes[item["index"]]
            if item.get("kind") in {"image", "text"}:
                rx, ry, rw, rh = item["rect"]
                record["rect"] = [nx + (rx - ox) * sx, ny + (ry - oy) * sy, rw * sx, rh * sy]
                rect = record["rect"]
                record["points"] = [[rect[0], rect[1]], [rect[0] + rect[2], rect[1] + rect[3]]]
                if item.get("kind") == "text":
                    record["font_size"] = max(10.0, float(item.get("font_size") or 28.0) * sy)
                    self._text_textures.clear()
                continue
            record["points"] = [
                [nx + (float(p[0]) - ox) * sx, ny + (float(p[1]) - oy) * sy] for p in item["points"]
            ]

    def _crop_image(self, handle: str, doc: Point) -> None:
        record = self._single_image()
        if record is None:
            return
        origin = getattr(self, "_crop_origin", None)
        if origin is None:
            origin = (
                list(record.get("rect") or [0, 0, 1, 1]),
                list(record.get("crop") or [0.0, 0.0, 1.0, 1.0]),
                float(record.get("angle") or 0.0),
            )
        x, y, w, h = [float(v) for v in origin[0][:4]]
        u0, v0, u1, v1 = [float(v) for v in origin[1][:4]]
        angle = float(origin[2]) if len(origin) > 2 else float(record.get("angle") or 0.0)
        cx, cy = x + w / 2.0, y + h / 2.0
        local = _rotate_point(doc[0], doc[1], cx, cy, -angle)
        min_frac = 0.08
        if handle == "l":
            frac = max(0.0, min(1.0 - min_frac, (local[0] - x) / max(w, 1.0)))
            record["rect"] = [x + frac * w, y, w * (1.0 - frac), h]
            record["crop"] = [u0 + frac * (u1 - u0), v0, u1, v1]
        elif handle == "r":
            frac = max(min_frac, min(1.0, (local[0] - x) / max(w, 1.0)))
            record["rect"] = [x, y, w * frac, h]
            record["crop"] = [u0, v0, u0 + frac * (u1 - u0), v1]
        elif handle == "b":
            frac = max(0.0, min(1.0 - min_frac, (local[1] - y) / max(h, 1.0)))
            record["rect"] = [x, y + frac * h, w, h * (1.0 - frac)]
            record["crop"] = [u0, v0 + frac * (v1 - v0), u1, v1]
        elif handle == "t":
            frac = max(min_frac, min(1.0, (local[1] - y) / max(h, 1.0)))
            record["rect"] = [x, y, w, h * frac]
            record["crop"] = [u0, v0, u1, v0 + frac * (v1 - v0)]
        rect = record["rect"]
        record["points"] = [[rect[0], rect[1]], [rect[0] + rect[2], rect[1] + rect[3]]]

    def _rotate_selected(self, doc: Point, ud: Dict[str, Any]) -> None:
        snap = getattr(self, "_rotate_origin", None)
        if not snap:
            return
        cx, cy = ud.get("rot_center", (doc[0], doc[1]))
        start = float(ud.get("rot_start", 0.0))
        now = math.degrees(math.atan2(doc[1] - cy, doc[0] - cx))
        delta = now - start
        for item in snap["items"]:
            record = self.strokes[item["index"]]
            if item.get("kind") in {"image", "text"}:
                rx, ry, rw, rh = item["rect"]
                icx, icy = rx + rw / 2.0, ry + rh / 2.0
                ncx, ncy = _rotate_point(icx, icy, cx, cy, delta)
                record["rect"] = [ncx - rw / 2.0, ncy - rh / 2.0, rw, rh]
                record["angle"] = item["angle"] + delta
                rect = record["rect"]
                record["points"] = [[rect[0], rect[1]], [rect[0] + rect[2], rect[1] + rect[3]]]
                continue
            record["points"] = [
                list(_rotate_point(float(p[0]), float(p[1]), cx, cy, delta)) for p in item["points"]
            ]

    def _move_line_endpoint(self, handle: str, doc: Point) -> None:
        record = self._single_selected()
        if record is None or not self._is_line(record):
            return
        points = [list(p) for p in (record.get("points") or [])]
        if len(points) < 2:
            return
        if handle == "p0":
            points[0] = [doc[0], doc[1]]
        else:
            points[-1] = [doc[0], doc[1]]
        record["points"] = points

    def copy_selected(self) -> List[StrokeRecord]:
        payload = []
        for index in self.selected_ids:
            if 0 <= index < len(self.strokes):
                payload.append(json.loads(json.dumps(self.strokes[index])))
        return payload

    def delete_selected(self) -> bool:
        if not self.selected_ids:
            return False
        self.push_history()
        drop = set(self.selected_ids)
        self.strokes = [record for index, record in enumerate(self.strokes) if index not in drop]
        self.selected_ids = []
        self.redraw_all()
        return True

    def paste_records(self, records: Sequence[StrokeRecord], dx: float = 36.0, dy: float = -36.0) -> None:
        if not records:
            return
        self.push_history()
        new_ids: List[int] = []
        for record in records:
            clone = json.loads(json.dumps(record))
            self._translate_record(clone, dx, dy)
            self.strokes.append(clone)
            new_ids.append(len(self.strokes) - 1)
        self.selected_ids = new_ids
        self.redraw_all()

    def place_text_record(self, doc: Point, text: str, color: Sequence[float], font_size: float = 28.0, index: Optional[int] = None) -> None:
        self.push_history()
        plain = _plain_user_text(text)
        record: StrokeRecord = {
            "kind": "text",
            "text": plain,
            "font_size": float(font_size),
            "color": list(color)[:4] if len(color) > 3 else list(color) + [1.0],
            "angle": 0.0,
            "rect": [doc[0], doc[1], 80.0, 32.0],
            "points": [[doc[0], doc[1]], [doc[0] + 80.0, doc[1] + 32.0]],
            "width": 1.0,
            "dashed": False,
            "eraser": False,
        }
        if index is not None and 0 <= index < len(self.strokes) and self.strokes[index].get("kind") == "text":
            record["angle"] = float(self.strokes[index].get("angle") or 0.0)
            record["rect"] = list(self.strokes[index].get("rect") or record["rect"])
            self.strokes[index] = record
            target = index
        else:
            self.strokes.append(record)
            target = len(self.strokes) - 1
        texture = self._text_texture(record)
        if texture is not None:
            width, height = max(24.0, float(texture.size[0])), max(18.0, float(texture.size[1]))
            if index is not None:
                x, y = float(record["rect"][0]), float(record["rect"][1])
            else:
                x = doc[0] - width if _has_hebrew(plain) else doc[0]
                y = doc[1] - height
            record["rect"] = [x, y, width, height]
            record["points"] = [[x, y], [x + width, y + height]]
        self.selected_ids = [target]
        self.redraw_all()

    def paste_records_at(self, records: Sequence[StrokeRecord], doc: Point) -> None:
        if not records:
            return
        boxes = []
        for record in records:
            box = self._record_bbox(record)
            if box is not None:
                boxes.append(box)
        if boxes:
            left = min(box[0] for box in boxes)
            bottom = min(box[1] for box in boxes)
            right = max(box[0] + box[2] for box in boxes)
            top = max(box[1] + box[3] for box in boxes)
            cx, cy = (left + right) / 2.0, (bottom + top) / 2.0
            self.paste_records(records, dx=doc[0] - cx, dy=doc[1] - cy)
            return
        self.paste_records(records, dx=doc[0], dy=doc[1])

    def _draw_selection(self) -> None:
        if str(getattr(App.get_running_app(), "tool_mode", "")) != "lasso":
            return
        box = self._selection_bbox()
        if box is None:
            return
        x, y, w, h = box
        Color(0.15, 0.45, 0.95, 0.9)
        Line(rectangle=(x, y, w, h), width=1.1)
        size = self._handle_size()
        handles = self._handle_centers(box)
        for name, center in handles.items():
            if name.startswith("_"):
                continue
            hx, hy = center
            if name in {"p0", "p1"}:
                Color(0.18, 0.72, 0.32, 1)
                Ellipse(pos=(hx - size / 2.0, hy - size / 2.0), size=(size, size))
            elif name == "rot":
                top = handles.get("t") or handles.get("_top")
                if top is not None:
                    Color(0.12, 0.46, 0.95, 0.95)
                    Line(points=[top[0], top[1], hx, hy], width=1.1)
                Color(0.45, 0.22, 0.86, 1)
                Ellipse(pos=(hx - size / 2.0, hy - size / 2.0), size=(size, size))
            elif name in {"tl", "tr", "bl", "br"}:
                Color(0.12, 0.46, 0.95, 1)
                Rectangle(pos=(hx - size / 2.0, hy - size / 2.0), size=(size, size))
            else:
                Color(0.95, 0.55, 0.12, 1)
                Line(
                    rectangle=(hx - size / 2.5, hy - size / 2.5, size * 0.8, size * 0.8),
                    width=1.2,
                )


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
        self.pdf_canvas.size_hint = (None, None)
        self.notes_canvas.size_hint = (None, None)
        self.workspace.add_widget(self.pdf_canvas)
        self.workspace.add_widget(self.notes_canvas)
        self.chrome = AbsorbLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=dp(CHROME_HEIGHT_DP),
            pos_hint={"x": 0, "top": 1},
            spacing=0,
        )
        self._shapes_open = False
        self.chrome.add_widget(self._build_header())
        self.chrome.add_widget(self._build_toolbar())
        self.shape_bar = self._build_shape_bar()
        self.shape_bar.height = 0
        self.shape_bar.opacity = 0
        self.shape_bar.disabled = True
        self.chrome.add_widget(self.shape_bar)
        self.chrome.add_widget(self._build_slider_bar())
        self.restore_btn = ToolIcon(
            "restore",
            on_dark=True,
            size_hint=(None, None),
            size=(dp(48), dp(32)),
            pos_hint={"center_x": 0.5, "top": 1},
            trigger=self.show_toolbar,
        )
        self.restore_btn.opacity = 0
        self.restore_btn.disabled = True
        self.copy_chip = SelectionBar()
        self.paste_chip = ToolIcon("paste", on_dark=True, size=(dp(48), dp(44)), trigger=self._on_paste_chip)
        self._paste_target: Optional[Tuple[Any, float, float]] = None
        self.text_overlay = self._build_text_overlay()
        self.add_widget(self.workspace)
        self.add_widget(self.chrome)
        self.add_widget(self.copy_chip)
        self.add_widget(self.paste_chip)
        self.add_widget(self.text_overlay)
        self.add_widget(self.restore_btn)
        self.hide_copy_chip()
        self.hide_paste_chip()
        self.hide_text_overlay()
        self.refresh_tool_styles()
        app = App.get_running_app()
        app.bind(
            view_scale=self.sync_floating_tools,
            view_pan_x=self.sync_floating_tools,
            view_pan_y=self.sync_floating_tools,
            notes_scale=self.sync_floating_tools,
            notes_pan_x=self.sync_floating_tools,
        )
        self.bind(size=self._fit_workspace, pos=self._fit_workspace)
        Window.bind(size=lambda *_args: self.apply_orientation())
        Clock.schedule_once(lambda _dt: self.apply_orientation(), 0)

    def _fit_workspace(self, *_args: Any) -> None:
        chrome_h = float(self.chrome.height) if self.toolbar_visible else 0.0
        work_h = max(1.0, float(self.height) - chrome_h)
        self.workspace.size = (float(self.width), work_h)
        self.workspace.pos = (float(self.x), float(self.y))
        self.dock_notes()
        self.sync_floating_tools()

    def hide_copy_chip(self) -> None:
        self.copy_chip.opacity = 0
        self.copy_chip.disabled = True
        self.copy_chip.pos = (-2000.0, -2000.0)

    def hide_paste_chip(self) -> None:
        self.paste_chip.opacity = 0
        self.paste_chip.disabled = True
        self.paste_chip.pos = (-2000.0, -2000.0)
        self._paste_target = None

    def _place_chip(
        self,
        chip: Widget,
        widget: Widget,
        x: float,
        y: float,
        lift: float = 12.0,
        side: float = 0.0,
    ) -> None:
        win_x, win_y = widget.to_window(x, y)
        local_x, local_y = self.to_widget(win_x, win_y)
        chip.center_x = min(
            max(local_x + side, chip.width / 2.0 + dp(8)),
            self.width - chip.width / 2.0 - dp(8),
        )
        chip.y = local_y + lift
        if self.toolbar_visible and chip.top > self.chrome.y - dp(4):
            chip.y = self.chrome.y - chip.height - dp(6)
        if chip.y < dp(8):
            chip.y = dp(8)
        chip.opacity = 1
        chip.disabled = False

    def sync_floating_tools(self, *_args: Any) -> None:
        app = App.get_running_app()
        if str(getattr(app, "tool_mode", "")) != "lasso":
            self.hide_copy_chip()
            return
        canvas = None
        box = None
        for candidate in (self.pdf_canvas, self.notes_canvas):
            if candidate.selected_ids:
                box = candidate._selection_bbox()
                if box is not None:
                    canvas = candidate
                    break
        if canvas is None or box is None:
            self.hide_copy_chip()
            return
        sx, sy = canvas.from_doc(box[0] + box[2], box[1] + box[3])
        self._place_chip(self.copy_chip, canvas, sx, sy, lift=dp(72), side=dp(44))

    def show_paste_chip(self, canvas: SPenAnnotationCanvas, x: float, y: float) -> None:
        app = App.get_running_app()
        if not getattr(app, "_clipboard", None):
            return
        self._paste_target = (canvas, x, y)
        self._place_chip(self.paste_chip, canvas, x, y, lift=dp(16), side=0.0)

    def _on_copy_chip(self, *_args: Any) -> None:
        App.get_running_app().copy_selection()

    def _on_paste_chip(self, *_args: Any) -> None:
        App.get_running_app().paste_at_chip()
        self.hide_paste_chip()

    def _build_text_overlay(self) -> AbsorbLayout:
        box = AbsorbLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=dp(168),
            pos_hint={"x": 0, "y": 0},
            padding=dp(10),
            spacing=dp(6),
        )
        with box.canvas.before:
            Color(0.12, 0.12, 0.14, 0.97)
            self._text_overlay_bg = Rectangle()
        box.bind(
            pos=lambda *_args: setattr(self._text_overlay_bg, "pos", box.pos),
            size=lambda *_args: setattr(self._text_overlay_bg, "size", box.size),
        )
        self.text_field = TextInput(
            text="",
            multiline=True,
            font_size=dp(18),
            input_type="text",
            write_tab=False,
            size_hint_y=1,
        )
        if _LATIN_FONT_READY:
            self.text_field.font_name = "LatinFont"
        buttons = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        ok_btn = Button(text="אישור")
        cancel_btn = Button(text="ביטול")
        ok_btn.bind(on_release=self._commit_text_overlay)
        cancel_btn.bind(on_release=lambda *_args: self.hide_text_overlay())
        buttons.add_widget(ok_btn)
        buttons.add_widget(cancel_btn)
        hint = Label(
            text=mixed_markup("כתבו טקסט בעברית או באנגלית"),
            markup=True,
            size_hint_y=None,
            height=dp(24),
            color=(1, 1, 1, 1),
        )
        box.add_widget(hint)
        box.add_widget(self.text_field)
        box.add_widget(buttons)
        self._text_target: Optional[Tuple[Any, Point, Optional[int]]] = None
        apply_hebrew_ui(hint)
        apply_hebrew_ui(ok_btn)
        apply_hebrew_ui(cancel_btn)
        return box

    def hide_text_overlay(self) -> None:
        self.text_overlay.opacity = 0
        self.text_overlay.disabled = True
        self.text_overlay.y = -400.0
        self.text_field.focus = False
        self._text_target = None

    def show_text_overlay(self, canvas: SPenAnnotationCanvas, doc: Point, existing: Optional[int] = None) -> None:
        initial = ""
        if existing is not None and 0 <= existing < len(canvas.strokes):
            initial = str(canvas.strokes[existing].get("text") or "")
        self._text_target = (canvas, doc, existing)
        self.text_field.text = initial
        self.text_overlay.disabled = False
        self.text_overlay.opacity = 1
        self.text_overlay.pos_hint = {}
        self.text_overlay.height = dp(168)
        self.text_overlay.x = float(self.x)
        self.text_overlay.width = float(self.width)
        top = float(self.chrome.y) if self.toolbar_visible else float(self.top)
        self.text_overlay.top = max(self.text_overlay.height, top)
        focus_system_keyboard(self.text_field)

    def _commit_text_overlay(self, *_args: Any) -> None:
        target = self._text_target
        text = _plain_user_text(self.text_field.text)
        self.hide_text_overlay()
        if not target or not text:
            return
        canvas, doc, existing = target
        app = App.get_running_app()
        color = list(getattr(app, "current_color", COLOR_BLACK))
        font_size = 28.0
        if existing is not None and 0 <= existing < len(canvas.strokes):
            font_size = float(canvas.strokes[existing].get("font_size") or 28.0)
        canvas.place_text_record(doc, text, color, font_size=font_size, index=existing)
        app._history_role = canvas.view_role
        app.tool_mode = "lasso"
        self.refresh_tool_styles()
        self.sync_floating_tools()

    def set_status(self, message: str) -> None:
        self.status_label.text = mixed_markup(message)

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
            ("image", "image", app.import_image),
            ("save_as", "save", app.save_document_as),
            ("toggle", "notes", self.toggle_notes),
        ):
            button = ToolIcon(kind, on_dark=False, size=(dp(44), dp(36)), trigger=handler)
            header.add_widget(button)
            self.tool_buttons[key] = button
        self.status_label = Label(
            text="",
            color=(0.35, 0.35, 0.38, 1),
            font_size=dp(13),
            halign="right",
            valign="middle",
            markup=True,
        )
        self.title_button = Button(
            text=mixed_markup(f"> {app.document_title}"),
            color=(0.12, 0.12, 0.14, 1),
            font_size=dp(16),
            bold=True,
            markup=True,
            size_hint_x=None,
            width=dp(220),
            background_normal="",
            background_down="",
            background_color=(1, 1, 1, 1),
            halign="right",
        )
        self.title_button.bind(on_release=app.rename_document)
        header.add_widget(self.status_label)
        header.add_widget(self.title_button)
        return header

    def _build_toolbar(self) -> BoxLayout:
        app = App.get_running_app()
        toolbar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            padding=(dp(6), dp(4)),
            spacing=dp(4),
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
            ("fit", "fit", app.reset_view),
            ("undo", "undo", app.undo),
            ("redo", "redo", app.redo),
            ("pen", "pen", app.select_pen),
            ("dashed", "dashed", app.toggle_dashed),
            ("eraser", "eraser", app.enable_eraser),
            ("lasso", "lasso", app.select_lasso),
            ("text", "text", app.select_text),
            ("shapes", "shapes", app.toggle_shape_menu),
        )
        for key, kind, handler in actions:
            button = ToolIcon(kind, on_dark=True, size=(dp(48), dp(44)), trigger=handler)
            toolbar.add_widget(button)
            self.tool_buttons[key] = button
        for key, rgba in INK_COLORS:
            dot = ColorDot(rgba, trigger=lambda _dot, name=key: app.set_ink_color(name))
            toolbar.add_widget(dot)
            self.color_dots[key] = dot
        palette_btn = ToolIcon("palette", on_dark=True, trigger=app.open_color_picker)
        toolbar.add_widget(palette_btn)
        self.tool_buttons["palette"] = palette_btn
        hide_btn = ToolIcon("hide", on_dark=True, trigger=self.hide_toolbar)
        toolbar.add_widget(Widget())
        toolbar.add_widget(hide_btn)
        self.tool_buttons["hide"] = hide_btn
        return toolbar

    def _build_shape_bar(self) -> BoxLayout:
        app = App.get_running_app()
        bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            padding=(dp(8), dp(4)),
            spacing=dp(2),
        )
        with bar.canvas.before:
            Color(*TOOLBAR_BG)
            self._shape_bg = Rectangle()
        bar.bind(
            pos=lambda *_args: setattr(self._shape_bg, "pos", bar.pos),
            size=lambda *_args: setattr(self._shape_bg, "size", bar.size),
        )
        for kind in SHAPE_ORDER:
            button = ToolIcon(
                kind,
                on_dark=True,
                size=(dp(36), dp(36)),
                trigger=lambda _btn, name=kind: app.select_shape(name),
            )
            bar.add_widget(button)
            self.tool_buttons[kind] = button
        bar.add_widget(Widget())
        return bar

    def _make_slider(
        self, kind: str, minimum: float, maximum: float, value: float, on_change: Any
    ) -> BoxLayout:
        cluster = BoxLayout(orientation="horizontal", size_hint_x=None, width=dp(138), spacing=dp(2))
        glyph = SliderGlyph(kind, amount=value)
        slider = Slider(min=minimum, max=maximum, value=value, size_hint_x=1)
        slider.bind(value=lambda _slider, amount, g=glyph, cb=on_change: (setattr(g, "amount", amount), cb(amount)))
        cluster.add_widget(glyph)
        cluster.add_widget(slider)
        return cluster

    def _build_slider_bar(self) -> BoxLayout:
        app = App.get_running_app()
        bar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(40),
            padding=(dp(8), dp(4)),
            spacing=dp(8),
        )
        with bar.canvas.before:
            Color(*TOOLBAR_BG)
            self._slider_bg = Rectangle()
        bar.bind(
            pos=lambda *_args: setattr(self._slider_bg, "pos", bar.pos),
            size=lambda *_args: setattr(self._slider_bg, "size", bar.size),
        )
        bar.add_widget(self._make_slider("width", 1.0, 16.0, float(app.ink_width), app.set_ink_width))
        bar.add_widget(self._make_slider("opacity", 0.15, 1.0, float(app.ink_opacity), app.set_ink_opacity))
        bar.add_widget(self._make_slider("dash", 4.0, 40.0, float(app.dash_gap), app.set_dash_gap))
        bar.add_widget(Widget())
        return bar

    def _chrome_height(self) -> float:
        extra = dp(SHAPE_BAR_DP) if self._shapes_open else 0.0
        return dp(CHROME_HEIGHT_DP) + extra

    def set_shapes_open(self, open_menu: bool) -> None:
        self._shapes_open = bool(open_menu)
        self.shape_bar.height = dp(SHAPE_BAR_DP) if self._shapes_open else 0
        self.shape_bar.opacity = 1 if self._shapes_open else 0
        self.shape_bar.disabled = not self._shapes_open
        if self.toolbar_visible:
            self.chrome.height = self._chrome_height()
            self._fit_workspace()
        self.refresh_tool_styles()

    def toggle_shape_menu(self, *_args: Any) -> None:
        self.set_shapes_open(not self._shapes_open)

    def hide_toolbar(self, *_args: Any) -> None:
        self.set_shapes_open(False)
        self.toolbar_visible = False
        self.chrome.opacity = 0
        self.chrome.disabled = True
        self.chrome.height = 0
        self.restore_btn.opacity = 1
        self.restore_btn.disabled = False
        self._fit_workspace()
        Clock.schedule_once(lambda _dt: App.get_running_app().clamp_view(), 0)

    def show_toolbar(self, *_args: Any) -> None:
        self.toolbar_visible = True
        self.chrome.opacity = 1
        self.chrome.disabled = False
        self.chrome.height = self._chrome_height()
        self.restore_btn.opacity = 0
        self.restore_btn.disabled = True
        self._fit_workspace()
        Clock.schedule_once(lambda _dt: App.get_running_app().clamp_view(), 0)

    def refresh_tool_styles(self) -> None:
        app = App.get_running_app()
        pen_on = app.tool_mode == "pen"
        drawing = pen_on or app.tool_mode in SHAPE_TOOLS or app.tool_mode == "text"
        mapping = {
            "pan": app.tool_mode == "none",
            "pen": pen_on and not app.is_dashed,
            "dashed": pen_on and bool(app.is_dashed),
            "eraser": app.tool_mode == "eraser",
            "lasso": app.tool_mode == "lasso",
            "text": app.tool_mode == "text",
            "shapes": app.tool_mode in SHAPE_TOOLS or self._shapes_open,
        }
        for shape in SHAPE_TOOLS:
            mapping[shape] = app.tool_mode == shape
        for key, button in self.tool_buttons.items():
            if key in {"open", "save_as", "toggle", "hide", "image", "fit", "palette", "undo", "redo"}:
                continue
            if isinstance(button, ToolIcon):
                button.selected = mapping.get(key, False)
        for key, rgba in INK_COLORS:
            dot = self.color_dots.get(key)
            if dot is None:
                continue
            rgb = tuple(app.current_color[:3])
            dot.selected = drawing and rgb == tuple(rgba[:3])

    def apply_orientation(self, *_args: Any) -> None:
        self._fit_workspace()

    def dock_notes(self) -> None:
        work_x, work_y = float(self.workspace.x), float(self.workspace.y)
        work_w, work_h = float(self.workspace.width), float(self.workspace.height)
        notes_w = 0.0
        if self.notes_expanded:
            notes_w = min(dp(360), max(dp(170), work_w * 0.30))
            self.notes_canvas.opacity = 1
            self.notes_canvas.disabled = False
        else:
            self.notes_canvas.opacity = 0
            self.notes_canvas.disabled = True
        self.notes_canvas.size = (notes_w, max(1.0, work_h))
        self.notes_canvas.pos = (work_x, work_y)
        self.pdf_canvas.size = (max(1.0, work_w - notes_w), max(1.0, work_h))
        self.pdf_canvas.pos = (work_x + notes_w, work_y)
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
        self._fit_workspace()
        Clock.schedule_once(lambda _dt: App.get_running_app().clamp_view(), 0)

    def refresh_title(self) -> None:
        app = App.get_running_app()
        self.title_button.text = mixed_markup(f"> {app.document_title}")

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
        try:
            apply_ui_font()
        except Exception:
            pass
        Window.clearcolor = LETTERBOX
        Window.softinput_mode = "pan"
        self.title = "Samsung Notes Companion"
        self.tool_mode: str = "none"
        self.current_color: Rgba = COLOR_BLACK
        self.ink_width: float = 2.5
        self.ink_opacity: float = 1.0
        self.dash_length: float = DASH_LENGTH
        self.dash_gap: float = GAP_LENGTH
        self.is_eraser: bool = False
        self.is_dashed: bool = False
        self._preview_token: int = 0
        self._preview_renderer: Any = None
        self._preview_pfd: Any = None
        self._preview_queue: List[int] = []
        self._preview_busy: bool = False
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
        self._pdf_page_index: int = 0
        self._pdf_page_count: int = 0
        self._page_strokes: Dict[int, List[StrokeRecord]] = {}
        self._notes_strokes: Dict[int, List[StrokeRecord]] = {}
        self._pending_save: Optional[Tuple[str, str]] = None
        self._stylus_listener: Any = None
        self._history_role: str = "pdf"
        self._clipboard: List[StrokeRecord] = []
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
            root._fit_workspace()

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
            height=dp(48),
            input_type="text",
            write_tab=False,
        )
        if _HEBREW_FONT_READY:
            field.font_name = "HebrewFont"
        elif _LATIN_FONT_READY:
            field.font_name = "LatinFont"
        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        buttons = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        popup = Popup(title="", content=body, size_hint=(0.88, 0.42), auto_dismiss=False)

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
        popup.bind(on_open=lambda *_args: focus_system_keyboard(field))
        popup.open()
        apply_hebrew_ui(popup, "שם המסמך")
        focus_system_keyboard(field)

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
                Toast.makeText(activity, String(message), Toast.LENGTH_LONG).show()

            _toast()
        except Exception:
            pass

    def _notify_long(self, message: str) -> None:
        self._notify(message)
        field = TextInput(text=message, readonly=True, multiline=True)
        set_hebrew_font(field)
        popup = Popup(title="", content=field, size_hint=(0.94, 0.6))
        popup.open()
        apply_hebrew_ui(popup, "שגיאה")

    def _on_key_down(self, *_args: Any, **kwargs: Any) -> bool:
        key = _args[1] if len(_args) > 1 else None
        modifiers = _args[4] if len(_args) > 4 else []
        code = key[0] if isinstance(key, (tuple, list)) else key
        name = key[1] if isinstance(key, (tuple, list)) and len(key) > 1 else ""
        mods = {str(item).lower() for item in (modifiers or [])}
        if "ctrl" in mods or "meta" in mods:
            if name in {"c", "C"} or str(getattr(_args[3] if len(_args) > 3 else "", "")).lower() == "c":
                self.copy_selection()
                return True
            if name in {"v", "V"} or str(getattr(_args[3] if len(_args) > 3 else "", "")).lower() == "v":
                self.paste_selection()
                return True
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
            elif request_code == IMAGE_REQUEST:
                self._open_android_image_uri(uri)
            elif request_code == SAVE_REQUEST and self._pending_save:
                self._write_android_uri(uri, *self._pending_save)
                self._pending_save = None
        except Exception as exc:
            self._notify(f"שגיאה בפתיחת הקובץ: {exc}")

    def _copy_java_stream(self, source: Any, path: str) -> None:
        from jnius import autoclass

        dest = autoclass("java.io.FileOutputStream")(path)
        try:
            autoclass("android.os.FileUtils").copy(source, dest)
            dest.flush()
            dest.close()
            return
        except Exception:
            try:
                dest.close()
            except Exception:
                pass
        with open(path, "wb") as out:
            while True:
                value = int(source.read())
                if value < 0:
                    break
                out.write(bytes([value & 0xFF]))

    def _copy_uri_to_temp(self, uri: Any, suffix: str) -> str:
        from jnius import autoclass

        resolver = self._android_activity().getContentResolver()
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        handle.close()
        copied = False
        try:
            pfd = resolver.openFileDescriptor(uri, "r")
            source = autoclass("java.io.FileInputStream")(pfd.getFileDescriptor())
            self._copy_java_stream(source, handle.name)
            source.close()
            pfd.close()
            copied = os.path.getsize(handle.name) > 4
        except Exception:
            copied = False
        if not copied:
            source = resolver.openInputStream(uri)
            if source is None:
                raise OSError("openInputStream returned null")
            self._copy_java_stream(source, handle.name)
            source.close()
        if os.path.getsize(handle.name) < 5:
            raise OSError("failed to copy the selected file")
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

    def _bitmap_to_file(self, bitmap: Any, jpeg: bool = False) -> Optional[str]:
        from jnius import autoclass

        suffix = ".jpg" if jpeg else ".png"
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        handle.close()
        stream = autoclass("java.io.FileOutputStream")(handle.name)
        fmt = autoclass("android.graphics.Bitmap$CompressFormat")
        if jpeg:
            ok = bool(bitmap.compress(fmt.JPEG, 70, stream))
        else:
            ok = bool(bitmap.compress(fmt.PNG, 100, stream))
        stream.close()
        if not ok:
            return None
        return handle.name

    def _call_page_render(self, page: Any, bitmap: Any) -> None:
        from jnius import autoclass

        page_cls = autoclass("android.graphics.pdf.PdfRenderer$Page")
        mode = int(getattr(page_cls, "RENDER_MODE_FOR_DISPLAY", 1))
        width = int(bitmap.getWidth())
        height = int(bitmap.getHeight())
        clip = autoclass("android.graphics.Rect")(0, 0, width, height)
        matrix = autoclass("android.graphics.Matrix")()
        page_w = max(1.0, float(page.getWidth()))
        page_h = max(1.0, float(page.getHeight()))
        matrix.setScale(width / page_w, height / page_h)
        page.render(bitmap, clip, matrix, mode)

    def _render_opened_page(self, page: Any, for_export: bool = False) -> Optional[str]:
        from jnius import autoclass

        page_w = max(1.0, float(page.getWidth()))
        page_h = max(1.0, float(page.getHeight()))
        if for_export:
            scale = min(PDF_RENDER_SCALE, PDF_RENDER_MAX_SIDE / max(page_w, page_h))
        else:
            cap = PDF_PREVIEW_MAX_SIDE
            try:
                cap = min(cap, max(720.0, float(Window.width) * 1.1))
            except Exception:
                pass
            scale = min(PDF_PREVIEW_SCALE, cap / max(page_w, page_h))
        width = max(1, int(round(page_w * scale)))
        height = max(1, int(round(page_h * scale)))
        bitmap_cls = autoclass("android.graphics.Bitmap")
        config = autoclass("android.graphics.Bitmap$Config")
        bitmap = bitmap_cls.createBitmap(width, height, config.ARGB_8888)
        canvas = autoclass("android.graphics.Canvas")(bitmap)
        paint = autoclass("android.graphics.Paint")()
        paint.setARGB(255, 255, 255, 255)
        canvas.drawRect(0.0, 0.0, float(width), float(height), paint)
        self._call_page_render(page, bitmap)
        path = self._bitmap_to_file(bitmap, jpeg=not for_export)
        try:
            bitmap.recycle()
        except Exception:
            pass
        return path

    def _render_pdf_pages(self) -> Tuple[List[str], str]:
        from jnius import autoclass

        pfd = self._open_pdf_pfd()
        renderer = autoclass("android.graphics.pdf.PdfRenderer")(pfd)
        paths: List[str] = []
        error = ""
        try:
            count = int(renderer.getPageCount())
            self._pdf_page_count = max(0, count)
            if count <= 0:
                return [], "PdfRenderer reported 0 pages"
            for index in range(count):
                page = renderer.openPage(int(index))
                try:
                    path = self._render_opened_page(page, for_export=False)
                    if path:
                        paths.append(path)
                except Exception as exc:
                    error = f"page {index}/{count}: {exc}"
                page.close()
        finally:
            renderer.close()
            pfd.close()
        return paths, error

    def _render_pdf_page(self, index: int, uri: Any = None) -> Optional[str]:
        try:
            from jnius import autoclass

            pfd = self._open_pdf_pfd(uri)
            renderer = autoclass("android.graphics.pdf.PdfRenderer")(pfd)
            page = renderer.openPage(int(index))
            path = self._render_opened_page(page, for_export=True)
            page.close()
            renderer.close()
            pfd.close()
            return path
        except Exception:
            return None

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

    def _close_preview_renderer(self) -> None:
        self._preview_queue = []
        self._preview_busy = False
        renderer = getattr(self, "_preview_renderer", None)
        pfd = getattr(self, "_preview_pfd", None)
        self._preview_renderer = None
        self._preview_pfd = None
        if renderer is not None:
            try:
                renderer.close()
            except Exception:
                pass
        if pfd is not None:
            try:
                pfd.close()
            except Exception:
                pass

    def _load_notebook(self, uri: Any = None) -> None:
        if uri is not None and (not self.pdf_path or str(self.pdf_path).startswith("content:")):
            self.pdf_path = self._copy_uri_to_temp(uri, ".pdf")
        self._preview_token += 1
        self._preview_opened_msg = False
        self._close_preview_renderer()
        try:
            from jnius import autoclass

            pfd = self._open_pdf_pfd()
            renderer = autoclass("android.graphics.pdf.PdfRenderer")(pfd)
            count = int(renderer.getPageCount())
        except Exception as exc:
            self._pdf_page_count = 0
            self.page_count = 1
            self.root_layout.pdf_canvas.set_blank_notebook(1, self.page_width, self.page_height)
            self.root_layout.notes_canvas.set_blank_notebook(1)
            self._notify_long(f"לא ניתן לפתוח את ה-PDF: {exc}")
            return
        if count <= 0:
            renderer.close()
            pfd.close()
            self._notify_long("PdfRenderer reported 0 pages")
            return
        try:
            page = renderer.openPage(0)
            self.page_width = max(1.0, float(page.getWidth()))
            self.page_height = max(1.0, float(page.getHeight()))
            page.close()
        except Exception:
            pass
        self._pdf_page_count = count
        self.page_count = count
        self._preview_pfd = pfd
        self._preview_renderer = renderer
        self.root_layout.pdf_canvas.set_blank_notebook(count, self.page_width, self.page_height)
        self.root_layout.notes_canvas.set_blank_notebook(count)
        self.root_layout.sync_notes_page_size()
        self.root_layout.pdf_canvas.load_strokes(self._pages_to_stacked(self._page_strokes))
        self.root_layout.notes_canvas.load_strokes(self._pages_to_stacked(self._notes_strokes))
        self.root_layout.set_status(f"טוען 1/{count}")
        self.request_visible_pages()

    def request_visible_pages(self) -> None:
        if self._preview_renderer is None:
            return
        canvas = self.root_layout.pdf_canvas
        first, last = canvas._visible_pages()
        count = int(self._pdf_page_count or 0)
        if count <= 0:
            return
        keep = list(range(max(0, first - 1), min(count, last + 2)))
        canvas.evict_page_textures(keep)
        textures = canvas._page_textures
        missing: List[int] = []
        for index in keep:
            while len(textures) <= index:
                textures.append(None)
            if textures[index] is None:
                missing.append(index)
        if missing:
            self._enqueue_preview(missing)

    def _enqueue_preview(self, indices: Sequence[int]) -> None:
        for index in indices:
            idx = int(index)
            if idx not in self._preview_queue:
                self._preview_queue.append(idx)
        if not self._preview_busy:
            self._preview_busy = True
            Clock.schedule_once(self._pump_preview, 0)

    def _pump_preview(self, *_args: Any) -> None:
        if self._preview_renderer is None:
            self._preview_busy = False
            self._preview_queue = []
            return
        if self._pointers:
            Clock.schedule_once(self._pump_preview, 0.12)
            return
        textures = self.root_layout.pdf_canvas._page_textures
        index: Optional[int] = None
        while self._preview_queue:
            candidate = self._preview_queue.pop(0)
            if candidate >= len(textures) or textures[candidate] is None:
                index = candidate
                break
        if index is None:
            self._preview_busy = False
            if not getattr(self, "_preview_opened_msg", False):
                self._preview_opened_msg = True
                self._notify(f"PDF נפתח לכתיבה: {self.document_title}")
            else:
                self.root_layout.set_page_status(0, self._pdf_page_count)
            return
        path = None
        try:
            page = self._preview_renderer.openPage(int(index))
            try:
                path = self._render_opened_page(page, for_export=False)
            finally:
                page.close()
            if path:
                self.root_layout.pdf_canvas.set_page_image_at(index, path, self._pdf_page_count)
                if index == 0:
                    self.root_layout.sync_notes_page_size()
            self.root_layout.set_status(f"טוען {index + 1}/{self._pdf_page_count}")
        except Exception as exc:
            if index == 0:
                self._notify_long(f"לא ניתן לרנדר את ה-PDF: {exc}")
        finally:
            if path:
                try:
                    os.unlink(path)
                except Exception:
                    pass
        Clock.schedule_once(self._pump_preview, 0.06)

    def _uri_display_name(self, uri: Any) -> str:
        try:
            from jnius import autoclass

            resolver = self._android_activity().getContentResolver()
            columns = autoclass("android.provider.OpenableColumns")
            cursor = resolver.query(uri, [columns.DISPLAY_NAME], None, None, None)
            if cursor is not None:
                try:
                    if cursor.moveToFirst():
                        name = str(cursor.getString(0) or "")
                        if name:
                            return name
                finally:
                    cursor.close()
        except Exception:
            pass
        return str(uri.getLastPathSegment() or uri.toString())

    def _bytes_look_like_pdf(self, path: str) -> bool:
        try:
            with open(path, "rb") as handle:
                return handle.read(5).startswith(b"%PDF")
        except Exception:
            return False

    def _uri_is_pdf(self, uri: Any) -> bool:
        try:
            mime = str(self._android_activity().getContentResolver().getType(uri) or "")
            if "pdf" in mime.lower():
                return True
        except Exception:
            pass
        name = str(uri.toString()).lower()
        return name.endswith(".pdf") or "/pdf" in name

    def _open_local_pdf(self, path: str, display: str) -> None:
        self.pdf_path = path
        self._page_strokes = {}
        self._notes_strokes = {}
        self._pdf_page_index = 0
        self._reset_view()
        self._pdf_page_count = 0
        self.root_layout.pdf_canvas.load_strokes([])
        self.root_layout.notes_canvas.load_strokes([])
        self._set_title_from_filename(display)
        self._notify(f"טוען PDF: {display}")
        self._load_notebook()

    def _open_android_uri(self, uri: Any) -> None:
        display = self._uri_display_name(uri)
        try:
            path = self._copy_uri_to_temp(uri, ".bin")
        except Exception as exc:
            self._notify(f"לא ניתן להעתיק את הקובץ: {exc}")
            return
        lower = display.lower()
        if (
            self._bytes_look_like_pdf(path)
            or lower.endswith(".pdf")
            or self._uri_is_pdf(uri)
        ):
            try:
                self._open_local_pdf(path, display)
            except Exception as exc:
                self._notify(f"לא ניתן להציג את ה-PDF: {exc}")
            return
        if self._path_is_image(path, display):
            try:
                self._place_imported_image(path)
                self._notify(f"תמונה נוספה: {display}")
            except Exception as exc:
                self._notify(f"לא ניתן לייבא את התמונה: {exc}")
            return
        try:
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
        from PIL import Image, ImageDraw

        width, height = image.size
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        drawer = ImageDraw.Draw(overlay)
        scale_x = width / page_w if page_w > 1 else 1.0
        scale_y = height / page_h if page_h > 1 else 1.0
        for record in strokes:
            if record.get("kind") == "image":
                rect = record.get("rect") or [0.0, 0.0, 0.0, 0.0]
                path = str(record.get("path") or "")
                if not path or not os.path.isfile(path):
                    continue
                try:
                    stamp = _image_rgb_on_white(path).convert("RGBA")
                    u0, v0, u1, v1 = [float(v) for v in (record.get("crop") or [0.0, 0.0, 1.0, 1.0])[:4]]
                    pw, ph = stamp.size
                    left = int(max(0, min(pw - 1, u0 * pw)))
                    right = int(max(left + 1, min(pw, u1 * pw)))
                    top = int(max(0, min(ph - 1, (1.0 - v1) * ph)))
                    bottom = int(max(top + 1, min(ph, (1.0 - v0) * ph)))
                    stamp = stamp.crop((left, top, right, bottom))
                    sized = stamp.resize(
                        (
                            max(1, int(float(rect[2]) * scale_x)),
                            max(1, int(float(rect[3]) * scale_y)),
                        )
                    )
                    angle = float(record.get("angle") or 0.0)
                    if abs(angle) > 0.05:
                        sized = sized.rotate(-angle, expand=True, resample=Image.BICUBIC)
                    cx = (float(rect[0]) + float(rect[2]) / 2.0) * scale_x
                    cy = height - (float(rect[1]) + float(rect[3]) / 2.0) * scale_y
                    box = (
                        int(cx - sized.size[0] / 2.0),
                        int(cy - sized.size[1] / 2.0),
                    )
                    overlay.paste(sized, box, sized)
                except Exception:
                    pass
                continue
            if record.get("kind") == "text":
                try:
                    canvas = self.root_layout.pdf_canvas
                    texture = canvas._text_texture(record)
                    if texture is None:
                        continue
                    raw = Image.frombytes("RGBA", tuple(texture.size), bytes(texture.pixels))
                    stamp = raw.transpose(Image.FLIP_TOP_BOTTOM)
                    rect = record.get("rect") or [0.0, 0.0, 1.0, 1.0]
                    sized = stamp.resize(
                        (
                            max(1, int(float(rect[2]) * scale_x)),
                            max(1, int(float(rect[3]) * scale_y)),
                        )
                    )
                    angle = float(record.get("angle") or 0.0)
                    if abs(angle) > 0.05:
                        sized = sized.rotate(-angle, expand=True, resample=Image.BICUBIC)
                    cx = (float(rect[0]) + float(rect[2]) / 2.0) * scale_x
                    cy = height - (float(rect[1]) + float(rect[3]) / 2.0) * scale_y
                    box = (
                        int(cx - sized.size[0] / 2.0),
                        int(cy - sized.size[1] / 2.0),
                    )
                    overlay.paste(sized, box, sized)
                except Exception:
                    pass
                continue
            points = record.get("points") or []
            if len(points) < 2:
                continue
            color = record.get("color", COLOR_BLACK)
            alpha = int(max(0.0, min(1.0, float(color[3] if len(color) > 3 else 1.0))) * 255)
            fill = tuple(max(0, min(255, int(c * 255))) for c in color[:3]) + (alpha,)
            stroke_w = max(1, int(record.get("width", 2) * max(scale_x, scale_y)))
            xy = [
                (float(p[0]) * scale_x, height - float(p[1]) * scale_y) for p in points
            ]
            if record.get("dashed"):
                dashes = dashed_polylines(
                    points,
                    float(record.get("dash_len", DASH_LENGTH)),
                    float(record.get("gap_len", GAP_LENGTH)),
                )
                for dash in dashes:
                    pair = [
                        (dash[i] * scale_x, height - dash[i + 1] * scale_y)
                        for i in range(0, len(dash) - 1, 2)
                    ]
                    if len(pair) >= 2:
                        drawer.line(pair, fill=fill, width=stroke_w)
            else:
                drawer.line(xy, fill=fill, width=stroke_w)
        composed = Image.alpha_composite(image.convert("RGBA"), overlay)
        image.paste(composed.convert(image.mode))

    def _texture_to_rgb(self, texture: Any) -> Optional[Any]:
        from PIL import Image

        try:
            image = Image.frombytes("RGBA", tuple(texture.size), bytes(texture.pixels))
            return _image_rgb_on_white(image)
        except Exception:
            return None

    def _export_document_page(self, index: int) -> Optional[Any]:
        if self.pdf_path and is_android():
            preview = self._render_pdf_page(index)
            if preview:
                return _image_rgb_on_white(preview)
        textures = getattr(self.root_layout.pdf_canvas, "_page_textures", [])
        if 0 <= index < len(textures) and textures[index] is not None:
            return self._texture_to_rgb(textures[index])
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
        intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
        intent.addCategory(Intent.CATEGORY_OPENABLE)
        intent.setType("*/*")
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        intent.addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
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
            filters=[
                "*.pdf",
                "*.png",
                "*.jpg",
                "*.jpeg",
                "*.webp",
                "*.notes",
                "*.json",
                "*.sdocx",
                "*",
            ],
        )
        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        buttons = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        popup = Popup(title="", content=body, size_hint=(0.94, 0.94))

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
        apply_hebrew_ui(popup, "פתיחת קובץ")

    def _open_local_path(self, path: str) -> None:
        lower = path.lower()
        if lower.endswith(".pdf") or self._bytes_look_like_pdf(path):
            if is_android():
                try:
                    self._open_local_pdf(path, os.path.basename(path))
                except Exception as exc:
                    self._notify(f"לא ניתן להציג את ה-PDF: {exc}")
                return
            self.pdf_path = path
            self._set_title_from_filename(path)
            self._notify(f"נבחר PDF: {os.path.basename(path)}")
            return
        if self._path_is_image(path, path):
            try:
                self._place_imported_image(path)
                self._notify(f"תמונה נוספה: {os.path.basename(path)}")
            except Exception as exc:
                self._notify(f"לא ניתן לייבא את התמונה: {exc}")
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
        popup = Popup(title="", content=body, size_hint=(0.94, 0.94))

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
        apply_hebrew_ui(popup, "שמירה בשם")

    def _write_local_path(self, path: str, extension: str) -> None:
        data = self._document_bytes(extension)
        if extension in {".png", ".pdf", ".sdocx"}:
            with open(path, "wb") as handle:
                handle.write(data)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(data.decode("utf-8"))
        self._notify(f"נשמר: {path}")

    def _path_is_image(self, path: str, display: str = "") -> bool:
        name = f"{display} {path}".lower()
        if any(name.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
            return True
        try:
            with open(path, "rb") as handle:
                head = handle.read(12)
            return head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8") or head.startswith(b"RIFF")
        except Exception:
            return False

    def _place_imported_image(self, path: str) -> None:
        from PIL import Image

        canvas = self.root_layout.pdf_canvas
        image = _image_rgb_on_white(Image.open(path))
        stored = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        stored.close()
        image.save(stored.name, "PNG")
        page_w = max(1.0, float(self.page_width))
        page_h = max(1.0, float(self.page_height))
        iw, ih = image.size
        target_w = page_w * 0.45
        scale = target_w / max(1.0, float(iw))
        tw, th = target_w, float(ih) * scale
        if th > page_h * 0.5:
            scale = (page_h * 0.5) / max(1.0, float(ih))
            tw, th = float(iw) * scale, page_h * 0.5
        first, _last = canvas._visible_pages()
        page_y = canvas._page_origin_y(first, page_h)
        x = (page_w - tw) / 2.0
        y = page_y + (page_h - th) / 2.0
        canvas.push_history()
        canvas.strokes.append(
            {
                "kind": "image",
                "path": stored.name,
                "rect": [x, y, tw, th],
                "crop": [0.0, 0.0, 1.0, 1.0],
                "angle": 0.0,
                "points": [[x, y], [x + tw, y + th]],
                "color": [0.0, 0.0, 0.0, 1.0],
                "width": 1.0,
                "dashed": False,
                "eraser": False,
            }
        )
        canvas.selected_ids = [len(canvas.strokes) - 1]
        self.tool_mode = "lasso"
        self.is_eraser = False
        self.is_dashed = False
        canvas.redraw_all()
        self.root_layout.refresh_tool_styles()
        self._notify("גררו להזזה, פינות לשינוי גודל, קצוות כתומים לחיתוך")

    def _open_android_image_uri(self, uri: Any) -> None:
        display = self._uri_display_name(uri)
        suffix = ".png"
        lower = display.lower()
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
            if lower.endswith(ext):
                suffix = ext
                break
        path = self._copy_uri_to_temp(uri, suffix)
        self._place_imported_image(path)
        self._notify(f"תמונה נוספה: {display}")

    def import_image(self, *_args: Any) -> None:
        if is_android():
            try:
                from jnius import autoclass

                Intent = autoclass("android.content.Intent")
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.setType("image/*")
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                self._launch_android_intent(intent, IMAGE_REQUEST)
                return
            except Exception as exc:
                self._notify(f"לא ניתן לפתוח תמונה: {exc}")
                return
        chooser = FileChooserListView(
            path=self._desktop_start_dir(),
            filters=["*.png", "*.jpg", "*.jpeg", "*.webp", "*"],
        )
        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        buttons = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        popup = Popup(title="", content=body, size_hint=(0.94, 0.94))

        def _load(_instance: Button) -> None:
            if chooser.selection:
                try:
                    self._place_imported_image(chooser.selection[0])
                    self._notify(f"תמונה נוספה: {os.path.basename(chooser.selection[0])}")
                except Exception as exc:
                    self._notify(f"לא ניתן לייבא את התמונה: {exc}")
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
        apply_hebrew_ui(popup, "ייבוא תמונה")

    def reset_view(self, *_args: Any) -> None:
        self._reset_view()
        self._notify("תצוגה 100%")

    def set_custom_color(self, rgb: Sequence[float], *_args: Any) -> None:
        red, green, blue = [max(0.0, min(1.0, float(channel))) for channel in list(rgb)[:3]]
        self.current_color = (red, green, blue, 1.0)
        if self.tool_mode in {"none", "eraser"}:
            self.tool_mode = "pen"
        self.is_eraser = False
        self.root_layout.refresh_tool_styles()

    def open_color_picker(self, *_args: Any) -> None:
        picker = InkColorPicker(self.current_color)
        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        buttons = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        popup = Popup(title="", content=body, size_hint=(0.84, 0.64))

        def _ok(_btn: Button) -> None:
            self.set_custom_color(picker.rgb())
            popup.dismiss()

        ok_btn = Button(text="אישור")
        cancel_btn = Button(text="ביטול")
        ok_btn.bind(on_release=_ok)
        cancel_btn.bind(on_release=lambda _btn: popup.dismiss())
        buttons.add_widget(ok_btn)
        buttons.add_widget(cancel_btn)
        body.add_widget(picker)
        body.add_widget(buttons)
        popup.open()
        apply_hebrew_ui(popup, "בחירת צבע")

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
        popup = Popup(title="", content=body, size_hint=(0.75, 0.7))
        for ext, mime, title in SAVE_TYPES:
            button = Button(text=title, size_hint_y=None, height=dp(44))

            def _pick(_btn: Button, extension: str = ext, media: str = mime) -> None:
                popup.dismiss()
                self._start_android_save(extension, media)

            button.bind(on_release=_pick)
            body.add_widget(button)
        popup.open()
        apply_hebrew_ui(popup, "שמירה בשם")

    def _history_canvas(self) -> SPenAnnotationCanvas:
        if getattr(self, "_history_role", "pdf") == "notes":
            return self.root_layout.notes_canvas
        return self.root_layout.pdf_canvas

    def undo(self, *_args: Any) -> None:
        first = self._history_canvas()
        second = (
            self.root_layout.notes_canvas
            if first is self.root_layout.pdf_canvas
            else self.root_layout.pdf_canvas
        )
        if first.undo() or second.undo():
            self.root_layout.sync_floating_tools()
            self._notify("בוטל")
            return
        self._notify("אין מה לבטל")

    def redo(self, *_args: Any) -> None:
        first = self._history_canvas()
        second = (
            self.root_layout.notes_canvas
            if first is self.root_layout.pdf_canvas
            else self.root_layout.pdf_canvas
        )
        if first.redo() or second.redo():
            self.root_layout.sync_floating_tools()
            self._notify("בוצע שוב")
            return
        self._notify("אין מה לבצע שוב")

    def select_lasso(self, *_args: Any) -> None:
        self.tool_mode = "lasso"
        self.is_eraser = False
        self.is_dashed = False
        self.root_layout.set_shapes_open(False)
        self.root_layout.refresh_tool_styles()

    def select_text(self, *_args: Any) -> None:
        self.tool_mode = "text"
        self.is_eraser = False
        self.is_dashed = False
        self.root_layout.set_shapes_open(False)
        self.root_layout.refresh_tool_styles()
        self._notify("לחצו על הדף כדי להוסיף טקסט")

    def prompt_new_text(self, canvas: SPenAnnotationCanvas, doc: Point) -> None:
        self._prompt_text(canvas, doc, None)

    def prompt_text_record(self, canvas: SPenAnnotationCanvas, index: int) -> None:
        record = canvas.strokes[index]
        rect = record.get("rect") or [0.0, 0.0, 1.0, 1.0]
        self._prompt_text(canvas, (float(rect[0]), float(rect[1])), index)

    def _prompt_text(
        self, canvas: SPenAnnotationCanvas, doc: Point, existing: Optional[int]
    ) -> None:
        if is_android():
            try:
                self.root_layout.hide_text_overlay()
                self._show_android_text_dialog(canvas, doc, existing)
                return
            except Exception:
                pass
        self.root_layout.show_text_overlay(canvas, doc, existing)

    def _ensure_android_text_listeners(self) -> None:
        if getattr(self, "_android_text_ui_ver", 0) == 6:
            return
        from jnius import PythonJavaClass, java_method

        app = self

        class TextTap(PythonJavaClass):
            __javacontext__ = "app"
            __javainterfaces__ = ["android.view.View$OnClickListener"]

            def __init__(self, ok: bool) -> None:
                super().__init__()
                self.ok = ok

            @java_method("(Landroid/view/View;)V")
            def onClick(self, _view: Any) -> None:
                app._capture_android_text(self.ok)

        class DialogShow(PythonJavaClass):
            __javacontext__ = "app"
            __javainterfaces__ = ["android.content.DialogInterface$OnShowListener"]

            @java_method("(Landroid/content/DialogInterface;)V")
            def onShow(self, _dialog: Any) -> None:
                try:
                    edit = getattr(app, "_android_edit", None)
                    if edit is not None:
                        edit.requestFocus()
                except Exception:
                    pass

        class DialogDismiss(PythonJavaClass):
            __javacontext__ = "app"
            __javainterfaces__ = ["android.content.DialogInterface$OnDismissListener"]

            @java_method("(Landroid/content/DialogInterface;)V")
            def onDismiss(self, _dialog: Any) -> None:
                Clock.schedule_once(lambda _dt: app._restore_kivy_softinput(), 0)
                if getattr(app, "_android_dialog_result", None) is None:
                    app._queue_android_text_result(False, "")

        self._android_tap_ok = TextTap(True)
        self._android_tap_cancel = TextTap(False)
        try:
            self._android_show = DialogShow()
        except Exception:
            self._android_show = None
        try:
            self._android_dismiss = DialogDismiss()
        except Exception:
            self._android_dismiss = None
        self._android_text_ui_ver = 6

    def _queue_android_text_result(self, accept: bool, text: str) -> None:
        if getattr(self, "_android_dialog_result", None) is not None:
            return
        self._android_dialog_result = (bool(accept), str(text or ""))

    def _pause_kivy_softinput(self) -> None:
        self._prev_softinput = getattr(Window, "softinput_mode", "")
        try:
            Window.softinput_mode = ""
        except Exception:
            pass
        try:
            Window.release_all_keyboards()
        except Exception:
            try:
                Window.release_keyboard()
            except Exception:
                pass

    def _restore_kivy_softinput(self) -> None:
        try:
            Window.softinput_mode = str(getattr(self, "_prev_softinput", None) or "pan")
        except Exception:
            pass

    def _poll_android_text_dialog(self, _dt: float) -> bool:
        result = getattr(self, "_android_dialog_result", None)
        if result is None:
            self._android_poll_ticks = int(getattr(self, "_android_poll_ticks", 0)) + 1
            return self._android_poll_ticks < 600
        self._android_dialog_result = None
        accept, text = result
        Clock.schedule_once(lambda _t, ok=accept, value=text: self._finish_android_text(value, ok), 0)
        return False

    def _capture_android_text(self, accept: bool) -> None:
        field = ""
        try:
            field = _java_chars(self._android_edit.getText())
        except Exception:
            field = ""
        text = field
        try:
            dialog = getattr(self, "_android_dialog", None)
            if dialog is not None:
                dialog.dismiss()
        except Exception:
            pass
        self._queue_android_text_result(accept, text)

    def _show_android_text_dialog(
        self, canvas: SPenAnnotationCanvas, doc: Point, existing: Optional[int]
    ) -> None:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass

        initial = ""
        font_size = 28.0
        if existing is not None and 0 <= existing < len(canvas.strokes):
            record = canvas.strokes[existing]
            initial = str(record.get("text") or "")
            font_size = float(record.get("font_size") or 28.0)

        self._ensure_android_text_listeners()
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        Builder = autoclass("android.app.AlertDialog$Builder")
        EditText = autoclass("android.widget.EditText")
        InputType = autoclass("android.text.InputType")
        View = autoclass("android.view.View")
        String = autoclass("java.lang.String")
        Gravity = autoclass("android.view.Gravity")
        LinearLayout = autoclass("android.widget.LinearLayout")
        Button = autoclass("android.widget.Button")
        EditorInfo = autoclass("android.view.inputmethod.EditorInfo")
        Context = autoclass("android.content.Context")
        InputMethodManager = autoclass("android.view.inputmethod.InputMethodManager")
        density = float(activity.getResources().getDisplayMetrics().density)
        pad = int(18 * density)

        self._android_text_target = (canvas, doc, existing, font_size)
        self._android_dialog_result = None
        self._android_dialog_visible = False
        self._pause_kivy_softinput()
        self._android_poll_ticks = 0
        Clock.unschedule(self._poll_android_text_dialog)
        Clock.schedule_interval(self._poll_android_text_dialog, 0.12)

        @run_on_ui_thread
        def _open() -> None:
            try:
                box = LinearLayout(activity)
                box.setOrientation(LinearLayout.VERTICAL)
                box.setPadding(pad, pad, pad, pad)
                try:
                    box.setLayoutDirection(View.LAYOUT_DIRECTION_LTR)
                except Exception:
                    pass

                edit = EditText(activity)
                edit.setText(String(initial))
                edit.setHint(String("כתבו טקסט"))
                edit.setInputType(
                    InputType.TYPE_CLASS_TEXT
                    | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                    | InputType.TYPE_TEXT_FLAG_IME_MULTI_LINE
                )
                try:
                    edit.setImeOptions(EditorInfo.IME_FLAG_NO_ENTER_ACTION)
                except Exception:
                    pass
                edit.setMinLines(4)
                edit.setGravity(Gravity.TOP | Gravity.LEFT)
                edit.setFocusable(True)
                edit.setFocusableInTouchMode(True)
                try:
                    edit.setHorizontallyScrolling(False)
                except Exception:
                    pass
                try:
                    edit.setLayoutDirection(View.LAYOUT_DIRECTION_LTR)
                    edit.setTextDirection(View.TEXT_DIRECTION_LTR)
                    edit.setTextAlignment(View.TEXT_ALIGNMENT_GRAVITY)
                except Exception:
                    pass

                buttons = LinearLayout(activity)
                buttons.setOrientation(LinearLayout.HORIZONTAL)
                buttons.setGravity(Gravity.END)
                cancel_btn = Button(activity)
                cancel_btn.setText(String("ביטול"))
                cancel_btn.setOnClickListener(self._android_tap_cancel)
                ok_btn = Button(activity)
                ok_btn.setText(String("אישור"))
                ok_btn.setOnClickListener(self._android_tap_ok)
                btn_params = LinearLayout.LayoutParams(-2, -2)
                buttons.addView(cancel_btn, btn_params)
                buttons.addView(ok_btn, btn_params)

                box.addView(edit, LinearLayout.LayoutParams(-1, -2))
                box.addView(buttons, LinearLayout.LayoutParams(-1, -2))

                builder = Builder(activity)
                builder.setTitle(String("טקסט"))
                builder.setView(box)
                builder.setCancelable(True)
                dialog = builder.create()
                if getattr(self, "_android_show", None) is not None:
                    dialog.setOnShowListener(self._android_show)
                if self._android_dismiss is not None:
                    dialog.setOnDismissListener(self._android_dismiss)
                win = dialog.getWindow()
                try:
                    win.getDecorView().setLayoutDirection(View.LAYOUT_DIRECTION_LTR)
                except Exception:
                    pass
                try:
                    LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
                    ViewGroup = autoclass("android.view.ViewGroup")
                    win.setGravity(Gravity.TOP | Gravity.FILL_HORIZONTAL)
                    win.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                    win.setSoftInputMode(
                        LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE
                        | LayoutParams.SOFT_INPUT_ADJUST_RESIZE
                    )
                except Exception:
                    pass
                self._android_edit = edit
                dialog.show()
                self._android_dialog = dialog
                self._android_dialog_visible = True
            except Exception:
                self._android_dialog_visible = False
                Clock.schedule_once(lambda _dt: self._restore_kivy_softinput(), 0)

        _open()

    def _finish_android_text(self, text: str, accept: bool) -> None:
        Clock.unschedule(self._poll_android_text_dialog)
        self._restore_kivy_softinput()
        target = getattr(self, "_android_text_target", None)
        self._android_text_target = None
        self._android_dialog_result = None
        if not accept or not target:
            return
        value = _plain_user_text(text)
        if not value:
            self._notify("לא נשמר טקסט")
            return
        canvas, doc, existing, font_size = target
        color = list(self.current_color)
        if len(color) < 4:
            color = list(color[:3]) + [1.0]
        canvas.place_text_record(doc, value, color, font_size=font_size, index=existing)
        self._history_role = canvas.view_role
        self.tool_mode = "lasso"
        self.root_layout.refresh_tool_styles()
        self.root_layout.sync_floating_tools()
        self._notify("הטקסט נוסף")

    def toggle_shape_menu(self, *_args: Any) -> None:
        self.root_layout.toggle_shape_menu()

    def copy_selection(self, *_args: Any) -> None:
        payload: List[StrokeRecord] = []
        for canvas in (self.root_layout.pdf_canvas, self.root_layout.notes_canvas):
            payload = canvas.copy_selected()
            if payload:
                self._history_role = canvas.view_role
                break
        if not payload:
            self._notify("אין בחירה להעתקה")
            return
        self._clipboard = payload
        self._notify("הועתק")

    def cut_selection(self, *_args: Any) -> None:
        payload: List[StrokeRecord] = []
        for canvas in (self.root_layout.pdf_canvas, self.root_layout.notes_canvas):
            payload = canvas.copy_selected()
            if payload:
                self._history_role = canvas.view_role
                break
        if not payload:
            self._notify("אין בחירה לגזירה")
            return
        self._clipboard = payload
        for canvas in (self.root_layout.pdf_canvas, self.root_layout.notes_canvas):
            if canvas.selected_ids and canvas.delete_selected():
                self._history_role = canvas.view_role
                self.root_layout.sync_floating_tools()
                break
        self._notify("נגזר")

    def delete_selection(self, *_args: Any) -> None:
        for canvas in (self.root_layout.pdf_canvas, self.root_layout.notes_canvas):
            if canvas.selected_ids and canvas.delete_selected():
                self._history_role = canvas.view_role
                self.root_layout.sync_floating_tools()
                self._notify("נמחק")
                return
        self._notify("אין בחירה למחיקה")

    def paste_selection(self, *_args: Any) -> None:
        if not self._clipboard:
            self._notify("אין מה להדביק")
            return
        canvas = self._history_canvas()
        canvas.paste_records(self._clipboard)
        self.tool_mode = "lasso"
        self.is_eraser = False
        self.is_dashed = False
        self.root_layout.refresh_tool_styles()
        self.root_layout.sync_floating_tools()
        self._notify("הודבק")

    def paste_at_chip(self, *_args: Any) -> None:
        target = getattr(self.root_layout, "_paste_target", None)
        if not self._clipboard or not target:
            self._notify("אין מה להדביק")
            return
        canvas, x, y = target
        canvas.paste_records_at(self._clipboard, canvas.to_doc(x, y))
        self._history_role = canvas.view_role
        self.tool_mode = "lasso"
        self.is_eraser = False
        self.is_dashed = False
        self.root_layout.refresh_tool_styles()
        self.root_layout.sync_floating_tools()
        self._notify("הודבק")

    def clear_tool(self, *_args: Any) -> None:
        self.tool_mode = "none"
        self.is_eraser = False
        self.root_layout.refresh_tool_styles()

    def select_pen(self, *_args: Any) -> None:
        self.tool_mode = "pen"
        self.is_eraser = False
        self.is_dashed = False
        self.root_layout.set_shapes_open(False)
        self.root_layout.refresh_tool_styles()

    def set_ink_width(self, value: float, *_args: Any) -> None:
        self.ink_width = max(1.0, min(16.0, float(value)))

    def set_ink_opacity(self, value: float, *_args: Any) -> None:
        self.ink_opacity = max(0.15, min(1.0, float(value)))

    def set_dash_gap(self, value: float, *_args: Any) -> None:
        self.dash_gap = max(4.0, min(40.0, float(value)))

    def select_shape(self, kind: str, *_args: Any) -> None:
        if kind not in SHAPE_TOOLS:
            return
        self.tool_mode = kind
        self.is_eraser = False
        self.root_layout.refresh_tool_styles()

    def set_ink_color(self, name: str, *_args: Any) -> None:
        color_map = dict(INK_COLORS)
        color = color_map.get(name, COLOR_BLACK)
        self.current_color = color
        if self.tool_mode in {"none", "eraser"}:
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
        self.is_dashed = True
        self.tool_mode = "pen"
        self.is_eraser = False
        self.root_layout.set_shapes_open(False)
        self.root_layout.refresh_tool_styles()

    def enable_eraser(self, *_args: Any) -> None:
        self.tool_mode = "eraser"
        self.is_eraser = True
        self.root_layout.set_shapes_open(False)
        self.root_layout.refresh_tool_styles()


if __name__ == "__main__":
    SamsungNotesCompanionApp().run()
