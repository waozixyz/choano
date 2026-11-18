#!/usr/bin/env python3
"""Packaging contract of the Linux AppImage, checked without its build tools."""
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('choano_desktop_release', ROOT / 'scripts/desktop_release.py')
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)
# Disposable intermediates beside the real AppDir, never under /tmp.
SCRATCH = ROOT / 'build/appimage/test'
# Sizes linuxdeploy accepts for an icon.
ICON_SIZES = {8, 16, 20, 22, 24, 28, 32, 36, 42, 48, 64, 72, 96, 128, 160, 192, 256, 384, 480, 512}


def writable(path):
    for folder, _, _ in os.walk(path):
        os.chmod(folder, 0o755)


def desktop_entry(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)


class WindowsDesktopPackageTest(unittest.TestCase):
    def test_stage_preserves_renderer_layout(self):
        scratch = ROOT / 'build/windows/stage-test'
        scratch.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, scratch)
        sdk = scratch / 'sdk'
        for name in ('bin/SDL2.dll', 'etc/fonts/fonts.conf', 'share/licenses/Cairo'):
            path = sdk / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        archive = scratch / 'runtime.tar'
        subprocess.run(['tar', '-cf', archive, '-C', sdk, 'bin', 'etc', 'share'], check=True)
        for name in ('program.exe', 'codec.dll', 'font.ttf', 'font.txt', 'assets/choano/title.avif'):
            path = scratch / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        renderer = {'runtime_archive': archive, 'resources': {
            'font': scratch / 'font.ttf', 'font_license': scratch / 'font.txt'}}
        with patch.object(desktop, 'ROOT', scratch):
            stage = desktop.stage_windows(scratch / 'stage', scratch / 'program.exe', renderer,
                                          scratch / 'codec.dll')
        for name, contents in {
            'bin/Choano.exe': 'program.exe', 'bin/kryonavif.dll': 'codec.dll',
            'bin/kryon-font.ttf': 'font.ttf', 'bin/LICENSE-Liberation': 'font.txt',
            'bin/SDL2.dll': 'bin/SDL2.dll', 'etc/fonts/fonts.conf': 'etc/fonts/fonts.conf',
            'assets/choano/title.avif': 'assets/choano/title.avif',
        }.items():
            self.assertEqual((stage / name).read_text(), contents)


class DesktopReleaseTest(unittest.TestCase):
    def setUp(self):
        if SCRATCH.exists():
            writable(SCRATCH)
            shutil.rmtree(SCRATCH)
        SCRATCH.mkdir(parents=True)
        # Only staged and copied, never run, so any file stands in for the game.
        self.binary = SCRATCH / 'Choano-native'
        self.binary.write_text('#!/bin/sh\n')
        self.binary.chmod(0o755)
        self.version = desktop.current_version()
        self.appdir = desktop.stage_appdir(SCRATCH / 'Choano.AppDir', self.binary, self.version)

    def tearDown(self):
        writable(SCRATCH)
        shutil.rmtree(SCRATCH)

    def test_appdir_carries_every_asset_unchanged(self):
        game = self.appdir / 'usr/bin/Choano'
        self.assertTrue(game.stat().st_mode & stat.S_IXUSR)
        source = ROOT / 'assets'
        staged = self.appdir / 'usr/share/choano/assets'
        names = sorted(p.relative_to(source) for p in source.rglob('*') if p.is_file())
        self.assertEqual(names, sorted(p.relative_to(staged) for p in staged.rglob('*') if p.is_file()))
        for name in names:
            self.assertEqual((source / name).read_bytes(), (staged / name).read_bytes(), name)
        # The art and music the native game opens by these paths.
        for name in ('choano/title-landscape.avif', 'choano/title-portrait.avif',
                     'choano/fish/title-landscape.avif', 'choano/fish/title-portrait.avif',
                     'choano/fish/turtle-hd.avif', 'choano/background-inside.avif',
                     'choano/audio/shark-music.wav'):
            self.assertIn(Path(name), names)

    def test_metadata_names_one_identity_and_the_release_version(self):
        entry = desktop_entry(self.appdir / 'usr/share/applications/xyz.waozi.choano.desktop')
        self.assertEqual(entry['Exec'], 'Choano')
        self.assertEqual(entry['Icon'], 'xyz.waozi.choano')
        self.assertIn('Game', entry['Categories'].split(';'))
        self.assertEqual(entry['X-AppImage-Version'], self.version)
        metainfo = (self.appdir / 'usr/share/metainfo/xyz.waozi.choano.appdata.xml').read_text()
        self.assertIn('<id>xyz.waozi.choano</id>', metainfo)
        self.assertIn('<launchable type="desktop-id">xyz.waozi.choano.desktop</launchable>', metainfo)
        from PIL import Image
        icon = self.appdir / f'usr/share/icons/hicolor/{desktop.ICON_SIZE}x{desktop.ICON_SIZE}/apps/xyz.waozi.choano.png'
        with Image.open(icon) as image:
            self.assertEqual(image.size, (desktop.ICON_SIZE, desktop.ICON_SIZE))
            self.assertIn(desktop.ICON_SIZE, ICON_SIZES)
            self.assertEqual(image.getpixel((0, 0))[3], 255, 'icon corners stay filled with its water')
        public = [name for name in desktop.expected_assets(self.version) if name.endswith('.AppImage')]
        self.assertEqual(public, [f'choano-v{self.version}-linux-x86_64.AppImage'])

    def test_launcher_starts_in_its_read_only_share_folder(self):
        game = self.appdir / 'usr/bin/Choano'
        game.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$GDK_PIXBUF_MODULE_FILE" "$CHOANO_DATA" "$@"\n')
        shutil.copy2(ROOT / 'packaging/linux/AppRun', self.appdir / 'AppRun')
        for folder, _, _ in os.walk(self.appdir):
            os.chmod(folder, 0o555)
        caller = SCRATCH / 'caller'
        caller.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ('APPDIR', 'CHOANO_DATA')}
        # A host's own loader list never reaches the bundled GdkPixbuf.
        env['GDK_PIXBUF_MODULE_FILE'] = '/usr/lib/x86_64-linux-gnu/gdk-pixbuf-2.0/2.10.0/loaders.cache'
        modules = str(self.appdir / desktop.PIXBUF_MODULES)
        for data, expected in (('profile', caller / 'profile'), ('/srv/choano', Path('/srv/choano'))):
            out = subprocess.run([self.appdir / 'AppRun', '--flag', 'two words'], cwd=caller,
                                 env=dict(env, APPDIR=str(self.appdir), CHOANO_DATA=data),
                                 capture_output=True, text=True, check=True).stdout.splitlines()
            self.assertEqual(out, [str(self.appdir / 'usr/share/choano'), modules, str(expected),
                                   '--flag', 'two words'])
        # Opened as AppDir/AppRun without the AppImage runtime's APPDIR.
        out = subprocess.run([self.appdir / 'AppRun'], cwd=caller, env=env,
                             capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertEqual(out[:3], [str(self.appdir / 'usr/share/choano'), modules, ''])

    def test_image_decoders_come_only_from_the_appdir(self):
        lines = (self.appdir / desktop.PIXBUF_MODULES).read_text().splitlines()
        self.assertTrue(lines and all(line.startswith('#') for line in lines),
                        'the module list names no loader, so no host module loads')
        # GdkPixbuf linked into an AppDir that lacks its GLib takes the host's.
        host = desktop.system_library(desktop.PIXBUF)
        lib = self.appdir / 'usr/lib'
        lib.mkdir(parents=True, exist_ok=True)
        shutil.copy2(host, lib / desktop.PIXBUF)
        with self.assertRaises(SystemExit) as failure:
            desktop.check_pixbuf_decoder(self.appdir)
        self.assertIn("loaded the host's", str(failure.exception))
        (lib / desktop.PIXBUF).write_bytes(b'not a library')
        with self.assertRaises(SystemExit) as failure:
            desktop.check_pixbuf_decoder(self.appdir)
        self.assertIn('cannot decode the art', str(failure.exception))

    def test_avif_art_needs_the_appdir_codec(self):
        with self.assertRaises(SystemExit) as failure:
            desktop.check_image_decoders(self.appdir)
        self.assertIn('carries no libkryonavif.so', str(failure.exception))
        lib = self.appdir / 'usr/lib'
        lib.mkdir(parents=True, exist_ok=True)
        (lib / desktop.AVIF).write_bytes(b'not a library')
        with self.assertRaises(SystemExit) as failure:
            desktop.check_avif_decoder(self.appdir)
        self.assertIn('cannot decode the art', str(failure.exception))

    def test_tools_are_pinned_and_a_mismatch_is_rejected(self):
        for name, (url, digest) in desktop.TOOLS.items():
            self.assertTrue(url.startswith('https://github.com/linuxdeploy/') and url.endswith('/' + name), url)
            self.assertNotIn('/continuous/', url)
            self.assertRegex(digest, '^[0-9a-f]{64}$')
        payload = SCRATCH / 'download/tool.AppImage'
        payload.parent.mkdir()
        payload.write_bytes(b'not the pinned tool')
        tools, tools_dir = desktop.TOOLS, desktop.TOOLS_DIR
        desktop.TOOLS = {'tool.AppImage': (payload.as_uri(), '0' * 64)}
        desktop.TOOLS_DIR = SCRATCH / 'tools'
        try:
            with self.assertRaises(SystemExit):
                desktop.fetch_tool('tool.AppImage')
            self.assertEqual(list(desktop.TOOLS_DIR.iterdir()), [])
            desktop.TOOLS = {'tool.AppImage': (payload.as_uri(), desktop.sha256(payload))}
            self.assertEqual(desktop.fetch_tool('tool.AppImage').read_bytes(), b'not the pinned tool')
        finally:
            desktop.TOOLS, desktop.TOOLS_DIR = tools, tools_dir


if __name__ == '__main__':
    unittest.main()
