import sys
import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox, QFrame, QApplication,
    QStackedWidget, QComboBox, QProgressBar, QTabWidget,
    QScrollArea, QFileDialog,
)

from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QIcon

from icons import lucide_icon
from theme import LIGHT_COLORS, DARK_COLORS
from scanner import (
    list_usb_drives, list_available_themes,
    DriveInfo, ThemeInfo,
)
from worker import create_flash_worker, create_deploy_worker, create_iso_worker, rename_volume, is_windows_iso, show_drive_ui


PAGES = [
    ('dashboard', 'layout-dashboard', 'nav_dashboard'),
    ('flash', 'zap', 'nav_flash'),
    ('deploy', 'package', 'nav_deploy'),
]


class DriveCard(QFrame):
    def __init__(self, drive: DriveInfo, lang, parent=None):
        super().__init__(parent)
        self.setObjectName('card')
        self.drive = drive
        self._lang = lang
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)

        top = QHBoxLayout()
        top.setSpacing(14)

        bt = self.drive.boot_type
        if bt == 'ventoy':
            icon_name, icon_color = 'check-circle', '#000000'
            badge_prefix = '\u2714 '
            badge_key = 'badge_ventoy'
            badge_bg = '#E8E8E8'
            badge_border = '#555555'
            badge_fg = '#000000'
        elif bt in ('windows',):
            icon_name, icon_color = 'monitor', '#1A1A1A'
            badge_prefix = '\u25a0 '
            badge_key = 'badge_windows'
            badge_bg = '#E8E8E8'
            badge_border = '#555555'
            badge_fg = '#000000'
        elif bt in ('winpe',):
            icon_name, icon_color = 'monitor', '#555555'
            badge_prefix = '\u25a0 '
            badge_key = 'badge_winpe'
            badge_bg = '#E8E8E8'
            badge_border = '#555555'
            badge_fg = '#000000'
        elif bt in ('ubuntu', 'mint', 'debian', 'fedora', 'manjaro', 'cachyos', 'arch', 'kali', 'pop', 'opensuse', 'gentoo', 'slackware', 'redhat', 'linux'):
            icon_name, icon_color = 'terminal', '#333333'
            badge_prefix = '\u25b6 '
            badge_key = 'badge_' + bt
            badge_bg = '#E8E8E8'
            badge_border = '#555555'
            badge_fg = '#000000'
        else:
            icon_name, icon_color = 'hard-drive', '#666666'
            badge_prefix = '\u25cb '
            badge_key = 'badge_no_os'
            badge_bg = '#F0F0F0'
            badge_border = '#B0B0B0'
            badge_fg = '#555555'

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(36, 36)
        icon_lbl.setPixmap(lucide_icon(icon_name, 36, icon_color).pixmap(36, 36))
        top.addWidget(icon_lbl)

        info = QVBoxLayout()
        info.setSpacing(0)
        name = QLabel(self.drive.model)
        name.setObjectName('statusLabel')
        f = name.font()
        f.setPointSize(12)
        f.setBold(True)
        name.setFont(f)
        info.addWidget(name)

        detail = QLabel(f'{self.drive.size_gb}')
        detail.setObjectName('statusLabel')
        info.addWidget(detail)

        top.addLayout(info, 1)

        badge = QFrame()
        badge.setStyleSheet(
            f'background: {badge_bg}; border: 1px solid {badge_border}; '
            f'border-radius: 4px; padding: 2px 8px;'
        )
        label_text = self._lang.get(badge_key)
        if self.drive.os_name and self.drive.os_name != label_text:
            label_text = self.drive.os_name
        badge_lbl = QLabel(label_text)
        badge_lbl.setStyleSheet(
            f'font-size: 9pt; font-weight: 600; color: {badge_fg}; background: transparent;'
        )
        b_layout = QVBoxLayout(badge)
        b_layout.setContentsMargins(0, 0, 0, 0)
        b_layout.addWidget(badge_lbl)
        top.addWidget(badge)

        if self.drive.mount_point:
            mp = QLabel(self.drive.mount_point)
            mp.setObjectName('statusLabel')
            mp.setAlignment(Qt.AlignmentFlag.AlignRight)
            top.addWidget(mp)

        layout.addLayout(top)


class DashboardPage(QWidget):
    def __init__(self, lang, parent=None):
        super().__init__(parent)
        self._lang = lang
        self._cards = []
        self._summary = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 32)
        layout.setSpacing(20)

        self._page_title = QLabel(self._lang.get('app_title'))
        self._page_title.setObjectName('pageTitle')
        layout.addWidget(self._page_title)

        self._summary = QLabel('')
        self._summary.setObjectName('pageSubtitle')
        layout.addWidget(self._summary)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addStretch()
        self._refresh_btn = QPushButton(self._lang.get('btn_refresh'))
        self._refresh_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._refresh_btn.setIcon(lucide_icon('refresh-cw', 16, '#616161'))
        self._refresh_btn.setFixedWidth(120)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        top_row.addWidget(self._refresh_btn)
        layout.addLayout(top_row)

        self._card_area = QVBoxLayout()
        self._card_area.setSpacing(10)
        layout.addLayout(self._card_area)

        self._no_drives = QLabel(self._lang.get('no_drives'))
        self._no_drives.setObjectName('statusLabel')
        self._no_drives.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_drives.setStyleSheet('padding: 60px; font-size: 12pt;')
        self._no_drives.setVisible(False)
        layout.addWidget(self._no_drives)

        layout.addStretch()

        self._refresh_btn.clicked.connect(lambda: self.refresh(True))

    def refresh(self, force=False):
        for i in reversed(range(self._card_area.count())):
            w = self._card_area.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._cards.clear()

        drives = list_usb_drives(force_refresh=force)
        if not drives:
            self._no_drives.setVisible(True)
            self._summary.setText('')
            return

        self._no_drives.setVisible(False)
        ventoy_count = sum(1 for d in drives if d.has_ventoy)
        self._summary.setText(
            self._lang.get('drives_detected').format(count=len(drives))
        )
        self._last_drives = drives

        for d in drives:
            card = DriveCard(d, self._lang)
            self._cards.append(card)
            self._card_area.addWidget(card)

    def set_icon_color(self, color: str):
        self._refresh_btn.setIcon(lucide_icon('refresh-cw', 16, color))

    def first_drive(self):
        if hasattr(self, '_last_drives') and self._last_drives:
            return self._last_drives[0]
        drives = list_usb_drives()
        return drives[0] if drives else None


class FlashPage(QWidget):
    def __init__(self, lang, parent=None):
        super().__init__(parent)
        self._lang = lang
        self._worker = None
        self._drive = None
        self._mode = ''
        self._deploy_worker = None
        self._iso_worker = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 32)
        layout.setSpacing(20)

        self._page_title = QLabel(self._lang.get('flash_title'))
        self._page_title.setObjectName('pageTitle')
        layout.addWidget(self._page_title)

        self._drive_info = QLabel(self._lang.get('flash_select'))
        self._drive_info.setObjectName('pageSubtitle')
        self._drive_info.setWordWrap(True)
        layout.addWidget(self._drive_info)

        self._tabs = QTabWidget()
        self._tabs.setObjectName('flashTabs')

        # --- Tab 1: ISO to USB ---
        iso_tab = QWidget()
        iso_layout = QVBoxLayout(iso_tab)
        iso_layout.setContentsMargins(0, 16, 0, 0)
        iso_layout.setSpacing(12)

        iso_card = QFrame()
        iso_card.setObjectName('card')
        iso_card_layout = QVBoxLayout(iso_card)
        iso_card_layout.setContentsMargins(24, 20, 24, 20)
        iso_card_layout.setSpacing(12)

        self._iso_title = QLabel(self._lang.get('iso_title'))
        self._iso_title.setStyleSheet('font-size: 12pt; font-weight: 600;')
        iso_card_layout.addWidget(self._iso_title)

        iso_sel_row = QHBoxLayout()
        iso_sel_row.setSpacing(8)
        self._iso_combo = QComboBox()
        self._iso_combo.setMinimumHeight(36)
        iso_sel_row.addWidget(self._iso_combo, 1)
        self._btn_iso_browse = QPushButton(self._lang.get('iso_browse'))
        self._btn_iso_browse.setObjectName('btn_accent')
        self._btn_iso_browse.setFixedHeight(36)
        self._btn_iso_browse.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        iso_sel_row.addWidget(self._btn_iso_browse)
        iso_card_layout.addLayout(iso_sel_row)

        self._iso_info = QLabel('')
        self._iso_info.setObjectName('statusLabel')
        self._iso_info.setWordWrap(True)
        iso_card_layout.addWidget(self._iso_info)

        self._btn_flash_iso = QPushButton(self._lang.get('iso_flash_btn'))
        self._btn_flash_iso.setObjectName('btn_accent')
        self._btn_flash_iso.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_flash_iso.setIcon(lucide_icon('zap', 16, '#ffffff'))
        iso_card_layout.addWidget(self._btn_flash_iso)

        iso_layout.addWidget(iso_card)
        iso_layout.addStretch()
        self._tabs.addTab(iso_tab, self._lang.get('tab_iso'))

        # --- Tab 2: Ventoy to USB ---
        ventoy_tab = QWidget()
        ventoy_layout = QVBoxLayout(ventoy_tab)
        ventoy_layout.setContentsMargins(0, 16, 0, 0)
        ventoy_layout.setSpacing(12)

        card = QFrame()
        card.setObjectName('card')
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(12)

        self._status = QLabel('')
        self._status.setObjectName('statusLabel')
        self._status.setWordWrap(True)
        card_layout.addWidget(self._status)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._btn_flash = QPushButton(self._lang.get('flash_btn'))
        self._btn_flash.setObjectName('btn_accent')
        self._btn_flash.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_flash.setIcon(lucide_icon('zap', 16, '#ffffff'))
        btn_row.addWidget(self._btn_flash)
        card_layout.addLayout(btn_row)

        # Deploy progress (Ventoy-only, inside Ventoy tab card)
        self._deploy_progress = QProgressBar()
        self._deploy_progress.setVisible(False)
        self._deploy_progress.setFixedHeight(6)
        self._deploy_progress.setTextVisible(False)
        card_layout.addWidget(self._deploy_progress)
        self._deploy_progress_label = QLabel('')
        self._deploy_progress_label.setObjectName('statusLabel')
        self._deploy_progress_label.setVisible(False)
        card_layout.addWidget(self._deploy_progress_label)

        ventoy_layout.addWidget(card)
        ventoy_layout.addStretch()
        self._tabs.addTab(ventoy_tab, self._lang.get('tab_ventoy'))

        layout.addWidget(self._tabs)

        # Shared progress bar (outside tabs, visible for both ISO and Ventoy)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        progress_row.addWidget(self._progress, 1)
        self._progress_label = QLabel('')
        self._progress_label.setObjectName('statusLabel')
        self._progress_label.setVisible(False)
        progress_row.addWidget(self._progress_label)
        layout.addLayout(progress_row)

        log_card = QFrame()
        log_card.setObjectName('card')
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(24, 20, 24, 20)
        log_layout.setSpacing(8)

        self._log_title = QLabel(self._lang.get('log_title'))
        self._log_title.setStyleSheet('font-size: 12pt; font-weight: 600;')
        log_layout.addWidget(self._log_title)

        self._log_area = QVBoxLayout()
        self._log_area.setSpacing(2)
        log_widget = QWidget()
        log_widget.setLayout(self._log_area)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(log_widget)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(160)
        log_layout.addWidget(scroll)
        layout.addWidget(log_card)

        layout.addStretch()

        self._btn_flash.clicked.connect(self._on_flash)
        self._btn_iso_browse.clicked.connect(self._on_iso_browse)
        self._btn_flash_iso.clicked.connect(self._on_flash_iso)

    def set_accent_icon_color(self, color: str):
        self._btn_flash.setIcon(lucide_icon('zap', 16, color))
        self._btn_flash_iso.setIcon(lucide_icon('zap', 16, color))

    def _on_iso_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._lang.get('iso_select'), '',
            self._lang.get('iso_file_filter')
        )
        if path:
            self._iso_combo.addItem(path, path)
            self._iso_combo.setCurrentIndex(self._iso_combo.count() - 1)
            self._update_iso_info(path)

    def _update_iso_info(self, path: str):
        self._iso_info.setText('')

    def _on_flash_iso(self):
        if not self._drive:
            QMessageBox.warning(self, self._lang.get('warning'), self._lang.get('flash_select_drive_first'))
            return

        iso_path = self._iso_combo.currentData()
        if not iso_path:
            QMessageBox.warning(self, self._lang.get('warning'), self._lang.get('iso_no_file'))
            return

        drive_info = f'{self._drive.model} ({self._drive.size_gb}) \u2013 {self._lang.get("disk_label")} #{self._drive.number}'
        is_win = is_windows_iso(iso_path)
        method = self._lang.get('iso_method_windows') if is_win else self._lang.get('iso_method_dd')
        msg = (
            f'{self._lang.get("flash_erase_warning")}\n\n{drive_info}\n'
            f'{iso_path}\n\n'
            f'{self._lang.get("iso_method_label")}: {method}\n'
            f'{self._lang.get("flash_data_lost")}\n'
            f'{self._lang.get("flash_continue")}'
        )
        reply = QMessageBox.question(
            self, self._lang.get('warning'), msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._start_iso_flash()

    def _start_iso_flash(self):
        self._btn_flash_iso.setEnabled(False)
        self._progress.setVisible(True)
        self._progress_label.setVisible(True)
        self._progress.setValue(0)
        self._progress_label.setText(f'0% - {self._lang.get("iso_flashing")}')

        for i in reversed(range(self._log_area.count())):
            w = self._log_area.itemAt(i).widget()
            if w:
                w.setParent(None)

        iso_path = self._iso_combo.currentData()
        self._iso_worker = create_iso_worker(self._drive.number, iso_path, self._drive.device_path)
        self._iso_worker.progress.connect(self._on_iso_progress)
        self._iso_worker.log.connect(self._log)
        self._iso_worker.finished.connect(self._on_iso_finished)
        self._iso_worker.start()

    def _on_iso_progress(self, msg: str):
        self._progress_label.setText(msg)
        import re
        m = re.search(r'(\d+)%', msg)
        if m:
            self._progress.setValue(int(m.group(1)))

    def _on_iso_finished(self, ok: bool, msg: str):
        self._btn_flash_iso.setEnabled(True)
        self._progress.setValue(100 if ok else 0)
        self._progress_label.setText(
            self._lang.get('iso_complete') if ok else f'{self._lang.get("iso_failed")} - {msg}'
        )
        QTimer.singleShot(3000, lambda: self._progress_label.setVisible(False))
        QTimer.singleShot(3000, lambda: self._progress.setVisible(False))
        if ok:
            QMessageBox.information(self, self._lang.get('success'), self._lang.get('iso_complete'))
        else:
            QMessageBox.critical(self, self._lang.get('error'), f'{self._lang.get("iso_failed")}: {msg}')

    def set_drive(self, drive: DriveInfo):
        self._drive = drive
        self._status.setText(
            f'{drive.model} ({drive.size_gb}) \u2013 {self._lang.get("disk_label")} #{drive.number}'
            + (f' \u2013 {drive.mount_point}' if drive.mount_point else '')
        )
        if drive.has_ventoy:
            self._drive_info.setText(self._lang.get('flash_ventoy_installed'))
            self._btn_flash.setText(self._lang.get('flash_btn_reflash'))
        else:
            self._drive_info.setText(self._lang.get('flash_ready'))
            self._btn_flash.setText(self._lang.get('flash_btn'))
        self._btn_flash.setEnabled(True)

    def _log(self, msg: str):
        lbl = QLabel(msg)
        lbl.setObjectName('statusLabel')
        lbl.setWordWrap(True)
        self._log_area.addWidget(lbl)

    def _on_flash(self):
        if not self._drive:
            QMessageBox.warning(self, self._lang.get('warning'), self._lang.get('flash_select_drive_first'))
            return

        drive_info = f'{self._drive.model} ({self._drive.size_gb}) \u2013 {self._lang.get("disk_label")} #{self._drive.number}'
        msg = (
            f'{self._lang.get("flash_erase_warning")}\n\n{drive_info}\n\n'
            f'{self._lang.get("flash_data_lost")}\n'
            f'{self._lang.get("flash_continue")}'
        )
        reply = QMessageBox.question(
            self, self._lang.get('warning'), msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        QTimer.singleShot(0, self._start)

    _progress_steps = 0

    def _start(self):
        self._btn_flash.setEnabled(False)
        self._progress.setVisible(True)
        self._progress_label.setVisible(True)
        self._progress.setValue(0)
        self._progress_label.setText(f'0% - {self._lang.get("flash_starting")}')
        self._progress_steps = 0

        for i in reversed(range(self._log_area.count())):
            w = self._log_area.itemAt(i).widget()
            if w:
                w.setParent(None)

        self._worker = create_flash_worker(self._drive.number)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._log)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, msg: str):
        self._progress_steps += 1
        pct = min(int(self._progress_steps * 12), 90)
        self._progress.setValue(pct)
        self._progress_label.setText(f'{pct}% - {msg}')

    def _on_finished(self, ok: bool, msg: str):
        self._progress.setValue(100 if ok else 0)
        self._progress_label.setText(
            f'100% - {self._lang.get("flash_complete")}' if ok else f'{self._lang.get("flash_failed")} - {msg}'
        )
        QTimer.singleShot(3000, lambda: self._progress_label.setVisible(False))
        QTimer.singleShot(3000, lambda: self._progress.setVisible(False))

        if ok:
            list_usb_drives(force_refresh=True)
            self._drive.has_ventoy = True
            self._drive_info.setText(self._lang.get('flash_ventoy_done'))
            self._btn_flash.setEnabled(False)
            self._log(self._lang.get('flash_deploying_theme'))
            QTimer.singleShot(500, self._auto_deploy)
        else:
            self._btn_flash.setEnabled(True)
            QMessageBox.critical(self, self._lang.get('error'), f'{self._lang.get("flash_failed")}: {msg}')

    _deploy_steps = 0

    def _auto_deploy(self):
        name = 'Vimix'
        base = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
        themes_dir = os.path.join(base, 'themes')
        themes = list_available_themes(themes_dir)
        theme_source = ''
        for t in themes:
            if t.name == name:
                theme_source = t.path
                break

        if not theme_source:
            self._log(self._lang.get('flash_theme_skip').format(name=name))
            self._do_rename()
            return

        drives = list_usb_drives(force_refresh=True)
        data_mount = ''
        for d in drives:
            if d.number == self._drive.number and d.data_mount_point:
                data_mount = d.data_mount_point
                break

        if not data_mount:
            self._log(self._lang.get('flash_no_data_partition'))
            for d in drives:
                if d.number == self._drive.number and d.mount_point:
                    data_mount = d.mount_point
                    break

        if not data_mount:
            self._log(self._lang.get('flash_no_data_error'))
            QMessageBox.critical(self, self._lang.get('error'), self._lang.get('flash_no_data_error'))
            return

        self._deploy_progress.setVisible(True)
        self._deploy_progress_label.setVisible(True)
        self._deploy_progress.setValue(0)
        self._deploy_progress_label.setText(f'0% - {self._lang.get("flash_deploying_theme")}')
        self._deploy_steps = 0

        self._deploy_worker = create_deploy_worker(self._drive.number, data_mount, name, theme_source)
        self._deploy_worker.progress.connect(self._on_deploy_progress)
        self._deploy_worker.log.connect(self._log)
        self._deploy_worker.finished.connect(self._on_deploy_finished)
        self._deploy_worker.start()

    def _on_deploy_progress(self, msg: str):
        self._deploy_steps += 1
        pct = min(int(self._deploy_steps * 25), 85)
        self._deploy_progress.setValue(pct)
        self._deploy_progress_label.setText(f'{pct}% - {msg}')

    def _on_deploy_finished(self, ok: bool, msg: str):
        self._deploy_progress.setValue(100 if ok else 0)
        self._deploy_progress_label.setText(
            f'100% - {self._lang.get("flash_theme_deployed")}' if ok else f'{self._lang.get("flash_failed")} - {msg}'
        )

        if ok:
            self._log(self._lang.get('flash_theme_success').format(name='Vimix'))
            QTimer.singleShot(1000, self._do_rename)
        else:
            self._log(self._lang.get('flash_theme_failed').format(msg=msg))
            QMessageBox.critical(self, self._lang.get('error'), f'{self._lang.get("deploy_fail")}: {msg}')

    def _do_rename(self):
        self._log(self._lang.get('flash_renaming'))
        self._deploy_progress_label.setText(self._lang.get('flash_renaming_progress'))

        drives = list_usb_drives(force_refresh=True)
        drive_letter = ''
        for d in drives:
            if d.number == self._drive.number:
                mp = d.data_mount_point or d.mount_point
                if mp:
                    drive_letter = mp.rstrip(':\\')
                    break

        if not drive_letter:
            self._log(self._lang.get('flash_no_drive_letter'))
            self._finish_all(rename_ok=False)
            return

        ok = rename_volume(drive_letter, 'KOUPREYDATA')
        if ok:
            self._log(self._lang.get('flash_rename_success'))
        else:
            self._log(self._lang.get('flash_rename_fail'))
        self._finish_all(rename_ok=ok)

    def _finish_all(self, rename_ok: bool):
        list_usb_drives(force_refresh=True)
        self._btn_flash.setEnabled(False)
        show_drive_ui(self._drive.number)
        QTimer.singleShot(2000, lambda: self._deploy_progress.setVisible(False))
        QTimer.singleShot(2000, lambda: self._deploy_progress_label.setVisible(False))

        if rename_ok:
            msg = self._lang.get('flash_all_done')
            self._drive_info.setText(msg)
            QMessageBox.information(self, self._lang.get('success'), msg)
        else:
            msg = self._lang.get('flash_rename_partial')
            self._drive_info.setText(msg)
            QMessageBox.warning(self, self._lang.get('warning'), msg)


class DeployPage(QWidget):
    def __init__(self, lang, parent=None):
        super().__init__(parent)
        self._lang = lang
        self._grub_dir = ''
        self._themes_dir = ''
        self._worker = None
        self._drive = None
        self._theme_paths = {}
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 32)
        layout.setSpacing(20)

        self._page_title = QLabel(self._lang.get('deploy_title'))
        self._page_title.setObjectName('pageTitle')
        layout.addWidget(self._page_title)

        self._drive_info = QLabel(self._lang.get('deploy_select'))
        self._drive_info.setObjectName('pageSubtitle')
        layout.addWidget(self._drive_info)

        theme_card = QFrame()
        theme_card.setObjectName('card')
        t_layout = QVBoxLayout(theme_card)
        t_layout.setContentsMargins(24, 20, 24, 20)
        t_layout.setSpacing(12)

        self._t_title = QLabel(self._lang.get('deploy_theme'))
        self._t_title.setStyleSheet('font-size: 12pt; font-weight: 600;')
        t_layout.addWidget(self._t_title)

        self._theme_combo = QComboBox()
        self._theme_combo.addItem(self._lang.get('theme_default'), '')
        self._theme_combo.currentIndexChanged.connect(self._on_theme_selected)
        t_layout.addWidget(self._theme_combo)

        self._theme_preview = QLabel()
        self._theme_preview.setFixedHeight(80)
        self._theme_preview.setStyleSheet(
            'background: #1A1A1A; border-radius: 8px; color: #AAAAAA;'
            ' font-size: 9pt; padding: 8px;'
        )
        self._theme_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._theme_preview.setVisible(False)
        t_layout.addWidget(self._theme_preview)

        self._theme_hint = QLabel('')
        self._theme_hint.setObjectName('statusLabel')
        self._theme_hint.setWordWrap(True)
        t_layout.addWidget(self._theme_hint)
        layout.addWidget(theme_card)

        self._btn_deploy = QPushButton(self._lang.get('btn_apply_theme'))
        self._btn_deploy.setObjectName('btn_accent')
        self._btn_deploy.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_deploy.setIcon(lucide_icon('palette', 16, '#ffffff'))
        self._btn_deploy.setFixedHeight(38)
        layout.addWidget(self._btn_deploy)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        progress_row.addWidget(self._progress, 1)
        self._progress_label = QLabel('')
        self._progress_label.setObjectName('statusLabel')
        self._progress_label.setVisible(False)
        progress_row.addWidget(self._progress_label)
        layout.addLayout(progress_row)

        log_card = QFrame()
        log_card.setObjectName('card')
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(24, 20, 24, 20)
        log_layout.setSpacing(8)
        self._log_title = QLabel(self._lang.get('deploy_log_title'))
        self._log_title.setStyleSheet('font-size: 12pt; font-weight: 600;')
        log_layout.addWidget(self._log_title)

        self._log_area = QVBoxLayout()
        self._log_area.setSpacing(2)
        log_w = QWidget()
        log_w.setLayout(self._log_area)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(log_w)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(120)
        log_layout.addWidget(scroll)
        layout.addWidget(log_card)

        layout.addStretch()

        self._btn_deploy.clicked.connect(self._on_deploy)

    def set_accent_icon_color(self, color: str):
        self._btn_deploy.setIcon(lucide_icon('palette', 16, color))

    def set_drive(self, drive: DriveInfo):
        self._drive = drive
        txt = f'{drive.model} ({drive.size_gb})'
        if drive.mount_point:
            txt += f' \u2013 {drive.mount_point}'
        self._drive_info.setText(txt)

    def refresh_themes(self):
        self._theme_combo.clear()
        self._theme_combo.addItem(self._lang.get('theme_default'), '')
        self._theme_paths.clear()

        themes = list_available_themes(self._themes_dir)
        for t in themes:
            self._theme_combo.addItem(t.name, t.name)
            self._theme_paths[t.name] = t.path

        if themes:
            self._theme_hint.setText(self._lang.get('deploy_theme_count').format(count=len(themes)))
        else:
            self._theme_hint.setText(self._lang.get('theme_no_themes'))

    def _on_theme_selected(self, idx):
        name = self._theme_combo.currentData()
        self._theme_preview.setVisible(bool(name))
        if not name:
            return
        path = self._theme_paths.get(name, '')
        if not path:
            return
        ti = ThemeInfo(name=name, path=path)
        bg = ti.background_path
        title = ti.title
        if bg and os.path.isfile(bg):
            pm = QPixmap(bg)
            if not pm.isNull():
                scaled = pm.scaled(
                    320, 76, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                self._theme_preview.setPixmap(scaled)
                self._theme_preview.setToolTip(f'{name}\n{title}')
                self._theme_preview.setFixedHeight(80)
                return
        self._theme_preview.setText(f'{name}\n{title}')
        self._theme_preview.setToolTip('')

    def _log(self, msg: str):
        lbl = QLabel(msg)
        lbl.setObjectName('statusLabel')
        lbl.setWordWrap(True)
        self._log_area.addWidget(lbl)

    _deploy_steps = 0

    def _on_deploy(self):
        data_mp = getattr(self._drive, 'data_mount_point', '')
        if not self._drive or not data_mp:
            QMessageBox.warning(self, '', self._lang.get('deploy_select'))
            return

        name = self._theme_combo.currentData()
        theme_source = self._theme_paths.get(name, '') if name else ''

        self._btn_deploy.setEnabled(False)
        self._progress.setVisible(True)
        self._progress_label.setVisible(True)
        self._progress.setValue(0)
        self._progress_label.setText(f'0% - {self._lang.get("deploy_starting")}')
        self._deploy_steps = 0

        for i in reversed(range(self._log_area.count())):
            w = self._log_area.itemAt(i).widget()
            if w:
                w.setParent(None)

        self._worker = create_deploy_worker(self._drive.number, data_mp, name, theme_source)
        self._worker.progress.connect(self._on_deploy_progress)
        self._worker.log.connect(self._log)
        self._worker.finished.connect(self._on_deploy_finished)
        self._worker.start()

    def _on_deploy_progress(self, msg: str):
        self._deploy_steps += 1
        pct = min(int(self._deploy_steps * 25), 85)
        self._progress.setValue(pct)
        self._progress_label.setText(f'{pct}% - {msg}')

    def _on_deploy_finished(self, ok: bool, msg: str):
        self._btn_deploy.setEnabled(True)
        self._progress.setValue(100 if ok else 0)
        self._progress_label.setText(
            f'100% - {self._lang.get("deploy_complete_short")}' if ok else f'{self._lang.get("deploy_failed")} - {msg}'
        )
        QTimer.singleShot(3000, lambda: self._progress_label.setVisible(False))
        QTimer.singleShot(3000, lambda: self._progress.setVisible(False))
        if ok:
            QMessageBox.information(self, self._lang.get('success'), msg)
        else:
            QMessageBox.critical(self, self._lang.get('error'), msg)


class SettingsPage(QWidget):
    language_changed = pyqtSignal(str)
    theme_changed = pyqtSignal(str)

    def __init__(self, lang, theme_mgr, parent=None):
        super().__init__(parent)
        self._lang = lang
        self._theme_mgr = theme_mgr
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 36, 40, 32)
        layout.setSpacing(20)

        self._page_title = QLabel(self._lang.get('settings_title'))
        self._page_title.setObjectName('pageTitle')
        layout.addWidget(self._page_title)

        self._card_titles = []
        card_defs = [
            ('settings_info', self._info_section()),
            ('settings_language', self._lang_section()),
            ('settings_theme', self._theme_section()),
        ]
        for key, widget in card_defs:
            card = QFrame()
            card.setObjectName('card')
            cl = QVBoxLayout(card)
            cl.setContentsMargins(24, 20, 24, 20)
            cl.setSpacing(12)
            ct = QLabel(self._lang.get(key))
            ct._lang_key = key
            ct.setStyleSheet('font-size: 12pt; font-weight: 600;')
            cl.addWidget(ct)
            cl.addWidget(widget)
            self._card_titles.append(ct)
            layout.addWidget(card)

        layout.addStretch()

    def _info_section(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        self._info_label = QLabel(self._lang.get('settings_tool_name'))
        self._info_label.setObjectName('statusLabel')
        self._info_label.setWordWrap(True)
        l.addWidget(self._info_label)
        self._ventoy_version = QLabel(self._lang.get('ventoy_version').format(version='1.1.12'))
        self._ventoy_version.setObjectName('statusLabel')
        l.addWidget(self._ventoy_version)
        return w

    def _lang_section(self):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        self._lang_combo = QComboBox()
        self._lang_combo.addItem(self._lang.get('khmer'), 'km')
        self._lang_combo.addItem(self._lang.get('english'), 'en')
        l.addWidget(self._lang_combo)
        l.addStretch()
        self._lang_combo.currentIndexChanged.connect(self._on_lang)
        return w

    def _theme_section(self):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        self._theme_combo = QComboBox()
        self._theme_combo.addItem(self._lang.get('settings_light'), 'light')
        self._theme_combo.addItem(self._lang.get('settings_dark'), 'dark')
        l.addWidget(self._theme_combo)
        l.addStretch()
        self._theme_combo.currentIndexChanged.connect(self._on_theme)
        return w

    def set_info(self, path: str, version: str = ''):
        self._info_label.setText(path or self._lang.get('settings_tool_name'))
        self._ventoy_version.setText(self._lang.get('ventoy_version').format(version=version or '1.1.12'))

    def _on_lang(self, idx):
        code = self._lang_combo.currentData()
        if code and code != self._lang.current_lang:
            self.language_changed.emit(code)

    def set_theme_mode(self, mode: str):
        idx = self._theme_combo.findData(mode)
        if idx >= 0:
            self._theme_combo.blockSignals(True)
            self._theme_combo.setCurrentIndex(idx)
            self._theme_combo.blockSignals(False)

    def _on_theme(self, idx):
        if self._theme_mgr:
            mode = self._theme_combo.currentData()
            self._theme_mgr.set_mode(mode)
            self.theme_changed.emit(mode)


class KoupreyBootFlashWindow(QMainWindow):
    def __init__(self, lang, theme_mgr):
        super().__init__()
        self._lang = lang
        self._theme_mgr = theme_mgr
        self._theme_colors = LIGHT_COLORS
        self._current_page = 'dashboard'

        self.setWindowTitle(lang.get('app_title'))
        self.setMinimumSize(900, 640)
        self.resize(1050, 720)

        icon = QApplication.instance().windowIcon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        self._base = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
        self._themes_dir = os.path.join(self._base, 'themes')

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._build_nav(root)
        self._build_main(root)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._refresh_timer.start(10000)

        QTimer.singleShot(300, self._on_switch_page)

    def _build_nav(self, root):
        panel = QFrame()
        panel.setObjectName('navPanel')
        panel.setFixedWidth(200)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 12, 6, 12)
        layout.setSpacing(4)

        header_row = QHBoxLayout()
        header_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo = QLabel()
        logo.setFixedSize(128, 128)
        self._logo_pixmap = logo
        self._update_logo()
        header_row.addWidget(logo)

        layout.addLayout(header_row)
        layout.addSpacing(8)

        self._nav_btns = {}
        self._nav_icon_map = {}
        self._nav_indicators = {}
        for pid, picon, plang_key in PAGES:
            item = QWidget()
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(0)

            indicator = QFrame()
            indicator.setObjectName('navIndicator')
            indicator.setFixedWidth(3)
            indicator.setFixedHeight(24)
            indicator.setVisible(pid == 'dashboard')
            self._nav_indicators[pid] = indicator
            item_layout.addWidget(indicator, alignment=Qt.AlignmentFlag.AlignVCenter)

            btn = QPushButton(self._lang.get(plang_key))
            btn.setObjectName('btn_nav')
            btn.setCheckable(True)
            btn.setChecked(pid == 'dashboard')
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setIcon(lucide_icon(picon, 32, self._current_text_color()))
            btn._icon_name = picon
            btn.clicked.connect(lambda checked, p=pid: self._switch_page(p))
            self._nav_btns[pid] = btn
            item_layout.addWidget(btn)
            layout.addWidget(item)

        layout.addStretch()

        nav_bottom = QFrame()
        nav_bottom_layout = QVBoxLayout(nav_bottom)
        nav_bottom_layout.setContentsMargins(0, 0, 0, 0)
        nav_bottom_layout.setSpacing(2)

        icon_color = self._current_text_color()
        self._btn_lang = QPushButton()
        self._btn_lang.setObjectName('btn_nav')
        self._btn_lang.setIcon(lucide_icon('languages', 20, icon_color))
        self._btn_lang.setText('  ' + (self._lang.get('khmer') if self._lang.current_lang == 'km' else self._lang.get('english')))
        self._btn_lang.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_lang.setMinimumHeight(36)
        nav_bottom_layout.addWidget(self._btn_lang)

        self._btn_theme = QPushButton()
        self._btn_theme.setObjectName('btn_nav')
        self._btn_theme.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_theme.setMinimumHeight(36)
        nav_bottom_layout.addWidget(self._btn_theme)
        self._update_theme_icon()

        layout.addWidget(nav_bottom)
        root.addWidget(panel)

    def _build_main(self, root):
        content = QFrame()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        self._stack = QStackedWidget()

        self._dash_page = DashboardPage(self._lang)
        self._flash_page = FlashPage(self._lang)
        self._flash_page._main_win = self
        self._deploy_page = DeployPage(self._lang)
        self._deploy_page._main_win = self
        self._settings_page = SettingsPage(self._lang, self._theme_mgr)
        self._settings_page.language_changed.connect(self._on_settings_lang_changed)
        self._settings_page.theme_changed.connect(self._on_settings_theme_changed)

        self._deploy_page._themes_dir = self._themes_dir
        self._settings_page.set_info(
            self._lang.get('settings_tool_name'), '1.1.12'
        )

        self._stack.addWidget(self._dash_page)
        self._stack.addWidget(self._flash_page)
        self._stack.addWidget(self._deploy_page)
        self._stack.addWidget(self._settings_page)
        cl.addWidget(self._stack)

        footer = QFrame()
        footer.setObjectName('footer')
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 8, 24, 8)
        self._footer_left = QLabel(self._lang.get('footer_creator'))
        self._footer_left.setObjectName('footerLabel')
        fl.addWidget(self._footer_left)

        fl.addStretch()

        self._footer_right = QLabel(
            self._lang.get('footer_copyright') + ' | v' + self._lang.get('version'))
        self._footer_right.setObjectName('footerLabel')
        self._footer_right.setAlignment(Qt.AlignmentFlag.AlignRight)
        fl.addWidget(self._footer_right)
        cl.addWidget(footer)

        root.addWidget(content)

        self._btn_lang.clicked.connect(self._on_toggle_lang)
        self._btn_theme.clicked.connect(self._on_toggle_theme)

    def _switch_page(self, page_id: str, run_on_switch: bool = True):
        self._current_page = page_id
        for pid, btn in self._nav_btns.items():
            btn.setChecked(pid == page_id)
        for pid, ind in self._nav_indicators.items():
            ind.setVisible(pid == page_id)

        pm = {'dashboard': 0, 'flash': 1, 'deploy': 2, 'settings': 3}
        self._stack.setCurrentIndex(pm.get(page_id, 0))
        if run_on_switch:
            self._on_switch_page()

    def _on_switch_page(self):
        if self._current_page == 'dashboard':
            self._dash_page.refresh()
            d = self._dash_page.first_drive()
            if d:
                self._flash_page.set_drive(d)
                self._deploy_page.set_drive(d)
        elif self._current_page == 'flash':
            drives = list_usb_drives()
            if drives:
                self._flash_page.set_drive(drives[0])
        elif self._current_page == 'deploy':
            drives = list_usb_drives()
            if drives:
                self._deploy_page.set_drive(drives[0])
            self._deploy_page.refresh_themes()

    def _auto_refresh(self):
        if self._current_page == 'dashboard':
            self._dash_page.refresh()

    def _current_text_color(self):
        c = self._theme_colors
        return c.text_primary if c else '#000000'

    def _update_nav_icons(self):
        c = self._current_text_color()
        for btn in self._nav_btns.values():
            name = getattr(btn, '_icon_name', '')
            if name:
                btn.setIcon(lucide_icon(name, 20, c))

    def _update_theme_icon(self):
        dark = self._theme_mgr and self._theme_mgr.get_mode() == 'dark'
        c = self._current_text_color()
        if dark:
            self._btn_theme.setIcon(lucide_icon('moon', 20, c))
            self._btn_theme.setText('  ' + self._lang.get('theme_tooltip_dark'))
            self._btn_theme.setToolTip(self._lang.get('theme_tooltip_dark'))
        else:
            self._btn_theme.setIcon(lucide_icon('sun', 20, c))
            self._btn_theme.setText('  ' + self._lang.get('theme_tooltip_light'))
            self._btn_theme.setToolTip(self._lang.get('theme_tooltip_light'))
        self._update_nav_icons()
        if hasattr(self, '_dash_page'):
            self._dash_page.set_icon_color(c)

    def _update_logo(self):
        dark = self._theme_mgr and self._theme_mgr.get_mode() == 'dark'
        name = 'Kouprey Logo Variations black.png' if dark else 'Kouprey Logo Variations white.png'
        path = os.path.join(self._base, 'assets', 'icons', name)
        if os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
                self._logo_pixmap.setPixmap(pm.scaled(
                    128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))

    def _retranslate_ui(self):
        lang = self._lang
        self.setWindowTitle(lang.get('app_title'))
        for pid, picon, plang_key in PAGES:
            btn = self._nav_btns.get(pid)
            if btn:
                btn.setText(lang.get(plang_key))

        self._footer_left.setText(lang.get('footer_creator'))
        self._footer_right.setText(
            lang.get('footer_copyright') + ' | v' + lang.get('version'))
        self._update_theme_icon()
        n = lang.get('khmer') if lang.current_lang == 'km' else lang.get('english')
        self._btn_lang.setText('  ' + n)

        # Dashboard page
        self._dash_page._page_title.setText(lang.get('app_title'))
        self._dash_page._no_drives.setText(lang.get('no_drives'))
        self._dash_page._refresh_btn.setText(lang.get('btn_refresh'))
        drives = getattr(self._dash_page, '_last_drives', None)
        if drives:
            self._dash_page._summary.setText(
                lang.get('drives_detected').format(count=len(drives))
            )

        # Flash page
        self._flash_page._page_title.setText(lang.get('flash_title'))
        self._flash_page._drive_info.setText(lang.get('flash_select'))
        self._flash_page._iso_title.setText(lang.get('iso_title'))
        self._flash_page._log_title.setText(lang.get('log_title'))
        self._flash_page._btn_flash.setText(lang.get('flash_btn'))
        self._flash_page._btn_flash_iso.setText(lang.get('iso_flash_btn'))
        self._flash_page._btn_iso_browse.setText(lang.get('iso_browse'))
        self._flash_page._tabs.setTabText(0, lang.get('tab_iso'))
        self._flash_page._tabs.setTabText(1, lang.get('tab_ventoy'))
        if self._flash_page._drive:
            self._flash_page.set_drive(self._flash_page._drive)

        # Deploy page
        self._deploy_page._page_title.setText(lang.get('deploy_title'))
        self._deploy_page._drive_info.setText(lang.get('deploy_select'))
        self._deploy_page._t_title.setText(lang.get('deploy_theme'))
        self._deploy_page._btn_deploy.setText(lang.get('btn_apply_theme'))
        self._deploy_page._log_title.setText(lang.get('deploy_log_title'))
        self._deploy_page._theme_combo.setItemText(0, lang.get('theme_default'))
        self._deploy_page.refresh_themes()

        # Settings page
        self._settings_page._page_title.setText(lang.get('settings_title'))
        for ct in self._settings_page._card_titles:
            ct.setText(lang.get(ct._lang_key))
        self._settings_page._info_label.setText(lang.get('settings_tool_name'))
        self._settings_page._ventoy_version.setText(
            lang.get('ventoy_version').format(version='1.1.12'))
        self._settings_page._lang_combo.setItemText(0, lang.get('khmer'))
        self._settings_page._lang_combo.setItemText(1, lang.get('english'))
        idx = self._settings_page._theme_combo.findData(self._theme_mgr.get_mode())
        self._settings_page._theme_combo.blockSignals(True)
        self._settings_page._theme_combo.clear()
        self._settings_page._theme_combo.addItem(lang.get('settings_light'), 'light')
        self._settings_page._theme_combo.addItem(lang.get('settings_dark'), 'dark')
        if idx >= 0:
            self._settings_page._theme_combo.setCurrentIndex(idx)
        self._settings_page._theme_combo.blockSignals(False)

    def _on_settings_lang_changed(self, code: str):
        self._lang.switch_to(code)
        self._apply_lang_font(code)
        self._retranslate_ui()

    def _on_settings_theme_changed(self, mode: str):
        self._theme_colors = DARK_COLORS if mode == 'dark' else LIGHT_COLORS
        self._update_theme_icon()
        self._update_logo()
        c = self._current_text_color()
        ac = self._theme_colors.accent_text
        self._btn_lang.setIcon(lucide_icon('languages', 20, c))
        self._flash_page.set_accent_icon_color(ac)
        self._deploy_page.set_accent_icon_color(ac)
        if hasattr(self, '_dash_page'):
            self._dash_page.set_icon_color(c)

    def _apply_lang_font(self, code: str):
        app = QApplication.instance()
        if app:
            f = QFont('Leelawadee UI' if code == 'km' else 'Segoe UI', 11)
            f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            app.setFont(f)

    def _on_toggle_lang(self):
        nl = 'km' if self._lang.current_lang == 'en' else 'en'
        self._lang.switch_to(nl)
        self._apply_lang_font(nl)
        self._retranslate_ui()

    def _on_toggle_theme(self):
        if not self._theme_mgr:
            return
        self._theme_mgr.toggle()
        dark = self._theme_mgr.get_mode() == 'dark'
        mode = 'dark' if dark else 'light'
        self._theme_colors = DARK_COLORS if dark else LIGHT_COLORS
        self._settings_page.set_theme_mode(mode)
        self._update_theme_icon()
        self._update_logo()
        c = self._current_text_color()
        ac = self._theme_colors.accent_text
        self._btn_lang.setIcon(lucide_icon('languages', 20, c))
        self._flash_page.set_accent_icon_color(ac)
        self._deploy_page.set_accent_icon_color(ac)
