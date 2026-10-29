#!/usr/bin/env python3
"""Build Choano from its locked shared packages; Arcade only consumes it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
ZIRAN = os.environ.get('ZIRAN', 'ziran')
LOCKED = [] if (ROOT / 'ziran.local.toml').exists() else ['--locked']


def run(*args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def package(name):
    return Path(subprocess.check_output([ZIRAN, 'pkg', 'path', name, *LOCKED], text=True).strip())


def bundle():
    run(ZIRAN, 'bundle', '--project', *LOCKED, '--define', 'CHOANO_PORTABLE',
        '--define', 'KRYON_HOSTED_UI', '--entry', 'portable:Main',
        '--asset-dir', 'assets=assets', '-o', 'build/choano.zx', 'src/portable.zi')


def profile():
    entity, kryon, ziran, qr = map(package, ('entity', 'kryon', 'ziran', 'qrcode'))
    run(ZIRAN, 'bundle', '--root', entity, '--module-path', entity / 'src',
        '--module-path', kryon / 'src/ui', '--module-path', 'kryon=' + str(kryon / 'src/ui'),
        '--module-path', 'kryon=' + str(kryon / 'src/backend'),
        '--module-path', 'qrcode=' + str(qr / 'src'), '--module-path', ziran / 'std',
        '--define', 'KRYON_HOSTED_UI', '--asset-dir', 'assets=' + str(entity / 'assets'),
        '--entry', 'entity:Main', '-o', ROOT / 'build/entity.zx', entity / 'src/entity.zi')


def web():
    profile()
    output = ROOT / 'build/web'
    output.mkdir(parents=True, exist_ok=True)
    run(sys.executable, package('entity') / 'scripts/build-web.py',
        '--profile', ROOT / 'build/entity.zx', '--output', output / 'game.html',
        '--source', 'src/web/runtime.zi', '--entry', 'runtime:main',
        '--linked', ROOT / 'build/entity.zx')
    # The browser renderer and Web Audio load the same replacement PNG/WAV files.
    if (output / 'assets').exists():
        shutil.rmtree(output / 'assets')
    shutil.copytree(ROOT / 'assets', output / 'assets')
    for item in (ROOT / 'src/web').iterdir():
        if item.suffix in {'.html', '.js', '.css'}:
            shutil.copyfile(item, output / item.name)
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], text=True, capture_output=True).stdout.strip() or 'uncommitted'
    page = output / 'index.html'
    asset_revision = json.loads((ROOT / 'assets/manifest.json').read_text())['sha256']
    page.write_text(page.read_text().replace('__CHOANO_ASSET_REVISION__', asset_revision)
                    .replace('__CHOANO_BUILD_REVISION__', revision))
    (output / 'build.json').write_text(json.dumps({'source_revision': revision,
        'game': 'choano', 'assets_sha256': json.loads((ROOT / 'assets/manifest.json').read_text())['sha256']}, indent=2) + '\n')
    (output / 'game.html').unlink()
    (output / '_headers').write_text('/game.*\n  Cache-Control: no-cache\n/assets/manifest.json\n  Cache-Control: no-cache\n/build.json\n  Cache-Control: no-cache\n/index.html\n  Cache-Control: no-cache\n')
    if any(p.stat().st_size > 25 * 1024 * 1024 for p in output.rglob('*') if p.is_file()):
        raise SystemExit('A site file exceeds the Cloudflare Pages limit')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', choices=['bundle', 'profile', 'web'])
    args = parser.parse_args()
    (ROOT / 'build').mkdir(exist_ok=True)
    {'bundle': bundle, 'profile': profile, 'web': web}[args.target]()
