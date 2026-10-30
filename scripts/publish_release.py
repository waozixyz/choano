#!/usr/bin/env python3
"""Publish one Choano version as a GitHub Release of one exact source commit.

    python3 scripts/publish_release.py due --revision SHA
    python3 scripts/publish_release.py checks --revision SHA DIR
    python3 scripts/publish_release.py publish --revision SHA --version VERSION DIR

`due` says whether the changelog's version at SHA still needs releasing.
`checks` waits for the Android and Choano workflows of SHA on master, which
must succeed, and copies the Android run's signed APKs into DIR. `publish`
checks DIR holds exactly the five downloads of release.expected_assets(),
signed and built for the right machines, writes SHA256SUMS beside them,
uploads them to a draft targeting SHA and only then publishes it; publishing
the draft creates the vVERSION tag. A published release is never changed, and
a draft or tag of another commit stops the run. Every GitHub call goes through
the gh command, so the tests replace it with a fake GitHub.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release import ReleaseError, current_version, expected_assets

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'master'
CHECKSUMS = 'SHA256SUMS'
# Workflows whose success on the exact commit gates a release.
ANDROID_WORKFLOW = 'android.yml'
SITE_WORKFLOW = 'site.yml'
# The Android workflow's artifacts and the downloads each one holds.
ANDROID_ARTIFACTS = {
    'choano-android-direct': lambda version: (f'choano-v{version}.apk', f'choano-{version}-fdroid.apk'),
    'choano-android-gplay': lambda version: (f'choano-v{version}-gplay.apk',),
}
# Runs of these events build master's own commits with the release secrets.
TRUSTED_EVENTS = ('push', 'workflow_dispatch')
_REVISION = re.compile(r'^[0-9a-f]{40}$')


class GhError(RuntimeError):
    def __init__(self, args, code, stderr):
        super().__init__(f'gh {" ".join(args)} failed ({code}): {stderr.strip()}')
        self.stderr = stderr

    @property
    def not_found(self):
        return 'HTTP 404' in self.stderr or 'release not found' in self.stderr


def gh(*args):
    """The real gh command; GitHub's answer on stdout."""
    done = subprocess.run(['gh', *map(str, args)], text=True, capture_output=True)
    if done.returncode:
        raise GhError(list(map(str, args)), done.returncode, done.stderr)
    return done.stdout


def checkout_revision():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def verify_apk(path, edition):
    """Package, version, release key, both ARM ABIs and the edition's Google
    rules, through the same check signing used."""
    command = [sys.executable, str(ROOT / 'scripts/android.py'), 'verify', str(path)]
    if edition == 'gplay':
        command += ['--edition', 'gplay']
    subprocess.run(command, check=True)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def require_revision(revision):
    if not _REVISION.fullmatch(revision or ''):
        raise ReleaseError(f'A full 40-character source commit is required, not {revision!r}')


def require_on_master(repo, revision, gh=gh):
    """The commit is master's tip or one of its ancestors."""
    status = json.loads(gh('api', f'repos/{repo}/compare/{revision}...{BRANCH}'))['status']
    if status not in ('identical', 'ahead'):
        raise ReleaseError(f'{revision} is not on {BRANCH} ({status})')


def tag_commit(repo, tag, gh=gh):
    """The commit the tag names, or None while it does not exist."""
    try:
        ref = json.loads(gh('api', f'repos/{repo}/git/ref/tags/{tag}'))
    except GhError as error:
        if error.not_found:
            return None
        raise
    target = ref['object']
    while target['type'] == 'tag':
        target = json.loads(gh('api', f'repos/{repo}/git/tags/{target["sha"]}'))['object']
    return target['sha']


def release_state(repo, tag, gh=gh):
    """The release named by the tag, drafts included, or None."""
    try:
        return json.loads(gh('release', 'view', tag, '-R', repo, '--json', 'isDraft,targetCommitish,assets,tagName'))
    except GhError as error:
        if error.not_found:
            return None
        raise


def plan_release(repo, revision, version, gh=gh):
    """'published' when vVERSION is out, 'resume' for this commit's draft,
    'create' when nothing exists yet. Anything naming another commit stops."""
    tag = f'v{version}'
    release = release_state(repo, tag, gh)
    if release and not release['isDraft']:
        return 'published'
    if release and release['targetCommitish'] != revision:
        raise ReleaseError(f'The draft {tag} targets {release["targetCommitish"]}, not {revision}; '
                           'delete that unpublished draft or release its own commit')
    tagged = tag_commit(repo, tag, gh)
    if tagged is not None and tagged != revision:
        raise ReleaseError(f'The tag {tag} already names {tagged}, not {revision}')
    return 'resume' if release else 'create'


def check_source(repo, revision, version, gh=gh, checkout=checkout_revision, source_version=current_version):
    """The checkout is the candidate, on master, and its changelog names VERSION."""
    require_revision(revision)
    head = checkout()
    if head != revision:
        raise ReleaseError(f'The checkout is {head}, not the candidate {revision}')
    found = source_version()
    if found != version:
        raise ReleaseError(f'The changelog at {revision} names {found}, not {version}')
    expected_assets(version)
    require_on_master(repo, revision, gh)


def due(repo, revision, gh=gh, checkout=checkout_revision, source_version=current_version):
    """The candidate's version and whether it still needs releasing."""
    version = source_version()
    check_source(repo, revision, version, gh, checkout, lambda: version)
    return version, plan_release(repo, revision, version, gh) != 'published'


def successful_run(repo, workflow, revision, gh=gh, wait=False):
    """The id of a successful run of the workflow for exactly this commit on
    master, from this repository. With wait, unfinished runs are watched."""
    def candidates():
        runs = json.loads(gh('api', '-X', 'GET', f'repos/{repo}/actions/workflows/{workflow}/runs',
                             '-f', f'head_sha={revision}', '-f', 'per_page=100'))['workflow_runs']
        return sorted((run for run in runs
                       if run['head_sha'] == revision and run['head_branch'] == BRANCH
                       and run['event'] in TRUSTED_EVENTS
                       and (run.get('head_repository') or {}).get('full_name') == repo),
                      key=lambda run: run['id'], reverse=True)

    runs = candidates()
    if wait:
        for run in runs:
            if run['status'] != 'completed':
                try:
                    gh('run', 'watch', run['id'], '-R', repo, '--exit-status', '--interval', '30')
                except GhError:
                    pass  # The run's conclusion is read again below.
        runs = candidates()
    for run in runs:
        if run['status'] == 'completed' and run['conclusion'] == 'success':
            return run['id']
    if not runs:
        raise ReleaseError(f'No {workflow} run of {revision} on {BRANCH}')
    latest = runs[0]
    raise ReleaseError(f'{workflow} has no successful run of {revision}: run {latest["id"]} is '
                       f'{latest["status"]} ({latest.get("conclusion")})')


def fetch_android(repo, run_id, version, directory, gh=gh):
    """Copies the signed APKs from the Android run's artifacts, and nothing else."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory.parent, prefix='.android-') as scratch:
        for artifact, names in ANDROID_ARTIFACTS.items():
            unpacked = Path(scratch) / artifact
            try:
                gh('run', 'download', run_id, '-R', repo, '-n', artifact, '-D', unpacked)
            except GhError as error:
                raise ReleaseError(f'Android run {run_id} has no {artifact} artifact (kept 7 days); '
                                   f'run Android again for this commit: {error}') from error
            files = sorted((path for path in unpacked.rglob('*') if path.is_file()), key=lambda path: path.name)
            found = [path.name for path in files]
            if found != sorted(names(version)):
                raise ReleaseError(f'{artifact} of run {run_id} holds {found}, not {sorted(names(version))}')
            for path in files:
                shutil.copyfile(path, directory / path.name)


def await_checks(repo, revision, version, directory, gh=gh):
    """Waits for both gating workflows of the commit, then takes Android's APKs."""
    require_revision(revision)
    android = successful_run(repo, ANDROID_WORKFLOW, revision, gh, wait=True)
    successful_run(repo, SITE_WORKFLOW, revision, gh, wait=True)
    fetch_android(repo, android, version, directory, gh)
    return android


def _check_appimage(path):
    with open(path, 'rb') as stream:
        head = stream.read(20)
    # ELF, type 2 AppImage magic, x86-64 machine.
    if (len(head) < 20 or head[:4] != b'\x7fELF' or head[8:11] != b'AI\x02'
            or struct.unpack_from('<H', head, 18)[0] != 0x3E):
        raise ReleaseError(f'{path.name} is not an x86-64 type 2 AppImage')


def _check_windows(path):
    """A Windows PE program. Installer stubs such as NSIS's are usually 32-bit
    x86 even when they install the x86-64 game, which its build job checks."""
    with open(path, 'rb') as stream:
        data = stream.read(4096)
    offset = struct.unpack_from('<I', data, 0x3C)[0] if len(data) >= 0x40 else len(data)
    if (data[:2] != b'MZ' or len(data) < offset + 6 or data[offset:offset + 4] != b'PE\0\0'
            or struct.unpack_from('<H', data, offset + 4)[0] not in (0x14C, 0x8664)):
        raise ReleaseError(f'{path.name} is not a Windows program')


def check_assets(directory, version, verify_apk=verify_apk):
    """Exactly this version's five non-empty downloads, each checked for what it is."""
    directory = Path(directory)
    names = expected_assets(version)
    present = sorted(path.name for path in directory.iterdir() if path.name != CHECKSUMS)
    missing = sorted(set(names) - set(present))
    extra = sorted(set(present) - set(names))
    if missing or extra:
        raise ReleaseError(f'Downloads for {version} differ: missing {missing}, unexpected {extra}')
    paths = [directory / name for name in names]
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ReleaseError(f'{path.name} is not a non-empty file')
        if path.suffix == '.apk':
            if path.read_bytes()[:4] != b'PK\x03\x04':
                raise ReleaseError(f'{path.name} is not an APK')
            verify_apk(path, 'gplay' if path.name.endswith('-gplay.apk') else 'direct')
        elif path.suffix == '.AppImage':
            _check_appimage(path)
        elif path.suffix == '.exe':
            _check_windows(path)
    return paths


def write_checksums(paths, directory):
    target = Path(directory) / CHECKSUMS
    target.write_text(''.join(f'{sha256(path)}  {path.name}\n' for path in paths))
    return target


def release_notes(changelog, version):
    section = re.search(r'^## \[' + re.escape(version) + r'\][^\n]*\n(.*?)(?=^## |\Z)', changelog, re.M | re.S)
    if not section or not section[1].strip():
        raise ReleaseError(f'CHANGELOG.md has no notes for {version}')
    return section[1].strip() + '\n'


def _check_uploaded(repo, tag, files, gh=gh):
    release = release_state(repo, tag, gh)
    found = {asset['name']: asset for asset in (release or {}).get('assets', [])}
    expected = {path.name: (path.stat().st_size, f'sha256:{sha256(path)}') for path in files}
    # GitHub reports each asset's SHA-256 digest; older answers lack it.
    if sorted(found) != sorted(expected) or any(
            found[name].get('size') != size or found[name].get('state') != 'uploaded'
            or found[name].get('digest', digest) != digest
            for name, (size, digest) in expected.items()):
        raise ReleaseError(f'The {tag} draft holds {sorted(found)}, not the uploaded {sorted(expected)}')


def publish_release(revision, version, asset_directory, *, repo, gh=gh, verify_apk=verify_apk,
                    checkout=checkout_revision, source_version=current_version, changelog=None):
    """Publishes vVERSION at REVISION with exactly the checked downloads in
    ASSET_DIRECTORY and their SHA256SUMS. Returns 'published' when the
    release already was out (left unchanged) and 'released' otherwise."""
    tag = f'v{version}'
    check_source(repo, revision, version, gh, checkout, source_version)
    # Both gates must already have passed; `checks` waited for them.
    successful_run(repo, ANDROID_WORKFLOW, revision, gh)
    successful_run(repo, SITE_WORKFLOW, revision, gh)
    if plan_release(repo, revision, version, gh) == 'published':
        print(f'Choano {version} is already published; its downloads stay as they are.')
        return 'published'
    directory = Path(asset_directory)
    paths = check_assets(directory, version, verify_apk)
    files = [*paths, write_checksums(paths, directory)]
    notes = directory.parent / f'choano-{version}-notes.md'
    notes.write_text(release_notes(changelog if changelog is not None else (ROOT / 'CHANGELOG.md').read_text(), version))
    # The plan is read again just before writing, so nothing published or
    # retargeted in between is touched.
    state = plan_release(repo, revision, version, gh)
    if state == 'published':
        return 'published'
    if state == 'create':
        # The tag appears only when this draft is published, at REVISION.
        gh('release', 'create', tag, '-R', repo, '--draft', '--target', revision,
           '--title', f'Choano {version}', '--notes-file', notes)
    else:
        gh('release', 'edit', tag, '-R', repo, '--notes-file', notes)
        names = {path.name for path in files}
        for asset in release_state(repo, tag, gh)['assets']:
            if asset['name'] not in names:
                gh('release', 'delete-asset', tag, '-R', repo, asset['name'], '--yes')
    gh('release', 'upload', tag, '-R', repo, '--clobber', *files)
    _check_uploaded(repo, tag, files, gh)
    if plan_release(repo, revision, version, gh) != 'resume':
        raise ReleaseError(f'The {tag} draft changed while its downloads uploaded')
    gh('release', 'edit', tag, '-R', repo, '--draft=false', '--latest')
    release = release_state(repo, tag, gh)
    tagged = tag_commit(repo, tag, gh)
    if not release or release['isDraft'] or tagged != revision:
        raise ReleaseError(f'{tag} did not publish at {revision} (tag names {tagged})')
    print(f'Published Choano {version} at {revision} with {", ".join(path.name for path in files)}.')
    return 'released'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    actions = parser.add_subparsers(dest='action', required=True)
    for name in ('due', 'checks', 'publish'):
        action = actions.add_parser(name)
        action.add_argument('--revision', required=True)
        if name == 'publish':
            action.add_argument('--version', required=True)
        if name != 'due':
            action.add_argument('directory', type=Path)
    args = parser.parse_args()
    repo = os.environ.get('GH_REPO') or os.environ.get('GITHUB_REPOSITORY')
    if not repo:
        parser.exit(1, 'publish release: set GH_REPO to owner/name\n')
    try:
        if args.action == 'due':
            version, needed = due(repo, args.revision)
            lines = f'version={version}\nrelease_due={str(needed).lower()}\n'
            print(lines, end='')
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                    output.write(lines)
        elif args.action == 'checks':
            run = await_checks(repo, args.revision, current_version(), args.directory)
            print(f'Android run {run} and the Choano run of {args.revision} succeeded; APKs in {args.directory}')
        else:
            publish_release(args.revision, args.version, args.directory, repo=repo)
    except (OSError, ReleaseError, GhError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'publish release: {error}\n')


if __name__ == '__main__':
    main()
