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
        for name in ('choano/title-landscape.jpg', 'choano/title-portrait.jpg',
                     'choano/fish/title-landscape.jpg', 'choano/fish/title-portrait.jpg',
                     'choano/fish/turtle-hd.png', 'choano/background-inside.png',
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
        game.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$CHOANO_DATA" "$@"\n')
        shutil.copy2(ROOT / 'packaging/linux/AppRun', self.appdir / 'AppRun')
        for folder, _, _ in os.walk(self.appdir):
            os.chmod(folder, 0o555)
        caller = SCRATCH / 'caller'
        caller.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ('APPDIR', 'CHOANO_DATA')}
        for data, expected in (('profile', caller / 'profile'), ('/srv/choano', Path('/srv/choano'))):
            out = subprocess.run([self.appdir / 'AppRun', '--flag', 'two words'], cwd=caller,
                                 env=dict(env, APPDIR=str(self.appdir), CHOANO_DATA=data),
                                 capture_output=True, text=True, check=True).stdout.splitlines()
            self.assertEqual(out, [str(self.appdir / 'usr/share/choano'), str(expected), '--flag', 'two words'])
        # Opened as AppDir/AppRun without the AppImage runtime's APPDIR.
        out = subprocess.run([self.appdir / 'AppRun'], cwd=caller, env=env,
                             capture_output=True, text=True, check=True).stdout.splitlines()
        self.assertEqual(out[:2], [str(self.appdir / 'usr/share/choano'), ''])

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
