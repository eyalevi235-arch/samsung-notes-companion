"""Samsung Notes companion: toolbar, split canvases, and S Pen ink."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from kivy.app import App
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle
from kivy.input.motionevent import MotionEvent
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget

Point = Tuple[float, float]
Rgba = Tuple[float, float, float, float]
StrokeRecord = Dict[str, Any]

PDF_BG: Rgba = (1.0, 1.0, 1.0, 1.0)
NOTES_BG: Rgba = (1.0, 0.98, 0.82, 1.0)
SPEN_ERASER_WIDTH = 15.0
COLOR_BLACK: Rgba = (0.0, 0.0, 0.0, 1.0)
COLOR_RED: Rgba = (0.90, 0.22, 0.22, 1.0)
COLOR_BLUE: Rgba = (0.12, 0.23, 0.54, 1.0)


class SPenAnnotationCanvas(Widget):
    """Freehand canvas for S Pen and finger input on a solid page color."""

    ink_width = NumericProperty(2.5)
    min_width = NumericProperty(1.0)
    max_width = NumericProperty(6.0)
    bg_color = ListProperty([1.0, 1.0, 1.0, 1.0])

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.strokes: List[StrokeRecord] = []
        self.current_stroke: List[Point] = []
        self._bg_rect: Optional[Rectangle] = None
        self._bg_color_instr: Optional[Color] = None
        self._bind_canvas_background()
        self.bind(bg_color=self._sync_bg_color)

    def _bind_canvas_background(self) -> None:
        with self.canvas.before:
            self._bg_color_instr = Color(*self.bg_color)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_background, size=self._sync_background)

    def _sync_background(self, *_args: Any) -> None:
        if self._bg_rect is not None:
            self._bg_rect.pos = self.pos
            self._bg_rect.size = self.size

    def _sync_bg_color(self, *_args: Any) -> None:
        if self._bg_color_instr is not None:
            self._bg_color_instr.rgba = tuple(self.bg_color)

    def _line_width_for_touch(self, touch: MotionEvent) -> float:
        """Map S Pen pressure to stroke width when the device reports it."""
        if "pressure" in touch.profile:
            pressure = max(0.0, min(1.0, float(touch.pressure)))
            span = self.max_width - self.min_width
            return float(self.min_width + span * pressure)
        return float(self.ink_width)

    def _page_background(self) -> Rgba:
        return (
            float(self.bg_color[0]),
            float(self.bg_color[1]),
            float(self.bg_color[2]),
            float(self.bg_color[3]),
        )

    def _stroke_style(self, touch: MotionEvent) -> Tuple[Rgba, float, bool, bool]:
        """Resolve color/width from app state (toolbar eraser, ink, dashes)."""
        app = App.get_running_app()
        if bool(getattr(app, "is_eraser", False)):
            width = max(8.0, self._line_width_for_touch(touch) * 3.0)
            return self._page_background(), width, False, True

        color = tuple(getattr(app, "current_color", COLOR_BLACK))
        dashed = bool(getattr(app, "is_dashed", False))
        return color, self._line_width_for_touch(touch), dashed, False

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        touch.grab(self)
        if getattr(touch, "button", None) == "right":
            # S Pen hardware button: local eraser only, do not change app state.
            color = self._page_background()
            width = SPEN_ERASER_WIDTH
            dashed = False
            eraser = True
        else:
            color, width, dashed, eraser = self._stroke_style(touch)
        self.current_stroke = [(touch.x, touch.y)]
        touch.ud["stroke_meta"] = {
            "color": color,
            "width": width,
            "dashed": dashed,
            "eraser": eraser,
        }
        line_kwargs: Dict[str, Any] = {
            "points": [touch.x, touch.y],
            "width": width,
            "cap": "round",
            "joint": "round",
        }
        if dashed:
            line_kwargs["dash_length"] = 12
            line_kwargs["dash_offset"] = 6
        with self.canvas:
            Color(*color)
            touch.ud["line"] = Line(**line_kwargs)
        return True

    def on_touch_move(self, touch: MotionEvent) -> bool:
        if touch.grab_current is not self or "line" not in touch.ud:
            return super().on_touch_move(touch)

        self.current_stroke.append((touch.x, touch.y))
        touch.ud["line"].points += [touch.x, touch.y]
        return True

    def on_touch_up(self, touch: MotionEvent) -> bool:
        if touch.grab_current is not self:
            return super().on_touch_up(touch)

        touch.ungrab(self)
        meta = touch.ud.get("stroke_meta")
        if "line" in touch.ud and self.current_stroke and meta:
            record: StrokeRecord = {
                "points": [list(point) for point in self.current_stroke],
                "color": list(meta["color"]),
                "width": meta["width"],
                "dashed": meta["dashed"],
                "eraser": meta["eraser"],
            }
            self.strokes.append(record)
        self.current_stroke = []
        return True

    def serialized_strokes(self) -> List[StrokeRecord]:
        """Return a JSON-safe copy of completed strokes."""
        return json.loads(json.dumps(self.strokes))


class RootLayout(BoxLayout):
    """Light-themed shell: toolbar, PDF canvas, collapsible notes panel."""

    notes_expanded = BooleanProperty(True)

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("spacing", dp(6))
        kwargs.setdefault("padding", dp(6))
        super().__init__(**kwargs)

        self.pdf_canvas = SPenAnnotationCanvas(bg_color=list(PDF_BG))
        self.notes_canvas = SPenAnnotationCanvas(bg_color=list(NOTES_BG))
        self.side_panel = self._build_side_panel()
        self.add_widget(self._build_toolbar())
        self.add_widget(self._build_workspace())

    def _build_toolbar(self) -> BoxLayout:
        app = App.get_running_app()
        toolbar = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(48),
            spacing=dp(4),
        )
        actions: Sequence[Tuple[str, Any]] = (
            ("Open PDF", app.open_pdf),
            ("Save .notes", app.save_document),
            ("Black", app.set_color_black),
            ("Red", app.set_color_red),
            ("Blue", app.set_color_blue),
            ("Dashed line", app.toggle_dashed),
            ("Eraser", app.enable_eraser),
            ("Toggle Notes", self.toggle_notes),
        )
        for label, handler in actions:
            button = Button(
                text=label,
                background_color=(0.88, 0.88, 0.90, 1),
                color=(0.12, 0.12, 0.14, 1),
            )
            button.bind(on_release=handler)
            toolbar.add_widget(button)
        return toolbar

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

    def _build_workspace(self) -> BoxLayout:
        workspace = BoxLayout(orientation="horizontal", spacing=dp(6))
        workspace.add_widget(self.pdf_canvas)
        workspace.add_widget(self.side_panel)
        return workspace

    def toggle_notes(self, *_args: Any) -> None:
        """Collapse or restore the notes side panel."""
        self.notes_expanded = not self.notes_expanded
        self.side_panel.size_hint_x = 0.32 if self.notes_expanded else 0
        self.side_panel.opacity = 1 if self.notes_expanded else 0
        self.side_panel.disabled = not self.notes_expanded


class SamsungNotesCompanionApp(App):
    """Application state and entry point for the companion client."""

    def build(self) -> RootLayout:
        Window.clearcolor = (0.95, 0.95, 0.95, 1)
        self.title = "Samsung Notes Companion"
        self.current_color: Rgba = COLOR_BLACK
        self.is_eraser: bool = False
        self.is_dashed: bool = False
        self.pdf_path: Optional[str] = None
        self.root_layout = RootLayout()
        return self.root_layout

    def open_pdf(self, *_args: Any) -> None:
        """Let the user pick a PDF to associate with the main canvas."""
        chooser = FileChooserListView(filters=["*.pdf"], path=os.getcwd())
        body = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        buttons = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        popup = Popup(title="Open PDF", content=body, size_hint=(0.9, 0.9))

        def _load(_instance: Button) -> None:
            if chooser.selection:
                self.pdf_path = chooser.selection[0]
            popup.dismiss()

        load_btn = Button(text="Load")
        cancel_btn = Button(text="Cancel")
        load_btn.bind(on_release=_load)
        cancel_btn.bind(on_release=lambda _btn: popup.dismiss())
        buttons.add_widget(load_btn)
        buttons.add_widget(cancel_btn)
        body.add_widget(chooser)
        body.add_widget(buttons)
        popup.open()

    def save_document(self, *_args: Any) -> None:
        """Serialize strokes from both canvases into my_drawing.notes."""
        payload = {
            "pdf_path": self.pdf_path,
            "pdf_canvas": self.root_layout.pdf_canvas.serialized_strokes(),
            "notes_canvas": self.root_layout.notes_canvas.serialized_strokes(),
        }
        serialized = json.dumps(payload, indent=2)
        notes_path = os.path.join(self.user_data_dir, "my_drawing.notes")
        os.makedirs(self.user_data_dir, exist_ok=True)
        with open(notes_path, "w", encoding="utf-8") as handle:
            handle.write(serialized)
        try:
            with open("my_drawing.notes", "w", encoding="utf-8") as handle:
                handle.write(serialized)
        except OSError:
            pass

    def set_color_black(self, *_args: Any) -> None:
        self.is_eraser = False
        self.current_color = COLOR_BLACK

    def set_color_red(self, *_args: Any) -> None:
        self.is_eraser = False
        self.current_color = COLOR_RED

    def set_color_blue(self, *_args: Any) -> None:
        self.is_eraser = False
        self.current_color = COLOR_BLUE

    def toggle_dashed(self, *_args: Any) -> None:
        self.is_dashed = not self.is_dashed
        if self.is_dashed:
            self.is_eraser = False

    def enable_eraser(self, *_args: Any) -> None:
        self.is_eraser = True


if __name__ == "__main__":
    SamsungNotesCompanionApp().run()
