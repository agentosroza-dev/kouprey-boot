from PyQt6.QtCore import QObject
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtWidgets import QApplication


class ThemeColors:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


LIGHT_COLORS = ThemeColors(
    Surface='#F2F2F2',
    SurfaceAlt='#FFFFFF',
    SurfaceCard='#FFFFFF',
    SurfaceHover='#F0F0F0',
    SurfaceActive='#E5E5E5',
    NavBg='#E8E8E8',
    NavSelected='#DEEAF6',
    TextPrimary='#000000',
    TextSecondary='#616161',
    Accent='#0078D4',
    AccentLight='#DEEAF6',
    AccentHover='#106EBE',
    AccentPressed='#005A9E',
    Border='#E5E5E5',
    BorderSubtle='#EFEFEF',
    Success='#107C10',
    Warning='#FF8C00',
    Error='#D13438',
)

DARK_COLORS = ThemeColors(
    Surface='#2C2C2C',
    SurfaceAlt='#333333',
    SurfaceCard='#3D3D3D',
    SurfaceHover='#404040',
    SurfaceActive='#4A4A4A',
    NavBg='#2A2A2A',
    NavSelected='#1A3A4A',
    TextPrimary='#F2F2F2',
    TextSecondary='#ABABAB',
    Accent='#60CDFF',
    AccentLight='#1A3A4A',
    AccentHover='#7FD8FF',
    AccentPressed='#A0E4FF',
    Border='#454545',
    BorderSubtle='#383838',
    Success='#6CCF6C',
    Warning='#FFB83B',
    Error='#F44747',
)


def _build_stylesheet(c: ThemeColors) -> str:
    return ''.join([
        '\nQMainWindow, QWidget {\n    background-color: ',
        c.Surface,
        ';\n    color: ',
        c.TextPrimary,
        ';\n    font-size: 11pt;\n}\n',
        'QFrame#card {\n    background: ',
        c.SurfaceAlt,
        ';\n    border: 1px solid ',
        c.Border,
        ';\n    border-radius: 8px;\n}\n',
        'QFrame#card:hover {\n    border-color: ',
        c.Accent,
        ';\n}\n',
        'QLabel#titleLabel {\n    font-size: 16pt;\n    font-weight: 600;\n    color: ',
        c.TextPrimary,
        ';\n    letter-spacing: -0.5px;\n    background: transparent;\n}\n',
        'QLabel#subtitleLabel {\n    font-size: 11pt;\n    color: ',
        c.TextSecondary,
        ';\n    background: transparent;\n}\n',
        'QLabel#pageTitle {\n    font-size: 20pt;\n    font-weight: 600;\n    color: ',
        c.TextPrimary,
        ';\n    background: transparent;\n    padding-bottom: 4px;\n}\n',
        'QLabel#pageSubtitle {\n    font-size: 10pt;\n    color: ',
        c.TextSecondary,
        ';\n    background: transparent;\n}\n',
        'QLabel#statusLabel {\n    font-size: 10pt;\n    color: ',
        c.TextSecondary,
        ';\n    background: transparent;\n    padding: 2px 0;\n}\n',
        'QLabel#footerLabel {\n    font-size: 9pt;\n    color: ',
        c.TextSecondary,
        ';\n    padding-top: 4px;\n    background: transparent;\n}\n',
        'QPushButton {\n    background: ',
        c.SurfaceAlt,
        ';\n    color: ',
        c.TextPrimary,
        ';\n    border: 1px solid ',
        c.Border,
        ';\n    border-radius: 6px;\n    padding: 6px 18px;\n    font-size: 11pt;\n    font-weight: 500;\n    min-height: 28px;\n}\n',
        'QPushButton:hover {\n    background: ',
        c.SurfaceHover,
        ';\n    border-color: ',
        c.Border,
        ';\n}\n',
        'QPushButton:pressed {\n    background: ',
        c.Border,
        ';\n}\n',
        'QPushButton:disabled {\n    background: ',
        c.Surface,
        ';\n    color: ',
        c.TextSecondary,
        ';\n    border-color: ',
        c.Border,
        ';\n}\n',
        'QPushButton#btn_accent {\n    background: ',
        c.Accent,
        ';\n    color: white;\n    border: 1px solid ',
        c.Accent,
        ';\n    font-weight: 600;\n}\n',
        'QPushButton#btn_accent:hover {\n    background: ',
        c.AccentHover,
        ';\n    border-color: ',
        c.AccentHover,
        ';\n}\n',
        'QPushButton#btn_accent:pressed {\n    background: ',
        c.AccentPressed,
        ';\n    border-color: ',
        c.AccentPressed,
        ';\n}\n',
        'QPushButton#btn_accent:disabled {\n    background: ',
        c.AccentLight,
        ';\n    color: ',
        c.TextSecondary,
        ';\n    border-color: transparent;\n}\n',
        'QPushButton#btn_icon {\n    background: transparent;\n    border: none;\n    border-radius: 6px;\n    padding: 6px;\n    min-height: 32px;\n    min-width: 32px;\n}\n',
        'QPushButton#btn_icon:hover {\n    background: ',
        c.SurfaceHover,
        ';\n}\n',
        'QPushButton#btn_nav {\n    background: transparent;\n    border: none;\n    border-radius: 6px;\n    padding: 10px 16px;\n    text-align: left;\n}\n',
        'QPushButton#btn_nav:hover {\n    background: ',
        c.SurfaceHover,
        ';\n}\n',
        'QPushButton#btn_nav:checked {\n    background: ',
        c.AccentLight,
        ';\n    color: ',
        c.Accent,
        ';\n    font-weight: 600;\n}\n',
        'QFrame#navPanel {\n    background: ',
         getattr(c, 'NavBg', c.SurfaceAlt),
        ';\n    border-right: 1px solid ',
        c.Border,
        ';\n}\n',
        'QComboBox {\n    background: ',
        c.SurfaceAlt,
        ';\n    color: ',
        c.TextPrimary,
        ';\n    border: 1px solid ',
        c.Border,
        ';\n    border-radius: 6px;\n    padding: 6px 12px;\n    font-size: 11pt;\n    min-height: 24px;\n}\n',
        'QComboBox:hover {\n    border-color: ',
        c.Accent,
        ';\n}\n',
        'QComboBox::drop-down {\n    border: none;\n    width: 24px;\n}\n',
        'QComboBox QAbstractItemView {\n    background: ',
        c.SurfaceAlt,
        ';\n    color: ',
        c.TextPrimary,
        ';\n    border: 1px solid ',
        c.Border,
        ';\n    border-radius: 6px;\n    selection-background-color: ',
        c.AccentLight,
        ';\n    selection-color: ',
        c.TextPrimary,
        ';\n    padding: 4px;\n}\n',
        'QCheckBox {\n    spacing: 8px;\n    font-size: 11pt;\n}\n',
        'QCheckBox::indicator {\n    width: 18px;\n    height: 18px;\n    border: 2px solid ',
        c.Border,
        ';\n    border-radius: 4px;\n    background: ',
        c.SurfaceAlt,
        ';\n}\n',
        'QCheckBox::indicator:checked {\n    background: ',
        c.Accent,
        ';\n    border-color: ',
        c.Accent,
        ';\n}\n',
        'QCheckBox::indicator:hover {\n    border-color: ',
        c.Accent,
        ';\n}\n',
        'QProgressBar {\n    background: ',
        c.BorderSubtle,
        ';\n    border: none;\n    border-radius: 3px;\n    height: 6px;\n    text-align: center;\n    font-size: 8pt;\n}\n',
        'QProgressBar::chunk {\n    background: ',
        c.Accent,
        ';\n    border-radius: 3px;\n}\n',
        'QTableWidget {\n    background: ',
        c.SurfaceCard,
        ';\n    border: 1px solid ',
        c.Border,
        ';\n    border-radius: 8px;\n    gridline-color: transparent;\n    outline: none;\n}\n',
        'QTableWidget::item {\n    padding: 8px 12px;\n    border: none;\n    border-bottom: 1px solid ',
        c.BorderSubtle,
        ';\n}\n',
        'QTableWidget::item:hover {\n    background: ',
        c.SurfaceHover,
        ';\n}\n',
        'QTableWidget::item:selected {\n    background: ',
        c.AccentLight,
        ';\n    color: ',
        c.TextPrimary,
        ';\n}\n',
        'QHeaderView::section {\n    background: transparent;\n    color: ',
        c.TextSecondary,
        ';\n    border: none;\n    border-bottom: 1px solid ',
        c.Border,
        ';\n    padding: 8px 12px;\n    font-weight: 600;\n    font-size: 10pt;\n}\n',
        'QScrollBar:vertical {\n    background: transparent;\n    width: 8px;\n    margin: 0;\n}\n',
        'QScrollBar::handle:vertical {\n    background: ',
        c.Border,
        ';\n    border-radius: 4px;\n    min-height: 30px;\n}\n',
        'QScrollBar::handle:vertical:hover {\n    background: ',
        c.TextSecondary,
        ';\n}\n',
        'QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {\n    height: 0;\n}\n',
        'QGroupBox {\n    background: ',
        c.SurfaceCard,
        ';\n    border: 1px solid ',
        c.Border,
        ';\n    border-radius: 8px;\n    margin-top: 12px;\n    padding: 16px;\n    padding-top: 28px;\n    font-size: 10pt;\n    font-weight: 600;\n}\n',
        'QGroupBox::title {\n    subcontrol-origin: margin;\n    subcontrol-position: top left;\n    padding: 4px 12px;\n    color: ',
        c.TextSecondary,
        ';\n}\n',
    ])


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
        palette.setColor(QPalette.ColorRole.Window, QColor(c.Surface))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(c.TextPrimary))
        palette.setColor(QPalette.ColorRole.Base, QColor(c.SurfaceCard))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c.SurfaceAlt))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c.SurfaceCard))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c.TextPrimary))
        palette.setColor(QPalette.ColorRole.Text, QColor(c.TextPrimary))
        palette.setColor(QPalette.ColorRole.Button, QColor(c.SurfaceCard))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(c.TextPrimary))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(c.TextPrimary))
        palette.setColor(QPalette.ColorRole.Link, QColor(c.Accent))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(c.Accent))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c.TextPrimary))
        self._app.setPalette(palette)

        stylesheet = _build_stylesheet(c)
        self._app.setStyleSheet(stylesheet)
