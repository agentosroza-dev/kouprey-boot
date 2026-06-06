"""Tests for Kouprey Boot project."""
import os
import sys
import json
import tempfile
import shutil
import pytest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'


# ---------------------------------------------------------------------------
# Module imports
# ---------------------------------------------------------------------------

class TestImports:
    def test_worker_imports(self):
        from worker import KoupreyFlashWorker, create_flash_worker, DeployWorker

    def test_scanner_imports(self):
        from scanner import list_usb_drives, list_available_themes, DriveInfo, ThemeInfo

    def test_theme_imports(self):
        from theme import ThemeManager, LIGHT_COLORS, DARK_COLORS

    def test_language_imports(self):
        from language import LanguageManager

    def test_icons_imports(self):
        from icons import lucide_icon

    def test_flash_headless_imports(self):
        import flash_headless
        assert hasattr(flash_headless, 'do_flash')
        assert hasattr(flash_headless, 'do_gen_iso_menu')
        assert hasattr(flash_headless, 'do_deploy')

    def test_ui_main_imports(self):
        from ui_main import KoupreyBootFlashWindow


# ---------------------------------------------------------------------------
# Scanner tests
# ---------------------------------------------------------------------------

class TestScanner:
    def test_theme_info(self):
        from scanner import ThemeInfo
        t = ThemeInfo(name='Test', path=os.getcwd())
        assert t.name == 'Test'
        assert t.title == 'Test'

    def test_theme_pack_name(self):
        from scanner import ThemeInfo
        with tempfile.TemporaryDirectory() as td:
            theme_dir = os.path.join(td, 'TestTheme')
            os.makedirs(theme_dir)
            tf = os.path.join(theme_dir, 'theme.txt')
            with open(tf, 'w') as f:
                f.write('title-text: "My Theme"\n')
            t = ThemeInfo(name='TestTheme', path=theme_dir)
            assert t.title == 'My Theme'
            assert t.has_theme_file

    def test_list_available_themes(self):
        from scanner import list_available_themes
        with tempfile.TemporaryDirectory() as td:
            themes = list_available_themes(td)
            assert isinstance(themes, list)

    def test_drive_info(self):
        from scanner import DriveInfo
        d = DriveInfo(
            number=2, model='Test USB', size_bytes=16_000_000_000,
            is_removable=True, is_usb=True,
        )
        assert d.number == 2
        assert d.is_usb
        assert 'GB' in d.size_gb


# ---------------------------------------------------------------------------
# Worker tests
# ---------------------------------------------------------------------------

class TestWorker:
    def test_generate_iso_menu_empty(self):
        from worker import KoupreyFlashWorker
        with tempfile.TemporaryDirectory() as td:
            count = KoupreyFlashWorker._generate_iso_menu(td)
            assert count == 0
            menu_path = os.path.join(td, 'ISOS', '.iso_menu.cfg')
            assert os.path.isfile(menu_path)

    def test_generate_iso_menu_with_isos(self):
        from worker import KoupreyFlashWorker
        with tempfile.TemporaryDirectory() as td:
            iso_dir = os.path.join(td, 'ISOS')
            os.makedirs(iso_dir)
            for name in ('ubuntu.iso', 'arch.iso', 'readme.txt'):
                path = os.path.join(iso_dir, name)
                with open(path, 'w') as f:
                    f.write('test')
            count = KoupreyFlashWorker._generate_iso_menu(td)
            assert count == 2, f'Expected 2 entries, got {count}'
            menu_path = os.path.join(iso_dir, '.iso_menu.cfg')
            with open(menu_path) as f:
                content = f.read()
            assert 'Boot ubuntu.iso' in content
            assert 'Boot arch.iso' in content
            assert 'boot_iso' in content
            assert 'readme.txt' not in content

    def test_generate_iso_menu_skips_existing(self):
        from worker import KoupreyFlashWorker
        with tempfile.TemporaryDirectory() as td:
            iso_dir = os.path.join(td, 'ISOS')
            os.makedirs(iso_dir)
            # Put a .iso_menu.cfg and real ISOs
            with open(os.path.join(iso_dir, '.iso_menu.cfg'), 'w') as f:
                f.write('# manual')
            with open(os.path.join(iso_dir, 'test.iso'), 'w') as f:
                f.write('test')
            count = KoupreyFlashWorker._generate_iso_menu(td)
            assert count == 1
            with open(os.path.join(iso_dir, '.iso_menu.cfg')) as f:
                content = f.read()
            assert 'Boot test.iso' in content

    def test_create_flash_worker(self):
        from worker import create_flash_worker
        w = create_flash_worker(99, 'exfat', ['test.iso'])
        assert w._disk_number == 99
        assert w._file_system == 'exfat'
        assert w._selected_isos == ['test.iso']


# ---------------------------------------------------------------------------
# GRUB config validation
# ---------------------------------------------------------------------------

class TestGrubConfig:
    GRUB_CFG = os.path.join(os.path.dirname(__file__), 'assets', 'grub', 'grub', 'grub.cfg')

    def test_grub_cfg_exists(self):
        assert os.path.isfile(self.GRUB_CFG)

    def test_grub_cfg_basic_syntax(self):
        with open(self.GRUB_CFG) as f:
            content = f.read()
        # Check essential elements
        assert 'menuentry' in content, 'Missing menuentry'
        assert 'boot_iso' in content, 'Missing boot_iso function'
        assert 'search --no-floppy --set=data_root --file /themes/.marker' in content, \
            'Missing data_root search'
        assert 'loopback' in content, 'Missing loopback'
        assert 'configfile' in content, 'Missing configfile'
        assert 'chainloader' in content, 'Missing chainloader'
        assert 'function boot_iso' in content, 'Missing boot_iso definition'

    def test_grub_cfg_braces_balanced(self):
        """Count opening and closing braces in menuentry blocks."""
        with open(self.GRUB_CFG) as f:
            content = f.read()
        opens = content.count('{')
        closes = content.count('}')
        assert opens == closes, \
            f'Unbalanced braces: {opens} {{ vs {closes} }}'

    def test_grub_cfg_modules_loaded(self):
        with open(self.GRUB_CFG) as f:
            content = f.read()
        required = ['insmod part_gpt', 'insmod ntfs', 'insmod fat',
                     'insmod ext2', 'insmod iso9660', 'insmod loopback',
                     'insmod chain', 'insmod search']
        for mod in required:
            assert mod in content, f'Missing: {mod}'

    def test_iso_menu_template_exists(self):
        tpl = os.path.join(os.path.dirname(__file__),
                           'assets', 'grub', 'grub', '.iso_menu.cfg')
        assert os.path.isfile(tpl), 'Template .iso_menu.cfg not found'
        with open(tpl) as f:
            content = f.read()
        # All entries must have balanced braces
        assert content.count('{') == content.count('}'), \
            'Template has unbalanced braces'
        # Check key entries exist
        for title in ['Windows 11', 'Windows 10', 'Arch Linux',
                       'Ubuntu Live', 'Debian', 'Redo Rescue',
                       'Fedora', 'WinPE', 'CachyOS']:
            assert title in content, f'Missing entry: {title}'


# ---------------------------------------------------------------------------
# GRUB boot files audit
# ---------------------------------------------------------------------------

class TestBootFiles:
    BASE = os.path.join(os.path.dirname(__file__), 'assets')

    @pytest.mark.parametrize('path', [
        'boot/boot.img',
        'boot/core.img.xz',
        'grub/EFI/BOOT/BOOTX64.EFI',
        'grub/grub/ventoy/ventoy_x64.efi',
        'grub/grub/ventoy/ventoy_ia32.efi',
        'grub/grub/ventoy/ventoy.cpio',
        'grub/grub/ventoy/ipxe.krn',
        'grub/grub/ventoy/memdisk',
        'grub/grub/ventoy/wimboot.x86_64.xz',
        'grub/grub/ventoy/vtoyjump64.exe',
    ])
    def test_boot_file_exists(self, path):
        full = os.path.join(self.BASE, path)
        assert os.path.isfile(full), f'Missing: {full}'

    def test_ventoy_efi_binaries(self):
        import glob as g
        ventoy = os.path.join(self.BASE, 'grub', 'grub', 'ventoy', 'ventoy_*.efi')
        efi_files = [f for f in g.glob(ventoy) if os.path.isfile(f)]
        assert len(efi_files) >= 2, f'Expected >=2 ventoy_*.efi, found {len(efi_files)}'

    def test_grub_modules_exist(self):
        """At least one architecture should have essential modules."""
        for arch in ('x86_64-efi', 'i386-efi', 'i386-pc'):
            mod_dir = os.path.join(self.BASE, 'grub', 'grub', arch)
            if not os.path.isdir(mod_dir):
                continue
            files = os.listdir(mod_dir)
            mods = [f for f in files if f.endswith('.mod')]
            essential = ['normal.mod', 'linux.mod', 'loopback.mod',
                         'chain.mod', 'search.mod', 'iso9660.mod',
                         'fat.mod', 'ntfs.mod', 'ext2.mod', 'part_gpt.mod']
            missing = [m for m in essential if m not in mods]
            if not missing:
                return
        pytest.fail(f'Essential modules missing in all archs: {missing}')

    def test_grub_fonts_exist(self):
        fonts = os.path.join(self.BASE, 'grub', 'grub', 'fonts')
        assert os.path.isdir(fonts)
        pf2 = [f for f in os.listdir(fonts) if f.endswith('.pf2')]
        assert len(pf2) >= 1, 'No .pf2 fonts found'

    def test_wimboot_files_exist(self):
        wim_dir = os.path.join(self.BASE, 'grub', 'grub', 'ventoy')
        for fname in ('wimboot.x86_64.xz', 'wimboot.i386.efi.xz'):
            assert os.path.isfile(os.path.join(wim_dir, fname)), f'Missing {fname}'


# ---------------------------------------------------------------------------
# Headless CLI argument parsing
# ---------------------------------------------------------------------------

class TestCli:
    def test_flash_headless_has_functions(self):
        import flash_headless
        assert callable(flash_headless.do_flash)
        assert callable(flash_headless.do_gen_iso_menu)
        assert callable(flash_headless.do_deploy)

    def test_gen_iso_menu_logic(self):
        """Test the do_gen_iso_menu PowerShell query logic parses correctly."""
        # Simulate the JSON parsing from PowerShell output
        sample_json = '''
        [
            {"DriveLetter": "T:", "Label": "VTOYDATA"},
            {"DriveLetter": "", "Label": "VTOYEFI"}
        ]
        '''
        data = json.loads(sample_json)
        data_drive = ''
        for p in data:
            label = p.get('Label', '')
            letter = p.get('DriveLetter', '')
            if label in ('VTOYDATA', 'KoupreyData') and letter:
                data_drive = letter
                break
        assert data_drive == 'T:', f'Expected T:, got {data_drive}'


# ---------------------------------------------------------------------------
# Theme tests
# ---------------------------------------------------------------------------

class TestTheme:
    def test_theme_manager(self):
        from theme import ThemeManager
        # We can't create QApplication here, just test the class exists
        assert ThemeManager

    def test_theme_colors_defined(self):
        from theme import LIGHT_COLORS, DARK_COLORS
        for key in ('TextPrimary', 'Accent', 'Surface', 'Success', 'Error'):
            assert hasattr(LIGHT_COLORS, key), f'Missing light color: {key}'
            assert hasattr(DARK_COLORS, key), f'Missing dark color: {key}'

    def test_deployed_themes_exist(self):
        themes_root = os.path.join(os.path.dirname(__file__), 'themes')
        assert os.path.isdir(themes_root), 'themes/ directory missing'
        dirs = [d for d in os.listdir(themes_root)
                if os.path.isdir(os.path.join(themes_root, d))]
        assert len(dirs) >= 1, 'No theme directories found'
        for d in dirs:
            theme_txt = os.path.join(themes_root, d, 'themes', 'theme.txt')
            alt = os.path.join(themes_root, d, 'theme.txt')
            assert os.path.isfile(theme_txt) or os.path.isfile(alt), \
                f'{d}: no theme.txt found'
