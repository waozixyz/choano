#!/usr/bin/env python3
"""Build Choano from its locked shared packages; Arcade only consumes it."""
import argparse
import importlib.util
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


def prepare_theme():
    run(sys.executable, ROOT / "scripts/theme.py")


def package(name):
    return Path(subprocess.check_output([ZIRAN, 'pkg', 'path', name, *LOCKED], text=True).strip())


def shared_script(owner, name):
    spec = importlib.util.spec_from_file_location(name, package(owner) / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def renderer_links():
    artifacts = shared_script('ziran', 'ziran_artifacts')
    renderers = shared_script('kryon', 'renderer_artifact')
    artifact = artifacts.request('kryon:renderer-raylib', 'linux-x86_64-gnu', project=ROOT, ziran=ZIRAN)
    return renderers.renderer_link(renderers.renderer_metadata(artifact), preloads=False)


def artifact(selection, platform, env=None):
    return shared_script('ziran', 'ziran_artifacts').request(selection, platform, project=ROOT, ziran=ZIRAN, env=env)


# The system libraries Entity's native-profile recipe adds for its Profile UI
# (tools/artifacts.zi SystemLinkText). That recipe lists 65 inputs, past the
# 64 the locked Ziran (before 3e69203b) accepts, so only its native-crypto
# prerequisite is requested; switch to native-profile with a newer toolchain.
PROFILE_SYSTEM = {
    'linux-x86_64-gnu': (['sdl2', 'cairo', 'freetype2', 'fontconfig', 'pangocairo', 'gtk+-3.0'], ['-lX11']),
    'windows-x86_64-mingw': ([], ['-flto=1', '-luser32', '-lshell32', '-lole32', '-lcomdlg32']),
}


def account_links(platform, env=None):
    """The Entity account provider's foreign libraries for PLATFORM, in its own
    order: its Ziran modules are ordinary imports, so no Entity archive."""
    flags = artifact('entity:native-crypto', platform, env).link_flags(env=env)
    packages, libraries = PROFILE_SYSTEM[platform]
    if packages:
        flags.extend(shlex.split(subprocess.check_output(['pkg-config', '--libs', *packages], text=True, env=env)))
    return [*flags, *libraries]


# The Profile bundle native editions read from assets/; never tracked, and
# kept out of the portable bundle and the web site, which do not open it.
PROFILE_ASSET = ROOT / 'assets/entity.zx'


def profile_asset():
    profile()
    partial = PROFILE_ASSET.with_name('entity.zx.new')
    shutil.copyfile(ROOT / 'build/entity.zx', partial)
    partial.replace(PROFILE_ASSET)
    return PROFILE_ASSET


def without_profile(folder, names):
    return ['entity.zx', 'entity.zx.new'] if Path(folder).resolve() == PROFILE_ASSET.parent else []


def link_or_copy(source, target):
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


NATIVE = ROOT / 'build/Choano-native'
NATIVE_WORK = ROOT / 'build/native-accounts'


def native():
    """build/Choano-native: src/desktop.zi with the Entity account provider.
    Kryon's native profile takes no defines, so this is its desktop route
    (POSIX threads, the desktop backend's libraries) with CHOANO_ACCOUNTS."""
    profile_asset()
    # Preserve dependency-owned archive order before its platform libraries.
    links = renderer_links()
    links.extend(account_links('linux-x86_64-gnu'))
    for query in (['sdl2', 'cairo', 'freetype2', 'pangocairo', 'fontconfig', 'gio-2.0'], ['libcurl']):
        found = subprocess.run(['pkg-config', '--libs', *query], text=True, capture_output=True)
        links.extend(shlex.split(found.stdout) if found.returncode == 0 else ['-l:libcurl.so.4'])
    links.extend(['-pthread', *shlex.split(os.environ.get('LDLIBS', ''))])
    env = {**os.environ, 'LDLIBS': shlex.join(links),
           'CFLAGS': os.environ.get('CFLAGS', '-O2') + ' -ffunction-sections -fdata-sections -Wno-main -pthread',
           'LDFLAGS': (os.environ.get('LDFLAGS', '') + ' -Wl,--gc-sections').strip()}
    run(ZIRAN, 'build', '--project', *LOCKED, '--target=c', '--exe', '--define', 'POSIX_THREADS',
        '--define', 'CHOANO_ACCOUNTS', '--entry', 'desktop:main', '-o', NATIVE_WORK, 'src/desktop.zi', env=env)
    partial = NATIVE.with_name(NATIVE.name + '.new')
    shutil.copyfile(NATIVE_WORK / 'desktop', partial)
    partial.chmod(0o755)
    partial.replace(NATIVE)
    # The window and menu name Kryon's desktop host reads beside the program.
    NATIVE.with_name(NATIVE.name + '.title').write_text('Choano\n')


def bundle():
    # The art without the native Profile bundle: hosts own the portable Profile.
    staged = ROOT / 'build/portable-assets'
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(ROOT / 'assets', staged, ignore=without_profile, copy_function=link_or_copy)
    run(ZIRAN, 'bundle', '--project', *LOCKED, '--define', 'CHOANO_PORTABLE',
        '--define', 'KRYON_HOSTED_UI', '--entry', 'portable:Main',
        '--asset-dir', 'assets=' + str(staged), '-o', 'build/choano.zx', 'src/portable.zi')


def profile():
    entity, kryon, ziran, qr = map(package, ('entity', 'kryon', 'ziran', 'qrcode'))
    # This legacy Profile entry uses explicit module paths. Invoke the locked
    # compiler itself so the global launcher cannot emit another ZX version.
    run(ziran / 'build/bin/ziran', 'bundle', '--root', entity, '--module-path', entity / 'src',
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
    shutil.copytree(ROOT / 'assets', output / 'assets', ignore=without_profile)
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
    parser.add_argument('target', choices=['native', 'bundle', 'profile', 'profile-asset', 'web'])
    args = parser.parse_args()
    prepare_theme()
    (ROOT / 'build').mkdir(exist_ok=True)
    {'native': native, 'bundle': bundle, 'profile': profile, 'profile-asset': profile_asset,
     'web': web}[args.target]()
