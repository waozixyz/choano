import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load('choano_release', ROOT / 'scripts/release.py')
sys.path.insert(0, str(ROOT / 'scripts'))
android = load('choano_android', ROOT / 'scripts/android.py')


class ReleaseTest(unittest.TestCase):
    def test_parses_first_numbered_release(self):
        changelog = '# Changelog\n\n## [Unreleased]\n\n- New.\n\n## [1.2.3] - 2026-01-01\n'
        self.assertEqual(release.release_version(changelog), '1.2.3')
        self.assertEqual(release.android_code('1.2.3'), 10203)
        self.assertEqual(release.release_version('## [0.1.0] - 2026-10-29'), '0.1.0')
        self.assertEqual(release.android_code('0.1.0'), 100)

    def test_rejects_invalid_and_overflowing_releases(self):
        for changelog in ('', '# Changelog\n', '## [0.0.0]\n', '## [0.01.0]\n',
                          '## [1.2]\n', '## [210000.0.0]\n', '## [0.100.0]\n',
                          '## [0.01.0]\n\n## [1.0.0]\n'):
            with self.assertRaises(release.ReleaseError):
                release.release_version(changelog)

    def test_expected_assets_are_exact(self):
        self.assertEqual(release.expected_assets('0.1.0'), (
            'choano-v0.1.0.apk',
            'choano-0.1.0-fdroid.apk',
            'choano-v0.1.0-gplay.apk',
            'choano-v0.1.0-linux-x86_64.AppImage',
            'choano-v0.1.0-windows-x86_64-setup.exe',
        ))

    def test_canonical_version_must_match_changelog(self):
        changelog = '## [0.1.0] - 2026-10-29\n'
        self.assertEqual(release.release_version(changelog, '0.1.0'), '0.1.0')
        with self.assertRaises(release.ReleaseError):
            release.release_version(changelog, '0.2.0')

    def test_android_keeps_pre_release_fallback(self):
        original_root = android.ROOT
        with tempfile.TemporaryDirectory() as folder:
            android.ROOT = Path(folder)
            try:
                self.assertEqual(android.version(), ('0.0.0', 1))
                (android.ROOT / 'CHANGELOG.md').write_text('## [2.3.4]\n')
                self.assertEqual(android.version(), ('2.3.4', 20304))
            finally:
                android.ROOT = original_root

    def test_updater_synchronizes_version_strictly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            shutil.copy2(ROOT / 'scripts/release.py', root / 'scripts/release.py')
            updater = root / 'update_version.sh'
            shutil.copy2(ROOT / 'update_version.sh', updater)
            changelog = root / 'CHANGELOG.md'
            changelog.write_text('# Changelog\n\n## [Unreleased]\n')
            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.run(['sh', updater], check=True, capture_output=True, text=True)
            self.assertFalse((root / 'VERSION').exists())

            changelog.write_text('# Changelog\n\n## [1.2.3] - 2026-01-01\n')
            subprocess.run(['sh', updater], check=True, capture_output=True, text=True)
            self.assertEqual((root / 'VERSION').read_text(), '1.2.3\n')

            changelog.write_text('# Changelog\n\n## [1.2.4] - 2026-01-02\n')
            subprocess.run(['sh', updater], check=True, capture_output=True, text=True)
            self.assertEqual((root / 'VERSION').read_text(), '1.2.4\n')

            changelog.write_text('# Changelog\n\n## [0.0.0]\n')
            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.run(['sh', updater], check=True, capture_output=True, text=True)
            self.assertEqual((root / 'VERSION').read_text(), '1.2.4\n')


if __name__ == '__main__':
    unittest.main()
