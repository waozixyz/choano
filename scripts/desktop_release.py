#!/usr/bin/env python3
"""Desktop release packages built from Choano's native desktop edition.

`appimage` packs the native SDL/Cairo/Pango game, its bundled libraries and
every asset into build/Choano.AppImage. `windows` cross-compiles the same
Frame on Kryon's raylib host with MinGW and packs it, its font and every
asset into the per-user NSIS installer build/Choano-setup.exe. The release
workflow copies each to its public versioned name.
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release import ReleaseError, current_version, expected_assets

ROOT = Path(__file__).resolve().parents[1]
ZIRAN = os.environ.get('ZIRAN', 'ziran')
LOCKED = [] if (ROOT / 'ziran.local.toml').exists() else ['--locked']
APP_ID = 'xyz.waozi.choano'
EXECUTABLE = 'Choano'
NATIVE = ROOT / 'build/Choano-native'
APPIMAGE = ROOT / 'build/Choano.AppImage'
PACKAGING = ROOT / 'packaging/linux'
BUILD = ROOT / 'build/appimage'
TOOLS_DIR = ROOT / 'work/tools/appimage'
# Pinned official linuxdeploy releases; the AppImage plugin carries appimagetool.
TOOLS = {
    'linuxdeploy-x86_64.AppImage': (
        'https://github.com/linuxdeploy/linuxdeploy/releases/download/'
        '1-alpha-20251107-1/linuxdeploy-x86_64.AppImage',
        'c20cd71e3a4e3b80c3483cef793cda3f4e990aca14014d23c544ca3ce1270b4d'),
    'linuxdeploy-plugin-appimage-x86_64.AppImage': (
        'https://github.com/linuxdeploy/linuxdeploy-plugin-appimage/releases/download/'
        '1-alpha-20250213-1/linuxdeploy-plugin-appimage-x86_64.AppImage',
        '992d502a248e14ab185448ddf6f6e7d25558cb84d4623c354c3af350c25fccb3'),
}
# linuxdeploy accepts only standard square icon sizes.
ICON_SIZE = 160
# Kryon opens GdkPixbuf at run time to decode the art, so linuxdeploy only
# bundles it when named. The image carries the build host's copy, its PNG and
# JPEG loaders built in, and an empty module list in place of the host's.
PIXBUF = 'libgdk_pixbuf-2.0.so.0'
PIXBUF_MODULES = 'usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache'
# Loads the AppDir's GdkPixbuf as the game does and decodes each named image;
# prints where every library it loaded came from.
DECODE_PROBE = '''
import ctypes, sys
pixbuf = ctypes.CDLL(sys.argv[1], mode=ctypes.RTLD_GLOBAL)
pixbuf.gdk_pixbuf_new_from_file.restype = ctypes.c_void_p
pixbuf.gdk_pixbuf_new_from_file.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
for name in sys.argv[2:]:
    if not pixbuf.gdk_pixbuf_new_from_file(name.encode(), None):
        sys.exit('cannot decode ' + name)
print('\\n'.join(sorted({line.split()[-1] for line in open('/proc/self/maps') if '.so' in line})))
'''
# Kryon's desktop renderer decodes AVIF art with its self-contained
# libkryonavif.so, found in the AppDir's usr/lib. Opens the AppDir's copy and
# decodes each named image; prints where every library it loaded came from.
AVIF = 'libkryonavif.so'
AVIF_PROBE = '''
import ctypes, sys
avif = ctypes.CDLL(sys.argv[1])
avif.avifDecoderCreate.restype = ctypes.c_void_p
avif.avifDecoderSetIOMemory.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
avif.avifDecoderParse.argtypes = [ctypes.c_void_p]
avif.avifDecoderNextImage.argtypes = [ctypes.c_void_p]
avif.avifDecoderDestroy.argtypes = [ctypes.c_void_p]
for name in sys.argv[2:]:
    data = open(name, 'rb').read()
    decoder = avif.avifDecoderCreate()
    if (not decoder or avif.avifDecoderSetIOMemory(decoder, data, len(data))
            or avif.avifDecoderParse(decoder) or avif.avifDecoderNextImage(decoder)):
        sys.exit('cannot decode ' + name)
    avif.avifDecoderDestroy(decoder)
print('\\n'.join(sorted({line.split()[-1] for line in open('/proc/self/maps') if '.so' in line})))
'''
SETUP = ROOT / 'build/Choano-setup.exe'
WINDOWS = ROOT / 'build/windows'
WINDOWS_PACKAGING = ROOT / 'packaging/windows'
# The Linux toolchain's MinGW-w64 cross compiler, and NSIS.
MINGW = os.environ.get('MINGW_PREFIX', 'x86_64-w64-mingw32-')
WINDOWS_DEFINES = ['--define', '_WIN32', '--define', 'PLATFORM_DESKTOP', '--define', '__x86_64__',
                   '--define', 'CHOANO_RAYLIB', '--define', 'CHOANO_ACCOUNTS']
# libssp: the audio package's MinGW libopus keeps its stack protector.
WINDOWS_LIBRARIES = ['-lssp', '-lopengl32', '-lgdi32', '-lwinmm', '-luser32', '-lshell32', '-lole32', '-luuid', '-lm']
# raylib as Shovey and Breeze ship it on Windows: RGFW and OpenGL 1.1. Kryon's
# static libavif decoder supplies AVIF image support.
RAYLIB_FLAGS = '-O2 -ffunction-sections -fdata-sections -DSUPPORT_FILEFORMAT_JPG=1 -DSUPPORT_FILEFORMAT_TTF=1'


def run(*args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch_tool(name):
    """The pinned tool, downloaded once into ignored work/tools and verified."""
    url, expected = TOOLS[name]
    path = TOOLS_DIR / name
    if not path.exists() or sha256(path) != expected:
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix('.part')
        with urllib.request.urlopen(url) as response, open(partial, 'wb') as out:
            shutil.copyfileobj(response, out)
        if sha256(partial) != expected:
            partial.unlink()
            raise SystemExit(f'desktop release: {name} from {url} does not match its pinned checksum')
        partial.replace(path)
    path.chmod(0o755)
    return path


def square_icon(size=ICON_SIZE):
    """Choano's icon art centred on a square canvas, its edge rows extended."""
    from PIL import Image
    art = Image.open(ROOT / 'assets/choano/icon.png').convert('RGBA')
    scale = size / max(art.size)
    art = art.resize((round(art.width * scale), round(art.height * scale)), Image.NEAREST)
    icon = Image.new('RGBA', (size, size))
    top = (size - art.height) // 2
    left = (size - art.width) // 2
    icon.paste(art.crop((0, 0, art.width, 1)).resize((art.width, top)), (left, 0))
    bottom = size - top - art.height
    icon.paste(art.crop((0, art.height - 1, art.width, art.height)).resize((art.width, bottom)),
               (left, top + art.height))
    icon.paste(art, (left, top))
    return icon


def desktop_icon(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    square_icon().save(target, optimize=True)


def stage_appdir(appdir, binary, version):
    """Lays out APPDIR before linuxdeploy adds libraries: launcher, game,
    read-only assets and desktop metadata carrying VERSION."""
    if appdir.exists():
        shutil.rmtree(appdir)
    bin_dir = appdir / 'usr/bin'
    bin_dir.mkdir(parents=True)
    shutil.copy2(binary, bin_dir / EXECUTABLE)
    shutil.copytree(ROOT / 'assets', appdir / 'usr/share/choano/assets')
    applications = appdir / 'usr/share/applications'
    applications.mkdir(parents=True)
    desktop = (PACKAGING / f'{APP_ID}.desktop').read_text()
    (applications / f'{APP_ID}.desktop').write_text(desktop + f'X-AppImage-Version={version}\n')
    metainfo = appdir / 'usr/share/metainfo'
    metainfo.mkdir(parents=True)
    shutil.copy2(PACKAGING / f'{APP_ID}.appdata.xml', metainfo)
    desktop_icon(appdir / f'usr/share/icons/hicolor/{ICON_SIZE}x{ICON_SIZE}/apps/{APP_ID}.png')
    modules = appdir / PIXBUF_MODULES
    modules.parent.mkdir(parents=True)
    modules.write_text('# No loader modules: PNG and JPEG are built into the bundled GdkPixbuf.\n')
    return appdir


def system_library(soname):
    """The build host's 64-bit copy of a shared library, from the linker cache."""
    ldconfig = shutil.which('ldconfig') or '/sbin/ldconfig'
    listing = subprocess.run([ldconfig, '-p'], text=True, capture_output=True, check=True).stdout
    for line in listing.splitlines():
        name, _, path = line.strip().partition(' => ')
        if name.split(' ', 1)[0] == soname and 'x86-64' in name:
            return Path(path)
    raise SystemExit(f'desktop release: the build host has no {soname}; install libgdk-pixbuf-2.0-0')


def probe_decoder(appdir, library, probe, files):
    """Runs PROBE with the AppDir's LIBRARY on FILES; fails if it cannot decode
    them or loads a host copy of an image library."""
    lib = (appdir / 'usr/lib').resolve()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('GDK_PIXBUF', 'LD_', 'KRYON_AVIF'))}
    env['GDK_PIXBUF_MODULE_FILE'] = str(appdir / PIXBUF_MODULES)
    result = subprocess.run([sys.executable, '-I', '-c', probe, lib / library, *files],
                            env=env, text=True, capture_output=True)
    if result.returncode:
        raise SystemExit(f'desktop release: the bundled {library} cannot decode the art: '
                         f'{result.stderr.strip() or result.stdout.strip()}')
    for path in map(Path, result.stdout.split()):
        if path.name.startswith(('libkryonavif', 'libgdk_pixbuf', 'libglib-', 'libgobject-', 'libgio-',
                                 'libgmodule-', 'libjpeg', 'libpng')) and lib not in path.parents:
            raise SystemExit(f'desktop release: the bundled {library} loaded the host\'s {path}')


def check_avif_decoder(appdir):
    """The AppDir's own libkryonavif.so decodes Choano's AVIF art."""
    if not (appdir / 'usr/lib' / AVIF).is_file():
        raise SystemExit(f'desktop release: the AppImage carries no {AVIF} for the AVIF art')
    probe_decoder(appdir, AVIF, AVIF_PROBE, [ROOT / 'assets/choano/title-landscape.avif',
                                             ROOT / 'assets/choano/fish/turtle-hd.avif'])


def check_pixbuf_decoder(appdir):
    """The AppDir's own GdkPixbuf, GLib and codecs decode the PNG icon with
    only its empty module list, so no host loader is needed."""
    probe_decoder(appdir, PIXBUF, DECODE_PROBE, [ROOT / 'assets/choano/icon.png'])


def check_image_decoders(appdir):
    check_avif_decoder(appdir)
    check_pixbuf_decoder(appdir)


def build_native():
    run(sys.executable, ROOT / 'scripts/build.py', 'native', cwd=ROOT)


def build_appimage(rebuild_native=True):
    """build/Choano.AppImage from the native desktop build and current assets."""
    version = current_version()
    if rebuild_native:
        build_native()
    if not NATIVE.exists():
        raise SystemExit(f'desktop release: {NATIVE.relative_to(ROOT)} is missing; run make native')
    linuxdeploy = fetch_tool('linuxdeploy-x86_64.AppImage')
    fetch_tool('linuxdeploy-plugin-appimage-x86_64.AppImage')
    appdir = stage_appdir(BUILD / 'Choano.AppDir', NATIVE, version)
    temp = BUILD / 'tmp'
    temp.mkdir(parents=True, exist_ok=True)
    APPIMAGE.unlink(missing_ok=True)
    env = dict(os.environ, ARCH='x86_64', LINUXDEPLOY_OUTPUT_VERSION=version, LDAI_OUTPUT=str(APPIMAGE),
               APPIMAGE_EXTRACT_AND_RUN='1', TMPDIR=str(temp),
               PATH=f'{TOOLS_DIR}{os.pathsep}{os.environ.get("PATH", "")}')
    env.pop('SOURCE_DATE_EPOCH', None)
    share = appdir / 'usr/share'
    run(linuxdeploy, '--appdir', appdir,
        '--executable', appdir / 'usr/bin' / EXECUTABLE,
        '--desktop-file', share / f'applications/{APP_ID}.desktop',
        '--icon-file', share / f'icons/hicolor/{ICON_SIZE}x{ICON_SIZE}/apps/{APP_ID}.png',
        '--library', system_library(PIXBUF),
        '--custom-apprun', PACKAGING / 'AppRun',
        '--output', 'appimage', cwd=BUILD, env=env)
    if not APPIMAGE.exists():
        raise SystemExit('desktop release: linuxdeploy finished without build/Choano.AppImage')
    try:
        check_image_decoders(appdir)
    except SystemExit:
        APPIMAGE.unlink()
        raise
    return APPIMAGE


def windows_tool(name):
    """A Windows build tool from PATH or the user's Nix profile."""
    found = shutil.which(name) or shutil.which(name, path=str(Path.home() / '.nix-profile/bin'))
    if not found:
        raise SystemExit(f'desktop release: {name} is missing; install MinGW-w64 and NSIS')
    return found


def mingw_library_flags():
    """-L folders a Nix MinGW wrapper expects its build environment to give
    it: the libraries it propagates, such as mcfgthread for its thread model.
    Other toolchains already find their own."""
    support = Path(windows_tool(MINGW + 'gcc')).resolve().parent.parent / 'nix-support'
    pending = (support / 'propagated-target-target-deps').read_text().split() if support.is_dir() else []
    seen, flags = set(), []
    while pending:
        path = Path(pending.pop())
        if path in seen:
            continue
        seen.add(path)
        if (path / 'lib').is_dir():
            flags.append(f'-L{path / "lib"}')
        propagated = path / 'nix-support/propagated-build-inputs'
        if propagated.is_file():
            pending += propagated.read_text().split()
    return flags


def package(name):
    return Path(subprocess.check_output([ZIRAN, 'pkg', 'path', name, *LOCKED], text=True, cwd=ROOT).strip())


def built(output, source):
    """Whether OUTPUT was already built from SOURCE (a path and its options)."""
    stamp = output.parent / (output.name + '.source')
    return output.is_file() and stamp.is_file() and stamp.read_text() == source


def record(output, source):
    (output.parent / (output.name + '.source')).write_text(source)


def windows_runtime(compiler):
    """The Ziran runtime of the locked toolchain, cross-compiled out of tree."""
    runtime = WINDOWS / 'runtime/libziran.a'
    if not built(runtime, str(compiler)):
        run('make', '-B', '-C', compiler, 'BOOTSTRAP=1', 'BUILD_DIR=' + str(runtime.parent),
            'CC=' + windows_tool(MINGW + 'gcc'), 'AR=' + windows_tool(MINGW + 'ar'),
            'OBJCOPY=' + windows_tool(MINGW + 'objcopy'), 'CFLAGS=-O2', runtime)
        record(runtime, str(compiler))
    return runtime


def windows_toolchain(folder):
    """A CMake toolchain file in FOLDER for this MinGW cross compiler."""
    toolchain = folder / 'mingw.cmake'
    toolchain.write_text(f'''set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER {windows_tool(MINGW + 'gcc')})
set(CMAKE_CXX_COMPILER {windows_tool(MINGW + 'g++')})
set(CMAKE_RC_COMPILER {windows_tool(MINGW + 'windres')})
set(CMAKE_AR {windows_tool(MINGW + 'ar')})
set(CMAKE_RANLIB {windows_tool(MINGW + 'ranlib')})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
''')
    return toolchain


def windows_cmake_library(name, source, library, identity, *configure):
    """LIBRARY from SOURCE's CMake target NAME, configured out of tree in
    LIBRARY's build folder unless IDENTITY already built it."""
    folder = WINDOWS / name
    if built(library, identity):
        return library
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    # A Nix MinGW links its thread library only from these folders, also in
    # CMake's own compiler checks.
    run('cmake', '-S', source, '-B', folder, '-DCMAKE_TOOLCHAIN_FILE=' + str(windows_toolchain(folder)),
        '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_SHARED_LIBS=OFF',
        '-DCMAKE_EXE_LINKER_FLAGS=' + ' '.join(mingw_library_flags()), *configure)
    run('cmake', '--build', folder, '--target', name, '--parallel', '1')
    record(library, identity)
    return library


def windows_raylib():
    """Static raylib from the locked package, configured out of tree."""
    source = package('raylib')
    library = WINDOWS / 'raylib/raylib/libraylib.a'
    linking = ' '.join(mingw_library_flags())
    identity = f'{source}\n{windows_tool(MINGW + "gcc")}\n{windows_tool(MINGW + "g++")}\n{RAYLIB_FLAGS}\n{linking}'
    windows_cmake_library(
        'raylib', source, library, identity, '-DBUILD_EXAMPLES=OFF', '-DPLATFORM=RGFW',
        '-DOPENGL_VERSION=1.1', '-DOPENGL_opengl_LIBRARY=opengl32', '-DOPENGL_gl_LIBRARY=opengl32',
        '-DCMAKE_C_FLAGS=' + RAYLIB_FLAGS)
    return source, library


def windows_webp():
    """Kryon's static WebP decoder (kryonwebp), which its raylib host links
    for WebP images, from Kryon's own CMake project and the locked libwebp."""
    project = package('kryon') / 'cmake/webp'
    source = package('libwebp')
    library = WINDOWS / 'kryonwebp/libkryonwebp.a'
    identity = f'{project}\n{source}\n{windows_tool(MINGW + "gcc")}\n{" ".join(mingw_library_flags())}'
    return windows_cmake_library('kryonwebp', project, library, identity,
                                 f'-DWEBP_DIR={source}', '-DCMAKE_C_FLAGS=-O2')


def windows_avif():
    """Kryon's static AVIF decoder, which its raylib host links for AVIF art:
    libavif with dav1d inside, and libaom, from Kryon's own CMake project and
    the avif package's locked sources."""
    project = package('kryon') / 'cmake/avif'
    sources = {name: package(name) for name in ('avif', 'libavif', 'libaom', 'dav1d')}
    folder = WINDOWS / 'avif_static'
    archives = [folder / 'avif/libavif.a', folder / 'aom/libaom.a']
    identity = '\n'.join([str(project), *map(str, sources.values()), windows_tool(MINGW + 'gcc'),
                          ' '.join(mingw_library_flags())])
    windows_cmake_library('avif_static', project, archives[0], identity,
                          f'-DKRYON_AVIF_PACKAGE_DIR={sources["avif"]}', f'-DAVIF_DIR={sources["libavif"]}',
                          f'-DAOM_DIR={sources["libaom"]}', f'-DDAV1D_DIR={sources["dav1d"]}')
    missing = [path for path in archives if not path.is_file()]
    if missing:
        raise SystemExit('desktop release: the AVIF build made no ' + ', '.join(map(str, missing)))
    return archives


def windows_opus():
    """libopus for the Ogg Opus decoder in Kryon's raylib audio, from the
    audio package's own CMake recipe and its locked sources."""
    sources = {name: package(name) for name in ('audio', 'libopus', 'libsamplerate')}
    library = WINDOWS / 'opus/libopus/libopus.a'
    identity = '\n'.join([*map(str, sources.values()), windows_tool(MINGW + 'gcc'), ' '.join(mingw_library_flags())])
    return windows_cmake_library('opus', sources['audio'] / 'native', library, identity,
                                 f'-DOPUS_DIR={sources["libopus"]}', f'-DSAMPLERATE_DIR={sources["libsamplerate"]}')


def windows_icon(target):
    square_icon(256).save(target, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
                                         (256, 256)])


def check_windows_program(path):
    """Fails unless PATH is a 64-bit x86 Windows GUI program."""
    data = path.read_bytes()
    header = int.from_bytes(data[0x3c:0x40], 'little') if data[:2] == b'MZ' else -1
    if header < 0 or data[header:header + 4] != b'PE\0\0':
        raise SystemExit(f'desktop release: {path.name} is not a Windows program')
    machine = int.from_bytes(data[header + 4:header + 6], 'little')
    optional = header + 24
    magic = int.from_bytes(data[optional:optional + 2], 'little')
    subsystem = int.from_bytes(data[optional + 68:optional + 70], 'little')
    if (machine, magic, subsystem) != (0x8664, 0x20b, 2):
        raise SystemExit(f'desktop release: {path.name} is machine {machine:#x}, optional header {magic:#x}, '
                         f'subsystem {subsystem}; expected an x86-64 PE32+ GUI program')


def windows_account_links():
    """Entity's account provider support for Windows, from its own recipe with
    this MinGW toolchain; its Ziran modules compile with the game."""
    sys.path.insert(0, str(ROOT / 'scripts'))
    import build as choano_build
    env = {k: v for k, v in os.environ.items() if k not in
           ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES')}
    env.update(CC=windows_tool(MINGW + 'gcc'), AR=windows_tool(MINGW + 'ar'), CMAKE_BUILD_PARALLEL_LEVEL='1')
    # A Nix MinGW links its thread library only from these folders, also in
    # the provider's CMake compiler checks; CMake starts from LDFLAGS.
    linking = mingw_library_flags()
    if linking:
        env['LDFLAGS'] = ' '.join([*filter(None, [env.get('LDFLAGS')]), *linking])
    return choano_build.account_links('windows-x86_64-mingw', env)


def build_windows_program():
    """build/windows/Choano.exe: src/windows.zi on raylib, linked statically."""
    # Resolve the provider before replacing any existing Windows build output.
    accounts = windows_account_links()
    for folder in (WINDOWS / 'ir', WINDOWS / 'c'):
        if folder.exists():
            shutil.rmtree(folder)
    run(ZIRAN, 'ir', '--project', *LOCKED, *WINDOWS_DEFINES, '-o', WINDOWS / 'ir', 'src/windows.zi', cwd=ROOT)
    generated = WINDOWS / 'c'
    run(ZIRAN, 'build', '--project', *LOCKED, '--target=c', *WINDOWS_DEFINES, '--entry', 'windows:main',
        '--root', WINDOWS / 'ir', '-o', generated, WINDOWS / 'ir/windows.zir', cwd=ROOT)
    compiler = package('ziran')
    runtime = windows_runtime(compiler)
    raylib_source, raylib = windows_raylib()
    webp = windows_webp()
    avif = windows_avif()
    opus = windows_opus()
    # The program's icon in Explorer, the taskbar and the installer.
    windows_icon(WINDOWS / 'choano.ico')
    (WINDOWS / 'choano.rc').write_text('1 ICON "choano.ico"\n')
    # windres preprocesses with the MinGW gcc beside it.
    gcc_folder = str(Path(windows_tool(MINGW + 'gcc')).parent)
    run(windows_tool(MINGW + 'windres'), '-O', 'coff', '-o', 'choano-resource.o', 'choano.rc', cwd=WINDOWS,
        env=dict(os.environ, PATH=gcc_folder + os.pathsep + os.environ.get('PATH', '')))
    includes = ['-I' + str(compiler / 'include')]
    for path in sorted({generated, *(item for item in generated.rglob('*') if item.is_dir())}):
        includes += ['-iquote', str(path)]
    program = WINDOWS / 'Choano.exe'
    partial = WINDOWS / 'Choano.new.exe'
    run(windows_tool(MINGW + 'gcc'), '-std=c11', '-O2', '-ffunction-sections', '-fdata-sections', *includes,
        *sorted(generated.rglob('*.c')), runtime, raylib, webp, *avif, opus, WINDOWS / 'choano-resource.o', '-Wl,--gc-sections',
        *mingw_library_flags(), '-static', '-static-libgcc', '-mwindows', *accounts, *WINDOWS_LIBRARIES,
        '-o', partial)
    run(windows_tool(MINGW + 'strip'), partial)
    check_windows_program(partial)
    partial.replace(program)
    return program


def stage_windows(stage, program):
    """The installed folder: the program, Kryon's font and every asset."""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copy2(program, stage / 'Choano.exe')
    shutil.copyfile(package('kryon') / 'assets/fonts/LiberationSans-Regular.ttf', stage / 'kryon-font.ttf')
    shutil.copytree(ROOT / 'assets', stage / 'assets')
    return stage


def build_windows():
    """build/Choano-setup.exe from the current game, art and audio."""
    version = current_version()
    WINDOWS.mkdir(parents=True, exist_ok=True)
    # The Profile bundle the account provider reads from assets/entity.zx.
    run(sys.executable, ROOT / 'scripts/build.py', 'profile-asset', cwd=ROOT)
    program = build_windows_program()
    stage = stage_windows(WINDOWS / 'Choano', program)
    partial = WINDOWS / 'Choano-setup.new.exe'
    partial.unlink(missing_ok=True)
    run(windows_tool('makensis'), '-V2', '-NOCD', f'-DVERSION={version}', f'-DSTAGE={stage}',
        f'-DICON={WINDOWS / "choano.ico"}', f'-DOUTFILE={partial}', WINDOWS_PACKAGING / 'choano.nsi', cwd=WINDOWS)
    partial.replace(SETUP)
    return SETUP


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    actions = parser.add_subparsers(dest='action', required=True)
    appimage = actions.add_parser('appimage', help='build build/Choano.AppImage')
    appimage.add_argument('--use-built-native', action='store_true',
                          help='package the existing build/Choano-native instead of rebuilding it')
    actions.add_parser('windows', help='build build/Choano-setup.exe')
    args = parser.parse_args()
    try:
        if args.action == 'appimage':
            path = build_appimage(rebuild_native=not args.use_built_native)
            public = next(name for name in expected_assets(current_version()) if name.endswith('.AppImage'))
        else:
            path = build_windows()
            public = next(name for name in expected_assets(current_version()) if name.endswith('-setup.exe'))
        print(f'{path.relative_to(ROOT)} (release name {public})')
    except (OSError, ReleaseError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'desktop release: {error}\n')


if __name__ == '__main__':
    main()
