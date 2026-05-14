from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import floor
from typing import Any

from aqt.qt import QColor, QPainter, QPalette, QPen, QSizePolicy, QWidget

from .field_rule_table import (
    FieldThresholdRow,
    is_minimum_retention_row,
)
from .rule_table import RuleTableError, normalize_table_desired_retention


@dataclass(frozen=True)
class SliderColors:
    axis: QColor
    tick: QColor
    text: QColor
    marker_outline: QColor
    selected_marker_outline: QColor


class ThresholdSlider(QWidget):
    def __init__(
        self,
        *,
        on_selected_changed: Callable[[int], None],
        on_percent_changed: Callable[[int, int], None],
    ) -> None:
        super().__init__()
        self._thresholds: list[FieldThresholdRow] = []
        self._field_name = ""
        self._selected_index = -1
        self._dragging_index = -1
        self._on_selected_changed = on_selected_changed
        self._on_percent_changed = on_percent_changed
        self.setMinimumHeight(118)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_thresholds(
        self,
        thresholds: list[FieldThresholdRow],
        selected_index: int,
        field_name: str = "",
    ) -> None:
        self._thresholds = thresholds
        self._field_name = field_name.strip()
        self._selected_index = selected_index
        self.update()

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = slider_colors(self.palette())

        left, right = self._axis_bounds()
        y = self.height() // 2
        top_label_y = y - 18
        retention_label_y = y + 24
        side_label_x = 6
        if self._field_name:
            painter.setPen(QPen(colors.text, 1))
            painter.drawText(side_label_x, top_label_y, self._field_name)

        painter.setPen(QPen(colors.axis, 2))
        painter.drawLine(left, y, right, y)
        painter.setPen(QPen(colors.text, 1))
        painter.drawText(side_label_x, retention_label_y, "R")

        painter.setPen(QPen(colors.tick, 1))
        for percent in range(100, 9, -10):
            x = self._x_from_percent(percent)
            painter.drawLine(x, y - 5, x, y + 5)
            painter.setPen(QPen(colors.text, 1))
            painter.drawText(x - 16, retention_label_y, f"{percent}%")
            painter.setPen(QPen(colors.tick, 1))

        for index, threshold in enumerate(self._thresholds):
            percent = self._safe_percent(threshold.desired_retention_percent)
            x = self._x_from_percent(percent)
            selected = index == self._selected_index
            painter.setBrush(threshold_workload_color(percent))
            outline = (
                colors.selected_marker_outline if selected else colors.marker_outline
            )
            painter.setPen(QPen(outline, 3 if selected else 1))
            painter.drawEllipse(x - 7, y - 7, 14, 14)
            painter.setPen(QPen(colors.text, 1))
            _draw_centered_text(painter, x, top_label_y, _threshold_label(threshold))

    def mousePressEvent(self, event: Any) -> None:
        index = self._nearest_threshold_index(_event_x(event))
        if index < 0:
            return

        self._selected_index = index
        self._dragging_index = index
        self._on_selected_changed(index)
        self.update()

    def mouseMoveEvent(self, event: Any) -> None:
        if self._dragging_index < 0:
            return

        self._on_percent_changed(
            self._dragging_index, self._percent_from_x(_event_x(event))
        )

    def mouseReleaseEvent(self, _event: Any) -> None:
        self._dragging_index = -1

    def _nearest_threshold_index(self, x: int) -> int:
        if not self._thresholds:
            return -1

        distances = [
            abs(
                self._x_from_percent(
                    self._safe_percent(row.desired_retention_percent)
                )
                - x
            )
            for row in self._thresholds
        ]
        nearest_index = min(range(len(distances)), key=distances.__getitem__)
        return nearest_index if distances[nearest_index] <= 18 else -1

    def _safe_percent(self, value: str) -> int:
        try:
            percent = float(normalize_table_desired_retention(value))
        except RuleTableError:
            return 90
        return max(10, min(100, round(percent)))

    def _axis_bounds(self) -> tuple[int, int]:
        left = max(76, 18 + _text_width(self, self._field_name))
        return left, max(left + 1, self.width() - 52)

    def _x_from_percent(self, percent: int) -> int:
        left, right = self._axis_bounds()
        ratio = (100 - percent) / 90
        return round(left + ratio * (right - left))

    def _percent_from_x(self, x: int) -> int:
        left, right = self._axis_bounds()
        ratio = (min(max(x, left), right) - left) / (right - left)
        return round(100 - ratio * 90)


def _event_x(event: Any) -> int:
    position = event.position() if hasattr(event, "position") else None
    if position is not None:
        return round(position.x())
    return event.x()


def _threshold_label(threshold: FieldThresholdRow) -> str:
    if is_minimum_retention_row(threshold):
        return "Min"
    if threshold.value.casefold().startswith("top"):
        return _rounded_top_label(threshold.value)
    return threshold.value[:12]


def _rounded_top_label(value: str) -> str:
    percentile_text = value[3:].strip().removesuffix("%").strip()
    try:
        return f"Top {floor(float(percentile_text) + 0.5)}%"
    except ValueError:
        return value[:12]


def _draw_centered_text(painter: QPainter, x: int, baseline_y: int, text: str) -> None:
    painter.drawText(x - _text_width(painter, text) // 2, baseline_y, text)


def _text_width(source: QWidget | QPainter, text: str) -> int:
    return source.fontMetrics().horizontalAdvance(text)


def slider_colors(palette: QPalette) -> SliderColors:
    background = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)
    is_dark = _is_dark(background)

    axis = QColor(text)
    axis.setAlpha(150 if is_dark else 130)
    tick = QColor(text)
    tick.setAlpha(180 if is_dark else 150)

    marker_outline = palette.color(
        QPalette.ColorRole.HighlightedText
        if is_dark
        else QPalette.ColorRole.WindowText
    )
    selected_marker_outline = palette.color(QPalette.ColorRole.Highlight)

    return SliderColors(
        axis=axis,
        tick=tick,
        text=text,
        marker_outline=marker_outline,
        selected_marker_outline=selected_marker_outline,
    )


def _is_dark(color: QColor) -> bool:
    return color.lightness() < 128


def threshold_workload_color(percent: int) -> QColor:
    clamped_percent = max(50, min(100, percent))
    hue = round((100 - clamped_percent) / 50 * 120)
    return QColor.fromHsv(hue, 210, 220)
