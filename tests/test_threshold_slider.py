from __future__ import annotations

from aqt.qt import QColor, QPalette

from dynamic_desired_retention.threshold_slider import (
    _is_dark,
    _threshold_label,
    slider_colors,
    threshold_workload_color,
)
from dynamic_desired_retention.field_rule_table import (
    FieldThresholdRow,
    MINIMUM_RETENTION_VALUE,
)


def test_slider_colors_use_light_theme_contrast() -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2563eb"))

    colors = slider_colors(palette)

    assert colors.text == QColor("#111827")
    assert colors.selected_marker_outline == QColor("#2563eb")
    assert colors.marker_outline == QColor("#111827")
    assert colors.axis.alpha() == 130
    assert colors.tick.alpha() == 150


def test_slider_colors_use_dark_theme_contrast() -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f9fafb"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#60a5fa"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#030712"))

    colors = slider_colors(palette)

    assert colors.text == QColor("#f9fafb")
    assert colors.selected_marker_outline == QColor("#60a5fa")
    assert colors.marker_outline == QColor("#030712")
    assert colors.axis.alpha() == 150
    assert colors.tick.alpha() == 180


def test_dark_detection_uses_palette_background_lightness() -> None:
    assert _is_dark(QColor("#111827"))
    assert not _is_dark(QColor("#f9fafb"))


def test_threshold_workload_color_maps_high_dr_to_red_and_50_to_green() -> None:
    assert threshold_workload_color(100).hue() == 0
    assert threshold_workload_color(75).hue() == 60
    assert threshold_workload_color(50).hue() == 120


def test_threshold_workload_color_clamps_outside_workload_range() -> None:
    assert threshold_workload_color(110).hue() == 0
    assert threshold_workload_color(10).hue() == 120


def test_threshold_label_shortens_minimum_retention() -> None:
    assert _threshold_label(FieldThresholdRow(MINIMUM_RETENTION_VALUE, "50")) == "Min"
    assert _threshold_label(FieldThresholdRow("Frequency", "90")) == "Frequency"


def test_threshold_label_rounds_relative_percentile() -> None:
    assert _threshold_label(FieldThresholdRow("Top 12.5%", "90")) == "Top 13%"
