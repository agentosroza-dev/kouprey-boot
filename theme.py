from dataclasses import dataclass

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


@dataclass(frozen=True)
class ThemeColors:
    surface: str = "#FFFFFF"
    surface_alt: str = "#FFFFFF"
    surface_card: str = "#FFFFFF"
    surface_elevated: str = "#FFFFFF"
    base: str = "#EAEAEA"
    base_alt: str = "#D9D9D9"
    text_primary: str = "#000000"
    text_secondary: str = "#555555"
    text_tertiary: str = "#8B8B8B"
    text_disabled: str = "#B0B0B0"
    accent: str = "#000000"
    accent_light: str = "#E8E8E8"
    accent_hover: str = "#333333"
    accent_pressed: str = "#555555"
    accent_text: str = "#FFFFFF"
    border: str = "#E0E0E0"
    border_subtle: str = "#EFEFEF"
    border_input: str = "#C0C0C0"
    success: str = "#000000"
    warning: str = "#555555"
    error: str = "#000000"
    mica_background: str = "#F5F5F5"
    nav_hover_bg: str = "rgba(0, 0, 0, 0.04)"
    nav_pressed_bg: str = "rgba(0, 0, 0, 0.06)"
    nav_selected_bg: str = "#E8E8E8"
    progress_track: str = "#D9D9D9"
    scrollbar_thumb: str = "rgba(0, 0, 0, 0.15)"
    scrollbar_hover: str = "rgba(0, 0, 0, 0.25)"
    info_bar_info: str = "#E8E8E8"
    info_bar_success: str = "#D9D9D9"
    info_bar_warning: str = "#CCCCCC"
    info_bar_error: str = "#E8E8E8"


LIGHT_COLORS = ThemeColors()

DARK_COLORS = ThemeColors(
    surface="#1F1F1F",
    surface_alt="#2C2C2C",
    surface_card="#333333",
    surface_elevated="#383838",
    base="#454545",
    base_alt="#505050",
    text_primary="#F2F2F2",
    text_secondary="#ABABAB",
    text_tertiary="#8B8B8B",
    text_disabled="#6F6F6F",
    accent="#F2F2F2",
    accent_light="#3A3A3A",
    accent_hover="#D0D0D0",
    accent_pressed="#FFFFFF",
    accent_text="#1A1A1A",
    border="#454545",
    border_subtle="#383838",
    border_input="#555555",
    success="#FFFFFF",
    warning="#AAAAAA",
    error="#FFFFFF",
    mica_background="#202020",
    nav_hover_bg="rgba(255, 255, 255, 0.06)",
    nav_pressed_bg="rgba(255, 255, 255, 0.08)",
    nav_selected_bg="#000000",
    progress_track="#505050",
    scrollbar_thumb="rgba(255, 255, 255, 0.15)",
    scrollbar_hover="rgba(255, 255, 255, 0.25)",
    info_bar_info="#3A3A3A",
    info_bar_success="#333333",
    info_bar_warning="#3A3A3A",
    info_bar_error="#333333",
)


def build_stylesheet(c: ThemeColors) -> str:
    nav_bg = "#000000" if c == DARK_COLORS else "#FFFFFF"
    return f"""
QMainWindow, QWidget {{
    background-color: {c.surface};
    color: {c.text_primary};
    font-family: "AgentosUI", "Segoe UI Variable Display", "Segoe UI", sans-serif;
    font-size: 11pt;
}}

QFrame#card {{
    background: {c.surface_card};
    border: 1px solid {c.border};
    border-radius: 12px;
}}

QLabel#titleLabel {{
    font-size: 14pt;
    font-weight: 700;
    color: {c.text_primary};
    background: transparent;
}}

QLabel#subtitleLabel {{
    font-size: 11pt;
    color: {c.text_secondary};
    background: transparent;
}}

QLabel#pageTitle {{
    font-size: 24pt;
    font-weight: 700;
    color: {c.text_primary};
    background: transparent;
    padding-bottom: 4px;
    letter-spacing: -0.5px;
}}

QLabel#pageSubtitle {{
    font-size: 10pt;
    color: {c.text_secondary};
    background: transparent;
    padding-bottom: 8px;
}}

QLabel#statusLabel {{
    font-size: 10pt;
    color: {c.text_secondary};
    background: transparent;
    padding: 2px 0;
}}

QLabel#footerLabel {{
    color: {c.text_tertiary};
    font-size: 9pt;
    padding-top: 4px;
    background: transparent;
}}

QPushButton {{
    background: {c.surface_alt};
    color: {c.text_primary};
    border: 1px solid {c.border};
    border-radius: 6px;
    padding: 6px 18px;
    font-size: 11pt;
    font-weight: 500;
    min-height: 28px;
}}

QPushButton:hover {{
    background: {c.nav_hover_bg};
    border-color: {c.border_input};
}}

QPushButton:pressed {{
    background: {c.nav_pressed_bg};
}}

QPushButton:disabled {{
    background: {c.surface};
    color: {c.text_disabled};
    border-color: transparent;
}}

QPushButton#btn_accent {{
    background: {c.accent};
    color: {c.accent_text};
    border: none;
    font-weight: 600;
    border-radius: 6px;
    padding: 6px 20px;
}}

QPushButton#btn_accent:hover {{
    background: {c.accent_hover};
}}

QPushButton#btn_accent:pressed {{
    background: {c.accent_pressed};
}}

QPushButton#btn_accent:disabled {{
    background: {c.accent_light};
    color: {c.text_secondary};
}}

QPushButton#btn_icon {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px;
    min-height: 32px;
    min-width: 32px;
}}

QPushButton#btn_icon:hover {{
    background: {c.nav_hover_bg};
}}

QPushButton#btn_nav {{
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px 12px;
    text-align: left;
    font-size: 12pt;
    font-weight: 500;
    color: {c.text_primary};
    min-height: 32px;
}}

QPushButton#btn_nav:hover {{
    background: {c.nav_hover_bg};
}}

QPushButton#btn_nav:checked {{
    background: {c.nav_selected_bg};
    border-radius: 8px;
    color: {c.accent};
    font-weight: 600;
}}

QFrame#navPanel {{
    background: {nav_bg};
    border: none;
    border-right: 2px solid {c.border};
}}

QComboBox {{
    background: {c.surface_alt};
    color: {c.text_primary};
    border: 1px solid {c.border_input};
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 11pt;
    min-height: 24px;
}}

QComboBox:hover {{
    border-color: {c.accent};
}}

QComboBox:focus {{
    border: 2px solid {c.accent};
    padding: 5px 11px;
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background: {c.surface_elevated};
    border: 1px solid {c.border};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}

QComboBox QAbstractItemView::item {{
    padding: 6px 12px;
    min-height: 36px;
    color: {c.text_primary};
    border-radius: 4px;
}}

QComboBox QAbstractItemView::item:selected {{
    background: {c.accent_light};
    color: {c.text_primary};
}}

QCheckBox {{
    spacing: 10px;
    font-size: 11pt;
    color: {c.text_primary};
}}

QCheckBox::indicator {{
    width: 20px;
    height: 20px;
    border: 2px solid {c.base_alt};
    border-radius: 4px;
    background: {c.surface_alt};
}}

QCheckBox::indicator:checked {{
    background: {c.accent};
    border-color: {c.accent};
}}

QCheckBox::indicator:hover {{
    border-color: {c.accent};
}}

QProgressBar {{
    background: {c.progress_track};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    font-size: 8pt;
    color: transparent;
}}

QProgressBar::chunk {{
    background: {c.accent};
    border-radius: 4px;
}}

QTableWidget {{
    background: {c.surface_card};
    border: 1px solid {c.border};
    border-radius: 8px;
    gridline-color: transparent;
    outline: none;
}}

QTableWidget::item {{
    padding: 8px 12px;
    border: none;
    border-bottom: 1px solid {c.border_subtle};
}}

QTableWidget::item:hover {{
    background: {c.nav_hover_bg};
}}

QTableWidget::item:selected {{
    background: {c.accent_light};
    color: {c.text_primary};
}}

QHeaderView::section {{
    background: transparent;
    color: {c.text_secondary};
    border: none;
    border-bottom: 1px solid {c.border};
    padding: 8px 12px;
    font-weight: 600;
    font-size: 10pt;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    border: none;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {c.scrollbar_thumb};
    border-radius: 3px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background: {c.scrollbar_hover};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background: {c.scrollbar_thumb};
    border-radius: 3px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {c.scrollbar_hover};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QGroupBox {{
    background: {c.surface_card};
    border: 1px solid {c.border};
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px;
    padding-top: 28px;
    font-size: 10pt;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 4px 12px;
    color: {c.text_secondary};
}}

QFrame#separator {{
    background: {c.border};
    border: none;
    max-height: 1px;
}}

QFrame#navIndicator {{
    background: {c.accent};
    border: none;
    border-radius: 2px;
}}

QFrame#footer {{
    background: transparent;
    border-top: 2px solid {c.border};
}}
"""


class ThemeManager(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self._app = app
        self._mode = 'light'

    def get_mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        colors = DARK_COLORS if mode == 'dark' else LIGHT_COLORS
        self._apply(colors)

    def toggle(self) -> str:
        new = 'dark' if self._mode == 'light' else 'light'
        self.set_mode(new)
        return new

    def _apply(self, c: ThemeColors) -> None:
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(c.surface))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(c.text_primary))
        palette.setColor(QPalette.ColorRole.Base, QColor(c.surface_card))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c.surface_alt))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c.surface_elevated))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c.text_primary))
        palette.setColor(QPalette.ColorRole.Text, QColor(c.text_primary))
        palette.setColor(QPalette.ColorRole.Button, QColor(c.surface_alt))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(c.text_primary))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(c.text_primary))
        palette.setColor(QPalette.ColorRole.Link, QColor(c.accent))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(c.accent))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c.accent_text))
        self._app.setPalette(palette)

        stylesheet = build_stylesheet(c)
        self._app.setStyleSheet(stylesheet)
