#!/usr/bin/env python3
"""Build Choano from its locked shared packages; Arcade only consumes it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
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


def renderer_links(descriptor):
    artifact = descriptor.parent.resolve()
    rows = dict(line.split('\t', 1) for line in descriptor.read_text().splitlines())
    if any(rows.get(key) != value for key, value in
           {'schema': '1', 'artifact': 'renderer-raylib', 'platform': 'linux-x86_64-gnu'}.items()):
        raise RuntimeError('Unexpected renderer artifact descriptor')
    def verified(relative):
        path = (artifact / relative).resolve()
        if not path.is_relative_to(artifact):
            raise RuntimeError('Renderer output escapes artifact')
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        if rows.get(relative) != digest:
            raise RuntimeError('Renderer output hash mismatch: ' + relative)
        return path
    metadata = json.loads(verified('renderer.json').read_text())
    if metadata['schema'] != 1 or metadata['platform'] != 'linux-x86_64-gnu':
        raise RuntimeError('Unexpected MediaAudio renderer artifact')
    return [str(verified(path)) for path in metadata['archives']] + metadata['link_flags']


def native():
    # The desktop renderer and MediaAudio provider have separate link inputs.
    artifact = Path(subprocess.check_output([ZIRAN, 'pkg', 'artifact',
        'kryon:renderer-raylib', '--platform', 'linux-x86_64-gnu', *LOCKED], text=True).strip())
    # Preserve dependency-owned archive order before its platform libraries.
    links = renderer_links(artifact)
    links.extend(shlex.split(os.environ.get('LDLIBS', '')))
    run(ZIRAN, 'build', '--project', *LOCKED, 'native',
        env={**os.environ, 'LDLIBS': shlex.join(links)})


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
    parser.add_argument('target', choices=['native', 'bundle', 'profile', 'web'])
    args = parser.parse_args()
    (ROOT / 'build').mkdir(exist_ok=True)
    {'native': native, 'bundle': bundle, 'profile': profile, 'web': web}[args.target]()
