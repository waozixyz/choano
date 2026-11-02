#!/usr/bin/env python3
"""The native account provider's build and packaging glue, and the account
adapter's source contract. The actual provider build is `make native`."""
import importlib.util
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def load(name):
    spec = importlib.util.spec_from_file_location('choano_' + name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load('build')
android = load('android')
desktop = load('desktop_release')
API = ['Service ::', 'Available ::', 'Pump ::', 'OpenProfile ::', 'ProfileVisible ::', 'DrawProfile ::',
       'Back ::', 'Close ::']


class Artifact:
    def __init__(self, flags):
        self.flags = flags
        self.calls = []

    def link_flags(self, **options):
        self.calls.append(options)
        return self.flags


class AccountBuildTest(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / 'work/account-build-test'
        subprocess.run(['git', 'check-ignore', str(scratch)], check=True, stdout=subprocess.DEVNULL)
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_native_defines_accounts_and_replaces_the_stable_program(self):
        work = self.root / 'native'
        work.mkdir()
        (work / 'desktop').write_bytes(b'new program')
        program = self.root / 'Choano-native'
        program.write_bytes(b'old program')
        with patch.object(build, 'run') as run, patch.object(build, 'profile_asset') as profile, \
                patch.object(build, 'renderer_links', return_value=['renderer.a']), \
                patch.object(build, 'account_links', return_value=['libmonocypher.a', '-lgtk']) as accounts, \
                patch.object(build, 'NATIVE_WORK', work), patch.object(build, 'NATIVE', program):
            build.native()
        profile.assert_called_once()
        accounts.assert_called_once_with('linux-x86_64-gnu')
        command = list(map(str, run.call_args.args))
        for define in ('CHOANO_ACCOUNTS', 'POSIX_THREADS'):
            self.assertIn(define, command)
            self.assertEqual(command[command.index(define) - 1], '--define')
        self.assertIn('desktop:main', command)
        self.assertEqual(command[-1], 'src/desktop.zi')
        links = shlex.split(run.call_args.kwargs['env']['LDLIBS'])
        self.assertEqual(links[:3], ['renderer.a', 'libmonocypher.a', '-lgtk'])
        self.assertEqual(program.read_bytes(), b'new program')
        self.assertTrue(os.access(program, os.X_OK))
        self.assertEqual((self.root / 'Choano-native.title').read_text(), 'Choano\n')

    def test_account_links_use_the_provider_crypto_then_profile_libraries(self):
        artifact = Artifact(['libmonocypher.a', 'liboqs.a', '-lm'])
        with patch.object(build, 'artifact', return_value=artifact) as request:
            self.assertEqual(build.account_links('windows-x86_64-mingw', {'CC': 'gcc'}),
                             ['libmonocypher.a', 'liboqs.a', '-lm', '-flto=1', '-luser32', '-lshell32', '-lole32',
                              '-lcomdlg32'])
        request.assert_called_once_with('entity:native-crypto', 'windows-x86_64-mingw', {'CC': 'gcc'})
        self.assertEqual(artifact.calls, [dict(env={'CC': 'gcc'})])
        with patch.object(build, 'artifact', return_value=Artifact(['libz.a'])), \
                patch.object(subprocess, 'check_output', return_value='-lgtk-3 -lcairo\n') as config:
            self.assertEqual(build.account_links('linux-x86_64-gnu'), ['libz.a', '-lgtk-3', '-lcairo', '-lX11'])
        self.assertIn('gtk+-3.0', config.call_args.args[0])

    def test_profile_asset_is_generated_ignored_and_kept_from_guest_bundles(self):
        subprocess.run(['git', 'check-ignore', 'assets/entity.zx'], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        self.assertEqual(build.without_profile(str(ROOT / 'assets'), ['entity.zx', 'choano']),
                         ['entity.zx', 'entity.zx.new'])
        self.assertEqual(build.without_profile(str(ROOT / 'assets/choano'), ['entity.zx']), [])
        source = (ROOT / 'scripts/build.py').read_text()
        self.assertIn("'assets=' + str(staged)", source)
        self.assertNotIn("'assets=assets'", source)
        self.assertIn("output / 'assets', ignore=without_profile", source)

    def test_profile_asset_replaces_the_generated_copy(self):
        bundle = self.root / 'entity.zx'
        target = self.root / 'assets/entity.zx'
        target.parent.mkdir()
        with patch.object(build, 'profile', side_effect=lambda: bundle.write_bytes(b'profile')), \
                patch.object(build, 'ROOT', self.root), patch.object(build, 'PROFILE_ASSET', target):
            (self.root / 'build').mkdir()
            bundle = self.root / 'build/entity.zx'
            build.profile_asset()
        self.assertEqual(target.read_bytes(), b'profile')
        self.assertFalse(target.with_name('entity.zx.new').exists())

    def test_android_manifest_may_reach_the_account_node(self):
        manifest = (ROOT / 'packaging/android/AndroidManifest.xml').read_text()
        self.assertIn('android.permission.INTERNET', manifest)

    def test_android_system_backups_leave_out_the_account_key(self):
        manifest = (ROOT / 'packaging/android/AndroidManifest.xml').read_text()
        self.assertIn('@xml/backup_rules', manifest)
        self.assertIn('@xml/data_extraction_rules', manifest)
        for name, count in (('backup_rules', 1), ('data_extraction_rules', 2)):
            rules = (ROOT / f'packaging/android/res/xml/{name}.xml').read_text()
            self.assertEqual(rules.count('<exclude domain="file" path="profile/" />'), count)

    def test_android_links_entity_crypto_per_abi(self):
        cpp = self.root / 'droid/app/src/main/cpp'
        cpp.mkdir(parents=True)
        cmake = cpp / 'CMakeLists.txt'
        cmake.write_text('set(APP_ZIRAN_DEFINES --define ANDROID_BUILD)\nadd_library(main SHARED x.c)\n')
        ndk = self.root / 'ndk'
        ndk.mkdir()
        requests = []

        class Helper:
            @staticmethod
            def request(selection, platform, **options):
                requests.append((selection, platform, options))
                return Artifact(['/cache/' + platform + '/libmonocypher.a', '-lm'])

        fake_build = type('Build', (), {'shared_script': staticmethod(lambda owner, name: Helper)})
        with patch.object(android, 'ROOT', self.root), patch.object(android, 'ndk_folder', return_value=ndk), \
                patch.dict(sys.modules, build=fake_build):
            android.account_provider(self.root, 'gplay', 'arm64-v8a,armeabi-v7a')
            android.account_provider(self.root, 'gplay', 'arm64-v8a,armeabi-v7a')
        text = cmake.read_text()
        self.assertEqual(text.count('CHOANO_ACCOUNTS'), 1)
        self.assertEqual(text.count(android.ACCOUNT_MARKER), 1)
        self.assertIn('"/cache/android-aarch64-bionic/libmonocypher.a"', text)
        self.assertIn('if(ANDROID_ABI STREQUAL "armeabi-v7a")', text)
        selection, platform, options = requests[0]
        self.assertEqual((selection, platform), ('entity:native-crypto', 'android-aarch64-bionic'))
        self.assertIn('entity:android_api=23', options['options'])
        self.assertIn('entity:edition=play', options['options'])
        self.assertTrue(options['env']['CC'].endswith('aarch64-linux-android23-clang'))
        with self.assertRaises(SystemExit):
            android.account_provider(self.root, 'direct', 'x86_64')

    def test_release_recipes_package_the_profile(self):
        self.assertIn('CHOANO_ACCOUNTS', desktop.WINDOWS_DEFINES)
        windows = (ROOT / 'scripts/desktop_release.py').read_text()
        self.assertIn("'profile-asset'", windows)
        self.assertIn("account_links('windows-x86_64-mingw', env)", windows)
        apk = (ROOT / 'scripts/android.py').read_text()
        self.assertIn("'profile-asset'", apk)
        self.assertIn("'assets/assets/entity.zx' in names", apk)

    def test_adapter_source_contract(self):
        source = (ROOT / 'src/account.zi').read_text()
        branches = re.split(r'\n\} else #if #defined\(|\n\} else \{\n', source)
        self.assertEqual(len(branches), 4)
        for branch in branches:
            for name in API:
                self.assertIn(name, branch)
        native = branches[2]
        self.assertTrue(native.startswith('CHOANO_ACCOUNTS'))
        self.assertIn('"assets/entity.zx"', native)
        self.assertIn('Prefs.Root()', native)
        self.assertIn('"profile")', native)
        # A provider that is not running answers no shop, Dew or ownership.
        guarded = native[native.index('Service :: '):native.index('Available :: ')]
        self.assertLess(guarded.index('if !ready'), guarded.index('EntityGameShopAnswer'))
        self.assertIn('return ""', guarded[:guarded.index('EntityRecordsAnswer')])
        portable = branches[0]
        self.assertIn('Runtime.Service("entity.dew", TextUntilNul(shop_request[:]))', portable)
        self.assertIn('request.count >= 120', portable)
        self.assertNotIn('native_host', portable)
        self.assertNotIn('EntityHostOpen', branches[1])
        progress = (ROOT / 'src/progress.zi').read_text()
        self.assertIn('Account :: #import "account";', progress)


if __name__ == '__main__':
    unittest.main()
