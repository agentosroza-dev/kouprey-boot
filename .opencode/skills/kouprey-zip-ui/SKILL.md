
## Tech Stack

- **Python 3.12+** with **PyQt6** (QtWidgets, not QML)
- **No third-party state management** — state lives in instance attributes + JSON config
- **Custom WinUI 3–inspired QSS stylesheets** generated in `core/theme.py`
- **i18n** via `core/language.py` `LanguageManager` reading `assets/lang/{code}.json`
- **Lucide SVG icons** rendered via `core/icons.py` -> `PyQt6.QtSvg`
- **Async work** offloaded to `QThread` subclasses with `pyqtSignal`

## Architecture

### Navigation

`MainWindow` uses a `QStackedWidget` with manual routing:
- Left nav panel has `NavButton` instances (checkable `QPushButton`)
- `MainWindow._navigate_to(page_key)` sets the current widget, updates title, and calls `populate_toolbar()`
- Page keys: `"archive_page"`, `"compress_page"`, `"encrypt_page"`, `"settings_page"`
- Settings has its own nested `QStackedWidget` with sub-pages: General, Appearance, Integration

### Page Pattern

Every page class follows this contract:
- Constructor: `(self, lang: LanguageManager, theme: ThemeManager)`
- Implements `retranslate()` — updates all text labels/buttons/table headers for i18n
- Optionally implements `populate_toolbar(toolbar: QToolBar)` — adds actions to the command bar

## Theming

- `ThemeManager` holds a `WinUIColorTokens` (light) or `DarkWinUIColorTokens` (dark) dataclass
- `theme.set_mode("light" | "dark")` applies a `QPalette` + full QSS stylesheet to `QApplication`
- Use `theme.colors.<token>` to reference colors (e.g., `theme.colors.surface`, `theme.colors.accent`)
- Widgets must call `setObjectName(...)` for QSS selector targeting
- Object names used in stylesheets include: `#navigationButton`, `#card`, `#accentButton`, `#pageTitle`, `#captionLabel`, `#titleLabel`, `#subtitleLabel`, `#navPanel`, `#commandBar`, `#footer`, `#infoBar`, `#dropdownButton`
- Icon colors are updated via `set_icon_color()` in `core/icons.py` after theme change, followed by clearing icon cache

## i18n

- All user-facing strings MUST use `self._lang.tr(key, default_value)`
- Never hardcode text — always go through `tr()`, even for placeholder text
- Language files: `assets/lang/en.json`, `assets/lang/km.json`
- Each page implements `retranslate()` calling `self._lang.tr()` for every visible string
s to `assets/lang/en.json` and `assets/lang/km.json`
