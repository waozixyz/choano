"""Release publishing against a fake GitHub: exact downloads, gating runs,
retries and releases that must stay untouched."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('choano_publish_release', ROOT / 'scripts/publish_release.py')
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)
from release import ReleaseError, expected_assets

REPO = 'waozixyz/choano'
REVISION = 'a' * 40
OTHER = 'b' * 40
VERSION = '0.1.0'
CHANGELOG = f'# Changelog\n\n## [Unreleased]\n\n## [{VERSION}] - 2026-10-29\n\n- Swim.\n\n## [0.0.1]\n\n- Old.\n'
MUTATING = {('release', 'create'), ('release', 'upload'), ('release', 'edit'), ('release', 'delete-asset')}


def apk(edition):
    return b'PK\x03\x04' + edition.encode() * 50


def appimage(machine=0x3E):
    head = bytearray(b'\x7fELF' + b'\0' * 60)
    head[8:11] = b'AI\x02'
    struct.pack_into('<H', head, 18, machine)
    return bytes(head) + b'squashfs' * 20


def windows(machine=0x8664):
    data = bytearray(b'MZ' + b'\0' * 254)
    struct.pack_into('<I', data, 0x3C, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<H', data, 0x84, machine)
    return bytes(data) + b'installer' * 20


def downloads(version=VERSION):
    normal, fdroid, gplay, linux, setup = expected_assets(version)
    return {normal: apk('direct'), fdroid: apk('direct'), gplay: apk('gplay'), linux: appimage(), setup: windows()}


def run(id, workflow, status='completed', conclusion='success', sha=REVISION, branch='master',
        event='push', repo=REPO):
    return {'id': id, 'workflow': workflow, 'head_sha': sha, 'head_branch': branch, 'event': event,
            'status': status, 'conclusion': conclusion, 'head_repository': {'full_name': repo}}


class GhFailure(publish.GhError):
    def __init__(self, args, stderr):
        super().__init__(args, 1, stderr)


class FakeGitHub:
    """Answers the gh calls publish_release makes, from in-memory state."""

    def __init__(self):
        self.calls = []
        self.runs = [run(10, 'android.yml'), run(20, 'site.yml')]
        self.artifacts = {10: {'choano-android-direct': {}, 'choano-android-gplay': {}}}
        for name, data in downloads().items():
            artifact = 'choano-android-gplay' if name.endswith('-gplay.apk') else 'choano-android-direct'
            if name.endswith('.apk'):
                self.artifacts[10][artifact][name] = data
        self.release = None  # {'isDraft', 'targetCommitish', 'assets': {name: bytes}}
        self.tags = {}       # name -> commit
        self.annotated = {}  # tag object sha -> commit
        self.master_status = 'identical'
        self.finish_on_watch = {}
        self.drop_upload = None

    def mutations(self):
        return [call for call in self.calls if tuple(call[:2]) in MUTATING]

    def __call__(self, *args):
        args = [str(arg) for arg in args]
        self.calls.append(args)
        if args[0] == 'api':
            return self.api(args)
        if args[:2] == ['run', 'watch']:
            run_id = int(args[2])
            for entry in self.runs:
                if entry['id'] == run_id:
                    entry.update(status='completed', conclusion=self.finish_on_watch.get(run_id, 'success'))
                    if entry['conclusion'] != 'success':
                        raise GhFailure(args, 'run failed')
            return ''
        if args[:2] == ['run', 'download']:
            files = self.artifacts.get(int(args[2]), {}).get(args[args.index('-n') + 1])
            if files is None:
                raise GhFailure(args, 'no valid artifacts found to download')
            target = Path(args[args.index('-D') + 1])
            target.mkdir(parents=True)
            for name, data in files.items():
                (target / name).write_bytes(data)
            return ''
        assert args[0] == 'release' and args[3] == '-R' and args[4] == REPO, args
        action, tag = args[1], args[2]
        assert tag == f'v{VERSION}', args
        if action == 'view':
            if self.release is None:
                raise GhFailure(args, 'release not found')
            return json.dumps({'tagName': tag, 'isDraft': self.release['isDraft'],
                               'targetCommitish': self.release['targetCommitish'],
                               'assets': [{'name': name, 'size': len(data), 'state': 'uploaded',
                                           'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}
                                          for name, data in self.release['assets'].items()]})
        if action == 'create':
            assert self.release is None
            self.release = {'isDraft': '--draft' in args, 'targetCommitish': args[args.index('--target') + 1],
                            'assets': {}}
            return ''
        if action == 'upload':
            assert args[5] == '--clobber', args
            for path in args[6:]:
                if Path(path).name != self.drop_upload:
                    self.release['assets'][Path(path).name] = Path(path).read_bytes()
            return ''
        if action == 'delete-asset':
            del self.release['assets'][args[5]]
            return ''
        if action == 'edit':
            if '--draft=false' in args:
                self.release['isDraft'] = False
                self.tags.setdefault(tag, self.release['targetCommitish'])
            return ''
        raise AssertionError(args)

    def api(self, args):
        path = next(arg for arg in args[1:] if arg.startswith('repos/'))
        assert path.startswith(f'repos/{REPO}/'), path
        path = path[len(f'repos/{REPO}/'):]
        found = re.fullmatch(r'actions/workflows/([\w.]+)/runs', path)
        if found:
            sha = next(arg.split('=', 1)[1] for arg in args if arg.startswith('head_sha='))
            return json.dumps({'workflow_runs': [entry for entry in self.runs
                                                 if entry['workflow'] == found[1] and entry['head_sha'] == sha]})
        if path == f'compare/{REVISION}...master':
            return json.dumps({'status': self.master_status})
        if path.startswith('git/ref/tags/'):
            tag = path.rsplit('/', 1)[1]
            if tag in self.tags:
                return json.dumps({'object': {'type': 'commit', 'sha': self.tags[tag]}})
            for sha, commit in self.annotated.items():
                if tag == 'v' + VERSION:
                    return json.dumps({'object': {'type': 'tag', 'sha': sha}})
            raise GhFailure(args, 'gh: Not Found (HTTP 404)')
        if path.startswith('git/tags/'):
            return json.dumps({'object': {'type': 'commit', 'sha': self.annotated[path.rsplit('/', 1)[1]]}})
        raise AssertionError(args)


class PublishReleaseTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(dir=ROOT / 'build' if (ROOT / 'build').is_dir() else None))
        self.addCleanup(shutil.rmtree, self.folder)
        self.assets = self.folder / 'release'
        self.assets.mkdir()
        self.github = FakeGitHub()
        self.verified = []

    def put(self, files):
        for name, data in files.items():
            (self.assets / name).write_bytes(data)

    def publish(self, revision=REVISION, version=VERSION, checkout=REVISION, source=VERSION):
        return publish.publish_release(
            revision, version, self.assets, repo=REPO, gh=self.github,
            verify_apk=lambda path, edition: self.verified.append((path.name, edition)),
            checkout=lambda: checkout, source_version=lambda: source, changelog=CHANGELOG)

    def test_publishes_a_new_release_at_the_exact_commit(self):
        self.put(downloads())
        self.assertEqual(self.publish(), 'released')
        release = self.github.release
        self.assertFalse(release['isDraft'])
        self.assertEqual(release['targetCommitish'], REVISION)
        self.assertEqual(self.github.tags, {f'v{VERSION}': REVISION})
        self.assertEqual(sorted(release['assets']), sorted([*expected_assets(VERSION), 'SHA256SUMS']))
        for name, data in downloads().items():
            self.assertEqual(release['assets'][name], data)
            self.assertIn(f'{hashlib.sha256(data).hexdigest()}  {name}\n', release['assets']['SHA256SUMS'].decode())
        self.assertEqual(sorted(self.verified), sorted([
            (f'choano-v{VERSION}.apk', 'direct'), (f'choano-{VERSION}-fdroid.apk', 'direct'),
            (f'choano-v{VERSION}-gplay.apk', 'gplay')]))
        create = next(call for call in self.github.calls if call[:2] == ['release', 'create'])
        self.assertEqual(create[create.index('--target') + 1], REVISION)
        self.assertIn('--draft', create)
        notes = Path(create[create.index('--notes-file') + 1]).read_text()
        self.assertEqual(notes, '- Swim.\n')
        # Publishing comes last, after every upload.
        self.assertEqual(self.github.mutations()[-1][:2], ['release', 'edit'])
        self.assertIn('--draft=false', self.github.mutations()[-1])

    def test_missing_extra_empty_and_misnamed_downloads_stop_before_github_changes(self):
        normal, fdroid, gplay, linux, setup = expected_assets(VERSION)
        cases = {
            'missing': lambda: (self.assets / setup).unlink(),
            'extra': lambda: (self.assets / 'notes.txt').write_text('x'),
            'empty': lambda: (self.assets / linux).write_bytes(b''),
            'other version': lambda: (self.assets / normal).rename(self.assets / 'choano-v0.2.0.apk'),
            'symlink': lambda: ((self.assets / fdroid).unlink(), (self.assets / fdroid).symlink_to(self.assets / normal)),
            'not an apk': lambda: (self.assets / gplay).write_bytes(b'garbage' * 10),
            'arm appimage': lambda: (self.assets / linux).write_bytes(appimage(machine=0xB7)),
            'plain elf': lambda: (self.assets / linux).write_bytes(b'\x7fELF' + b'\0' * 100),
            'arm64 exe': lambda: (self.assets / setup).write_bytes(windows(machine=0xAA64)),
            'truncated exe': lambda: (self.assets / setup).write_bytes(windows()[:0x82]),
            'truncated appimage': lambda: (self.assets / linux).write_bytes(appimage()[:12]),
            'not an exe': lambda: (self.assets / setup).write_bytes(b'#!/bin/sh\n' * 10),
        }
        for name, damage in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.assets)
                self.assets.mkdir()
                self.github = FakeGitHub()
                self.put(downloads())
                damage()
                with self.assertRaises(ReleaseError):
                    self.publish()
                self.assertEqual(self.github.mutations(), [])

    def test_a_failing_apk_verification_stops_the_release(self):
        self.put(downloads())

        def reject(path, edition):
            raise publish.subprocess.CalledProcessError(1, ['android.py', 'verify', str(path)])
        with self.assertRaises(publish.subprocess.CalledProcessError):
            publish.publish_release(REVISION, VERSION, self.assets, repo=REPO, gh=self.github, verify_apk=reject,
                                    checkout=lambda: REVISION, source_version=lambda: VERSION, changelog=CHANGELOG)
        self.assertEqual(self.github.mutations(), [])

    def test_published_releases_are_never_changed(self):
        for target in (REVISION, OTHER):
            with self.subTest(target):
                self.github = FakeGitHub()
                self.github.release = {'isDraft': False, 'targetCommitish': target, 'assets': {'old.apk': b'1'}}
                self.github.tags = {f'v{VERSION}': target}
                self.put(downloads())
                self.assertEqual(self.publish(), 'published')
                self.assertEqual(self.github.mutations(), [])
                self.assertEqual(self.github.release['assets'], {'old.apk': b'1'})

    def test_resumes_this_commits_draft_replacing_partial_uploads(self):
        self.put(downloads())
        self.github.release = {'isDraft': True, 'targetCommitish': REVISION,
                               'assets': {f'choano-v{VERSION}.apk': b'partial', 'stray.zip': b'z'}}
        self.assertEqual(self.publish(), 'released')
        self.assertNotIn('stray.zip', self.github.release['assets'])
        self.assertEqual(self.github.release['assets'][f'choano-v{VERSION}.apk'], downloads()[f'choano-v{VERSION}.apk'])
        self.assertFalse(self.github.release['isDraft'])
        self.assertEqual(self.github.tags[f'v{VERSION}'], REVISION)
        self.assertFalse(any(call[:2] == ['release', 'create'] for call in self.github.calls))

    def test_a_draft_or_tag_of_another_commit_stops_without_changes(self):
        for setup in ('draft', 'tag', 'annotated tag'):
            with self.subTest(setup):
                self.github = FakeGitHub()
                if setup == 'draft':
                    self.github.release = {'isDraft': True, 'targetCommitish': OTHER, 'assets': {}}
                elif setup == 'tag':
                    self.github.tags = {f'v{VERSION}': OTHER}
                else:
                    self.github.annotated = {'c' * 40: OTHER}
                self.put(downloads())
                with self.assertRaises(ReleaseError):
                    self.publish()
                self.assertEqual(self.github.mutations(), [])

    def test_an_existing_tag_at_this_commit_is_released(self):
        self.github.annotated = {'c' * 40: REVISION}
        self.put(downloads())
        self.assertEqual(self.publish(), 'released')

    def test_an_incomplete_upload_is_never_published(self):
        self.put(downloads())
        self.github.drop_upload = f'choano-v{VERSION}-windows-x86_64-setup.exe'
        with self.assertRaises(ReleaseError):
            self.publish()
        self.assertTrue(self.github.release['isDraft'])
        self.assertNotIn(f'v{VERSION}', self.github.tags)

    def test_source_must_be_the_candidate_on_master_at_its_version(self):
        self.put(downloads())
        for name, kwargs, status in (
                ('short revision', {'revision': 'a' * 12, 'checkout': 'a' * 12}, 'identical'),
                ('other checkout', {'checkout': OTHER}, 'identical'),
                ('other changelog version', {'source': '0.2.0'}, 'identical'),
                ('not on master', {}, 'diverged'),
                ('behind', {}, 'behind')):
            with self.subTest(name):
                self.github = FakeGitHub()
                self.github.master_status = status
                with self.assertRaises(ReleaseError):
                    self.publish(**kwargs)
                self.assertEqual(self.github.mutations(), [])

    def test_publishing_requires_both_successful_gates(self):
        self.put(downloads())
        for name, runs in (
                ('android failed', [run(10, 'android.yml', conclusion='failure'), run(20, 'site.yml')]),
                ('site still running', [run(10, 'android.yml'), run(20, 'site.yml', status='in_progress', conclusion=None)]),
                ('site missing', [run(10, 'android.yml')]),
                ('android of another commit', [run(10, 'android.yml', sha=OTHER), run(20, 'site.yml')]),
                ('android from a pull request', [run(10, 'android.yml', event='pull_request'), run(20, 'site.yml')]),
                ('android from a fork', [run(10, 'android.yml', repo='someone/choano'), run(20, 'site.yml')]),
                ('android on a branch', [run(10, 'android.yml', branch='topic'), run(20, 'site.yml')])):
            with self.subTest(name):
                self.github = FakeGitHub()
                self.github.runs = runs
                with self.assertRaises(ReleaseError):
                    self.publish()
                self.assertEqual(self.github.mutations(), [])

    def test_checks_wait_for_running_gates_and_take_the_android_apks(self):
        self.github.runs = [run(10, 'android.yml', status='in_progress', conclusion=None),
                            run(9, 'android.yml', conclusion='failure'),
                            run(20, 'site.yml', status='queued', conclusion=None)]
        self.assertEqual(publish.await_checks(REPO, REVISION, VERSION, self.assets, gh=self.github), 10)
        watched = [call[2] for call in self.github.calls if call[:2] == ['run', 'watch']]
        self.assertEqual(watched, ['10', '20'])
        self.assertTrue(all('--exit-status' in call for call in self.github.calls if call[:2] == ['run', 'watch']))
        self.assertEqual(sorted(path.name for path in self.assets.iterdir()),
                         sorted(name for name in expected_assets(VERSION) if name.endswith('.apk')))

    def test_checks_fail_when_a_gate_fails_or_artifacts_are_wrong(self):
        cases = {
            'android fails': lambda github: (github.runs.__setitem__(0, run(10, 'android.yml', status='in_progress',
                                                                              conclusion=None)),
                                             github.finish_on_watch.__setitem__(10, 'failure')),
            'artifacts expired': lambda github: github.artifacts.pop(10),
            'stray artifact file': lambda github: github.artifacts[10]['choano-android-gplay'].update({'x.apk': b'1'}),
            'other version apk': lambda github: github.artifacts[10].__setitem__(
                'choano-android-gplay', {'choano-v0.2.0-gplay.apk': apk('gplay')}),
        }
        for name, damage in cases.items():
            with self.subTest(name):
                self.github = FakeGitHub()
                damage(self.github)
                with self.assertRaises(ReleaseError):
                    publish.await_checks(REPO, REVISION, VERSION, self.assets, gh=self.github)

    def test_due_only_while_unpublished(self):
        due = lambda: publish.due(REPO, REVISION, gh=self.github, checkout=lambda: REVISION,
                                  source_version=lambda: VERSION)
        self.assertEqual(due(), (VERSION, True))
        self.github.release = {'isDraft': True, 'targetCommitish': REVISION, 'assets': {}}
        self.assertEqual(due(), (VERSION, True))
        self.github.release['isDraft'] = False
        self.assertEqual(due(), (VERSION, False))

    def test_android_workflow_produces_the_artifacts_the_release_takes(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/android.yml').read_text())
        job = workflow['jobs']['android']
        upload = next(step for step in job['steps'] if step.get('uses', '').startswith('actions/upload-artifact'))
        names = {upload['with']['name'].replace('${{ matrix.edition }}', edition)
                 for edition in job['strategy']['matrix']['edition']}
        self.assertEqual(names, set(publish.ANDROID_ARTIFACTS))
        self.assertEqual(sorted(n for f in publish.ANDROID_ARTIFACTS.values() for n in f(VERSION)),
                         sorted(name for name in expected_assets(VERSION) if name.endswith('.apk')))
        triggers = workflow[True] if True in workflow else workflow['on']
        self.assertEqual(triggers['push']['branches'], ['master'])


if __name__ == '__main__':
    unittest.main()
