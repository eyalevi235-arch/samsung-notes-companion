"""Samsung Notes companion: collapsible sidebar and S Pen canvas."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from kivy.app import App
from kivy.graphics import Color, Line, Rectangle
from kivy.input.motionevent import MotionEvent
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.widget import Widget

Point = Tuple[float, float]
Stroke = List[Point]


class SPenAnnotationCanvas(Widget):
    """Freehand canvas tuned for Samsung S Pen and finger input.

    Strokes are stored as sequences of (x, y) points so they can later be
    anchored relative to a document page.
    """

    ink_width = NumericProperty(2.5)
    min_width = NumericProperty(1.0)
    max_width = NumericProperty(6.0)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.strokes: List[Stroke] = []
        self.current_stroke: Stroke = []
        self._bg_rect: Optional[Rectangle] = None
        self._bind_canvas_background()

    def _bind_canvas_background(self) -> None:
        with self.canvas.before:
            Color(0.98, 0.98, 0.96, 1)
            self._bg_rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync_background, size=self._sync_background)

    def _sync_background(self, *_args: Any) -> None:
        if self._bg_rect is not None:
            self._bg_rect.pos = self.pos
            self._bg_rect.size = self.size

    def _line_width_for_touch(self, touch: MotionEvent) -> float:
        """Map S Pen pressure to stroke width when the device reports it."""
        if "pressure" in touch.profile:
            pressure = max(0.0, min(1.0, float(touch.pressure)))
            span = self.max_width - self.min_width
            return self.min_width + span * pressure
        return float(self.ink_width)

    def on_touch_down(self, touch: MotionEvent) -> bool:
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        touch.grab(self)
        self.current_stroke = [(touch.x, touch.y)]
        width = self._line_width_for_touch(touch)
        with self.canvas:
            Color(0.12, 0.23, 0.54, 1)
            touch.ud["line"] = Line(
                points=[touch.x, touch.y],
                width=width,
                cap="round",
                joint="round",
            )
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
        if "line" in touch.ud and self.current_stroke:
            self.strokes.append(list(self.current_stroke))
        self.current_stroke = []
        return True

    def clear_strokes(self) -> None:
        """Remove all ink from the canvas."""
        self.strokes.clear()
        self.current_stroke = []
        self.canvas.clear()
        self._sync_background()


class CollapsibleSidebar(BoxLayout):
    """Vertical notes panel that can collapse to a zero-width strip."""

    expanded = BooleanProperty(True)
    expanded_hint = NumericProperty(0.32)

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("size_hint_x", 0.32)
        kwargs.setdefault("padding", dp(8))
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        self._build_contents()

    def _build_contents(self) -> None:
        self.add_widget(
            Label(
                text="Notes",
                size_hint_y=None,
                height=dp(36),
                bold=True,
                color=(0.15, 0.15, 0.18, 1),
            )
        )
        self.add_widget(
            Label(
                text="S Pen ink is captured on the canvas.\n"
                "Toggle this panel to focus on writing.",
                halign="left",
                valign="top",
                color=(0.25, 0.25, 0.28, 1),
            )
        )

    def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        self.size_hint_x = self.expanded_hint if expanded else 0
        self.opacity = 1 if expanded else 0
        self.disabled = not expanded


class RootLayout(BoxLayout):
    """Landscape shell: toggle strip, collapsible sidebar, annotation canvas."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("spacing", 0)
        super().__init__(**kwargs)

        self.sidebar = CollapsibleSidebar()
        self.canvas_widget = SPenAnnotationCanvas()
        self.toggle_button = Button(
            text="Hide",
            size_hint_x=None,
            width=dp(72),
            background_color=(0.90, 0.22, 0.22, 1),
        )
        self.toggle_button.bind(on_release=self.toggle_sidebar)

        self.add_widget(self.toggle_button)
        self.add_widget(self.sidebar)
        self.add_widget(self.canvas_widget)

    def toggle_sidebar(self, _instance: Optional[Button] = None) -> None:
        """Collapse or restore the notes sidebar."""
        self.sidebar.set_expanded(not self.sidebar.expanded)
        self.toggle_button.text = "Hide" if self.sidebar.expanded else "Show"


class SamsungNotesCompanionApp(App):
    """Entry point for the Samsung Notes companion client."""

    def build(self) -> RootLayout:
        self.title = "Samsung Notes Companion"
        return RootLayout()


if __name__ == "__main__":
    SamsungNotesCompanionApp().run()
