import os
import sys
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from PyQt6.QtGui import QIcon, QPixmap, QPainter
from PyQt6.QtCore import Qt, QByteArray
from PyQt6.QtSvg import QSvgRenderer


_icon_cache = {}
_icon_svgs = {}


def _ensure_icons_loaded():
    if _icon_svgs:
        return

    if getattr(sys, 'frozen', False):
        zip_path = os.path.join(sys._MEIPASS, 'lucide', 'lucide.zip')
    else:
        import lucide
        zip_path = os.path.join(os.path.dirname(lucide.__file__), 'lucide.zip')

    with ZipFile(zip_path, 'r') as zf:
        for name in zf.namelist():
            if name.endswith('.svg'):
                _icon_svgs[name[:-4]] = zf.read(name).decode('utf-8')


def _render_icon(name: str, size: int, color: str) -> str:
    _ensure_icons_loaded()
    svg_src = _icon_svgs.get(name)
    if svg_src is None:
        return ''

    svg = ET.fromstring(svg_src)
    svg.attrib['width'] = str(size)
    svg.attrib['height'] = str(size)

    if color:
        for elem in svg.iter():
            val = elem.get('stroke')
            if val and val in ('currentColor', 'currentcolor'):
                elem.set('stroke', color)

    string = ET.tostring(svg, encoding='unicode')
    string = string.replace(' xmlns="http://www.w3.org/2000/svg"', '', 1)
    return string


def lucide_icon(name: str, size: int = 20, color: str = '#000000') -> QIcon:
    if color:
        cache_key = f'{name}_{size}_{color}'
    else:
        cache_key = f'{name}_{size}'

    if cache_key in _icon_cache:
        return _icon_cache[cache_key]

    svg_str = _render_icon(name, size, color)
    if not svg_str:
        return QIcon()

    svg_bytes = svg_str.encode('utf-8')
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    icon = QIcon(pixmap)
    _icon_cache[cache_key] = icon
    return icon
