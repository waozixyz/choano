#!/usr/bin/env python3
"""Build, sign and verify Choano's Android APKs on Kryon's Android host.

    python3 scripts/android.py build [--edition direct|gplay]
    python3 scripts/android.py sign APK --output SIGNED.apk [--edition gplay]
    python3 scripts/android.py verify APK [--edition gplay]

The normal APK, also the F-Droid download, holds no Google library: Choano
has no self-update, so one build serves both. Only the Google Play edition
applies Kryon's android-gplay.gradle, which adds Play Billing.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'xyz.waozi.choano'
ABIS = 'arm64-v8a,armeabi-v7a'
# The Choano release key (backup/android-signing, GitHub secret
# CHOANO_ANDROID_KEYSTORE).
CERTIFICATE_SHA256 = '181c2124b549b190d4bfebddf0335eb276ba71877957decafcb0f6a408f91694'
ZIRAN = os.environ.get('ZIRAN', 'ziran')
LOCKED = [] if (ROOT / 'ziran.local.toml').exists() else ['--locked']
OUT = ROOT / 'build/android'


def run(*args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def package(name):
    return Path(subprocess.check_output([ZIRAN, 'pkg', 'path', name, *LOCKED], text=True, cwd=ROOT).strip())


def sdk():
    return Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or Path.home() / 'Android/Sdk')


def version():
    """The newest released changelog version and its versionCode; 0.0.0
    before the first release."""
    found = re.search(r'^## \[(\d+)\.(\d+)\.(\d+)\]', (ROOT / 'CHANGELOG.md').read_text(), re.M)
    if not found:
        return '0.0.0', 1
    major, minor, patch = map(int, found.groups())
    return f'{major}.{minor}.{patch}', max(1, major * 10000 + minor * 100 + patch)


def launcher_icons(res):
    """The launcher icon at each density: the player amoeba in Choano's water."""
    from PIL import Image
    sheet = Image.open(ROOT / 'assets/choano/organisms-hd.png').convert('RGBA')
    cell = sheet.crop((0, 0, sheet.width // 4, sheet.height // 4))
    player = cell.crop(cell.getchannel('A').point(lambda a: 255 if a > 32 else 0).getbbox())
    water = Image.open(ROOT / 'assets/choano/icon.png').convert('RGB').getpixel((5, 40))
    for density, size in (('mdpi', 48), ('hdpi', 72), ('xhdpi', 96), ('xxhdpi', 144), ('xxxhdpi', 192)):
        icon = Image.new('RGBA', (size, size), water + (255,))
        scale = 0.72 * size / max(player.size)
        sprite = player.resize((round(player.width * scale), round(player.height * scale)), Image.LANCZOS)
        icon.alpha_composite(sprite, ((size - sprite.width) // 2, (size - sprite.height) // 2))
        folder = res / f'mipmap-{density}'
        folder.mkdir(parents=True, exist_ok=True)
        icon.convert('RGB').save(folder / 'ic_launcher.png', optimize=True)


def scaffold(kryon):
    """droid/ from the locked Kryon, with Choano's Gradle build and manifest.
    Kryon's scaffold keeps existing files, so stale ones go first; Gradle's
    caches stay."""
    droid = ROOT / 'droid'
    if droid.exists():
        for path in droid.iterdir():
            if path.name in ('.gradle', 'build'):
                continue
            if path.name == 'app':
                for inner in path.iterdir():
                    if inner.name != 'build':
                        shutil.rmtree(inner) if inner.is_dir() else inner.unlink()
                continue
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    run(sys.executable, kryon / 'scripts/android_scaffold.py', '--root', ROOT, '--name', 'Choano',
        '--package', PACKAGE, '--activity', 'MainActivity', '--kryon', kryon)
    packaging = ROOT / 'packaging/android'
    shutil.copyfile(packaging / 'build.gradle', droid / 'app/build.gradle')
    shutil.copyfile(packaging / 'AndroidManifest.xml', droid / 'app/src/main/AndroidManifest.xml')
    (droid / 'gradle.properties').write_text(
        'org.gradle.daemon=false\norg.gradle.parallel=false\norg.gradle.workers.max=1\n'
        'org.gradle.jvmargs=-Xmx1536m -Dfile.encoding=UTF-8\n')


def build(edition, abis=ABIS):
    run(ZIRAN, 'fetch', *LOCKED, cwd=ROOT)
    kryon, compiler, raylib = package('kryon'), package('ziran'), package('raylib')
    if not all((compiler / 'build/bin' / name).is_file() for name in ('ziran', 'zi2c')):
        run('make', '-s', '-j2', '-C', compiler, 'build/bin/ziran', 'build/bin/zi2c', 'build/bin/zi2zir')
    android = sdk()
    aapt2 = android / 'build-tools/36.0.0/aapt2'
    if not aapt2.is_file() or not (android / 'platforms/android-36').is_dir():
        raise SystemExit(f'Install build-tools 36.0.0, platforms;android-36, cmake 3.22.1 and the NDK in {android}')
    scaffold(kryon)
    # The game reads its art and chimes as assets/choano/... from the APK.
    staged = OUT / 'assets'
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(ROOT / 'assets', staged / 'assets')
    res = OUT / 'res'
    if res.exists():
        shutil.rmtree(res)
    launcher_icons(res)
    name, code = version()
    command = ['sh', ROOT / 'droid/gradlew', '-p', ROOT / 'droid', '--no-daemon', '--max-workers=1',
               '-Pkryon.dir=' + str(kryon), '-Pziran.dir=' + str(compiler), '-Praylib.dir=' + str(raylib / 'src'),
               '-Papp.abis=' + abis, '-Papp.edition=' + edition, '-Papp.versionName=' + name,
               '-Papp.versionCode=' + str(code), '-Pandroid.aapt2FromMavenOverride=' + str(aapt2)]
    # Kryon's Play Billing needs AndroidX; only the Google Play edition has it.
    if edition == 'gplay':
        command.append('-Pandroid.useAndroidX=true')
    env = dict(os.environ, ANDROID_HOME=str(android), ANDROID_SDK_ROOT=str(android), CMAKE_BUILD_PARALLEL_LEVEL='1')
    for name_ in ('MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES', 'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY'):
        env.pop(name_, None)
    run(*command, 'assembleRelease', cwd=ROOT, env=env)
    output = OUT / ('choano-gplay-unsigned.apk' if edition == 'gplay' else 'choano-unsigned.apk')
    shutil.copyfile(ROOT / 'droid/app/build/outputs/apk/release/app-release-unsigned.apk', output)
    print(f'Choano {name} ({code}) for Android, {edition} edition: {output}')


def build_tools():
    folders = sorted((sdk() / 'build-tools').glob('*'), key=lambda p: tuple(int(n) for n in re.findall(r'\d+', p.name)))
    return next(p for p in reversed(folders) if all((p / name).is_file() for name in ('aapt', 'apksigner', 'zipalign')))


def verify(apk, edition, tools):
    name, _ = version()
    badging = subprocess.check_output([str(tools / 'aapt'), 'dump', 'badging', str(apk)], text=True)
    found = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging, re.M)
    assert found and found[1] == PACKAGE and found[3] == name, 'APK identity or version differs'
    assert 'application-debuggable' not in badging, 'A debug build cannot be published'
    google_play = edition == 'gplay'
    assert ("'com.android.vending.BILLING'" in badging) == google_play, 'Only the Google Play edition may ask for Play Billing'
    signature = subprocess.check_output([str(tools / 'apksigner'), 'verify', '--verbose', '--print-certs', str(apk)], text=True)
    signers = re.findall(r'^(?:Signer #\d+|V[\d.]+ Signer:) certificate SHA-256 digest: ([0-9a-f]+)$', signature, re.M)
    assert 'Number of signers: 1' in signature and set(signers) == {CERTIFICATE_SHA256}, \
        'APK signer is not the Choano release key'
    run(tools / 'zipalign', '-c', '-P', '16', '4', apk, capture_output=True)
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        abis = sorted(p.split('/')[1] for p in names if re.fullmatch(r'lib/[^/]+/libmain\.so', p))
        assert abis == sorted(ABIS.split(',')), 'Both supported ARM architectures must be present'
        assert 'assets/assets/choano/organisms-hd.png' in names, "The game's artwork is missing"
        assert 'assets/assets/choano/audio/eat.wav' in names, "The game's chimes are missing"
        dex = b''.join(archive.read(n) for n in names if re.fullmatch(r'classes\d*\.dex', n))
        for marker in (b'Lorg/kryonlabs/play/PlayBilling;', b'Lcom/android/billingclient/'):
            assert (marker in dex) == google_play, 'Only the Google Play edition may include Play Billing'
    print(f'{apk.name}: Choano {name} ({found[2]}), {edition} edition, {", ".join(abis)}, '
          f'signed by {CERTIFICATE_SHA256[:12]}')


def sign(apk, output, edition, keystore, password, alias):
    tools = build_tools()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    aligned = output.with_name(output.stem + '.aligned.apk')
    signed = output.with_name(output.stem + '.new.apk')
    try:
        run(tools / 'zipalign', '-P', '16', '-f', '4', apk, aligned)
        run(tools / 'apksigner', 'sign', '--alignment-preserved', '--ks', keystore.resolve(strict=True),
            '--ks-key-alias', alias, '--ks-pass', 'file:' + str(password.resolve(strict=True)),
            '--out', signed, aligned)
        verify(signed, edition, tools)
        signed.replace(output)
    finally:
        aligned.unlink(missing_ok=True)
        signed.unlink(missing_ok=True)
        output.with_name(signed.name + '.idsig').unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=('build', 'sign', 'verify', 'version'))
    parser.add_argument('apk', type=Path, nargs='?')
    parser.add_argument('--edition', choices=('direct', 'gplay'), default='direct')
    parser.add_argument('--output', type=Path)
    # x86_64 only for a local emulator check; releases carry both ARM ABIs.
    parser.add_argument('--abis', default=ABIS)
    parser.add_argument('--keystore', type=Path, default=ROOT / 'backup/android-signing/choano-release.p12')
    parser.add_argument('--password-file', type=Path, default=ROOT / 'backup/android-signing/password')
    parser.add_argument('--alias', default='choano')
    args = parser.parse_args()
    if args.action == 'version':
        print(version()[0])
    elif args.action == 'build':
        build(args.edition, args.abis)
    elif args.action == 'sign':
        if not args.apk or not args.output:
            parser.error('sign needs an APK and --output')
        sign(args.apk.resolve(strict=True), args.output, args.edition, args.keystore, args.password_file, args.alias)
    else:
        if not args.apk:
            parser.error('verify needs an APK')
        verify(args.apk.resolve(strict=True), args.edition, build_tools())


if __name__ == '__main__':
    main()
