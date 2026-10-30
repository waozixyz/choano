"""Canonical release metadata shared by packaging and release workflows."""
import argparse
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / 'CHANGELOG.md'
VERSION_FILE = ROOT / 'VERSION'
ANDROID_MAX_VERSION_CODE = 2_100_000_000
_RELEASE_HEADING = re.compile(r'^## \[(\d+)\.(\d+)\.(\d+)\](?:[ \t]+-[^\n]*)?[ \t]*$', re.MULTILINE)
_FIRST_NUMERIC_HEADING = re.compile(r'^## \[\d[^\]\n]*\]', re.MULTILINE)
_CANONICAL_VERSION = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')


class ReleaseError(ValueError):
    pass


def _version_parts(version):
    if not _CANONICAL_VERSION.fullmatch(version):
        raise ReleaseError(f'Invalid release version: {version}')
    major, minor, patch = map(int, version.split('.'))
    if major == minor == patch == 0:
        raise ReleaseError('The release version cannot be 0.0.0')
    if major > 209_999 or minor > 99 or patch > 99:
        raise ReleaseError(f'Release version does not fit Android versionCode: {version}')
    return major, minor, patch


def release_version(changelog, canonical_version=None):
    numeric = _FIRST_NUMERIC_HEADING.search(changelog)
    found = _RELEASE_HEADING.match(numeric.group(0)) if numeric else None
    if not found:
        raise ReleaseError('CHANGELOG.md has no numbered release heading')
    version = '.'.join(found.groups())
    _version_parts(version)
    if canonical_version is not None and canonical_version != version:
        raise ReleaseError(f'VERSION is {canonical_version}, but CHANGELOG.md is {version}')
    return version


def android_code(version):
    major, minor, patch = _version_parts(version)
    code = major * 10_000 + minor * 100 + patch
    if not 1 <= code <= ANDROID_MAX_VERSION_CODE:
        raise ReleaseError(f'Android versionCode out of range for {version}: {code}')
    return code


def expected_assets(version):
    _version_parts(version)
    return (
        f'choano-v{version}.apk',
        f'choano-{version}-fdroid.apk',
        f'choano-v{version}-gplay.apk',
        f'choano-v{version}-linux-x86_64.AppImage',
        f'choano-v{version}-windows-x86_64-setup.exe',
    )


def current_version():
    changelog = CHANGELOG.read_text()
    changelog_version = release_version(changelog)
    if VERSION_FILE.exists():
        release_version(changelog, VERSION_FILE.read_text().strip())
    return changelog_version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('version', 'code', 'assets'))
    args = parser.parse_args()
    try:
        version = current_version()
        if args.action == 'version':
            print(version)
        elif args.action == 'code':
            print(android_code(version))
        else:
            print(*expected_assets(version), sep='\n')
    except (OSError, ReleaseError) as error:
        parser.exit(1, f'release: {error}\n')


if __name__ == '__main__':
    main()
