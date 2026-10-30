#!/usr/bin/env python3
"""Run the built build/Choano.AppImage on a fresh private Xvfb display.

The image runs through APPIMAGE_EXTRACT_AND_RUN, so FUSE is not needed. Its
title screens must match the native build's pixel for pixel, proving the
packed art loads, and both modes must swim, dash and restart. Only this test's
own display and processes are touched.
"""
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
APPIMAGE = ROOT / 'build/Choano.AppImage'
NATIVE = ROOT / 'build/Choano-native'
SCRATCH = ROOT / 'build/appimage/smoke'
PROFILE = ROOT / 'work/appimage-profile'
# ImageMagick 7's magick command, or ImageMagick 6's separate programs.
IMAGEMAGICK = ['magick'] if shutil.which('magick') else []
env = {k: v for k, v in os.environ.items() if k not in
       ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
env.update(YUE_DESKTOP_RECOVERY='0', SDL_AUDIODRIVER='dummy', CHOANO_DATA=str(PROFILE),
           APPIMAGE_EXTRACT_AND_RUN='1', TMPDIR=str(SCRATCH / 'tmp'))


def inspect_contents():
    """The image's files: every asset unchanged and the game's libraries inside."""
    extract = SCRATCH / 'contents'
    extract.mkdir(parents=True)
    subprocess.run([APPIMAGE, '--appimage-extract'], cwd=extract, env=env, check=True, stdout=subprocess.DEVNULL)
    appdir = extract / 'squashfs-root'
    source = ROOT / 'assets'
    for path in source.rglob('*'):
        if path.is_file():
            packed = appdir / 'usr/share/choano/assets' / path.relative_to(source)
            assert packed.read_bytes() == path.read_bytes(), f'{packed} differs from {path}'
    assert (appdir / 'AppRun').read_bytes() == (ROOT / 'packaging/linux/AppRun').read_bytes()
    linked = subprocess.run(['ldd', appdir / 'usr/bin/Choano'], env=env, text=True,
                            capture_output=True, check=True).stdout
    assert 'not found' not in linked, linked
    for library in ('libSDL2-2.0.so.0', 'libcairo.so.2', 'libpango-1.0.so.0', 'libpangocairo-1.0.so.0'):
        assert f'{library} => {appdir}/usr/bin/../lib/{library}' in linked, (library, linked)
    # The art decoder the game opens at run time, with no loader modules of the host's.
    assert (appdir / 'usr/lib/libgdk_pixbuf-2.0.so.0').is_file(), 'GdkPixbuf is not bundled'
    modules = (appdir / 'usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache').read_text().splitlines()
    assert all(line.startswith('#') for line in modules), modules


def stop(*processes):
    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()


def window_for(launch, name):
    for _ in range(200):
        assert launch.poll() is None, f'{name} exited before opening'
        found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Choano$'],
                               env=env, text=True, capture_output=True)
        if found.returncode == 0:
            return found.stdout.split()[0]
        time.sleep(.1)
    raise AssertionError(f'{name} window missing')


def capture(window, path):
    """The owned window's exact 900x680 pixels, wherever the display placed it."""
    time.sleep(1.5)
    geometry = dict(line.split('=', 1) for line in subprocess.check_output(
        ['xdotool', 'getwindowgeometry', '--shell', window], env=env, text=True).split())
    assert (geometry['WIDTH'], geometry['HEIGHT']) == ('900', '680'), geometry
    subprocess.run([*IMAGEMAGICK, 'import', '-window', 'root', '-crop',
                    f'900x680+{geometry["X"]}+{geometry["Y"]}', '+repage', path], check=True, env=env)


def difference(a, b):
    result = subprocess.run([*IMAGEMAGICK, 'compare', '-metric', 'RMSE', a, b, 'null:'],
                            env=env, text=True, capture_output=True)
    return float(result.stderr.split('(')[1].split(')')[0])


def compare(mode, a, b):
    result = difference(a, b)
    try:
        assert result < .02, f'AppImage {mode} title differs from the native build: {result:.4f}'
    except AssertionError:
        diagnostics = ROOT / 'work/appimage-diagnostics'
        diagnostics.mkdir(parents=True, exist_ok=True)
        for shot in SCRATCH.glob('*.png'):
            shutil.copy2(shot, diagnostics / shot.name)
        raise
    return result


def run_title(command, cwd, fish, shot):
    """Opens one game on the title screen and captures it; the AppImage also plays."""
    PROFILE.mkdir(parents=True, exist_ok=True)
    # Controls, sound, then Fish mode unlocked and picked.
    (PROFILE / 'preferences.v1').write_text('1s011' if fish else '1s000')
    launch = subprocess.Popen(command, cwd=cwd, env=env)
    pid = None
    try:
        window = window_for(launch, command[0].name)
        pid = int(subprocess.check_output(['xdotool', 'getwindowpid', window], env=env, text=True))
        geometry = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', window], env=env, text=True)
        assert 'WIDTH=900' in geometry and 'HEIGHT=680' in geometry, geometry
        position = (20, 40) if command[0] == APPIMAGE else (330, 180)
        subprocess.run(['xdotool', 'windowmove', window, *map(str, position)], check=True, env=env)
        geometry = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', window], env=env, text=True)
        placed = dict(line.split('=', 1) for line in geometry.split())
        assert (placed['X'], placed['Y'], placed['WIDTH'], placed['HEIGHT']) == (
            str(position[0]), str(position[1]), '900', '680'), geometry
        capture(window, shot)
        if command[0] == APPIMAGE:
            folder = Path(os.readlink(f'/proc/{pid}/cwd'))
            assert folder.parts[-3:] == ('usr', 'share', 'choano') and SCRATCH / 'tmp' in folder.parents, folder
            maps = Path(f'/proc/{pid}/maps').read_text()
            for library in ('libSDL2-2.0.so.0', 'libgdk_pixbuf-2.0.so.0', 'libglib-2.0.so.0'):
                assert f'{folder.parents[1]}/lib/{library}' in maps, f'bundled {library} is not the one loaded'
            assert '/gdk-pixbuf-2.0/2.10.0/loaders/' not in maps, 'a GdkPixbuf loader module was loaded'
            play(window, fish, launch, pid)
    finally:
        # The image's runtime waits for the game it unpacked, so the game goes first.
        if pid is not None and pid != launch.pid:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
        stop(launch)
        for _ in range(100):
            if subprocess.run(['xdotool', 'search', '--name', '^Choano$'], env=env,
                              capture_output=True).returncode != 0:
                break
            time.sleep(.1)


def play(window, fish, launch, pid):
    """Starts a run in the saved mode and swims; Fish mode also dashes."""
    subprocess.run(['xdotool', 'windowfocus', window, 'key', 'Return'], check=True, env=env)
    time.sleep(.2)
    subprocess.run(['xdotool', 'keydown', 'Right'], check=True, env=env)
    time.sleep(.4)
    if fish:
        subprocess.run(['xdotool', 'key', 'x'], check=True, env=env)
        time.sleep(.3)
    subprocess.run(['xdotool', 'keyup', 'Right', 'key', 'r'], check=True, env=env)
    time.sleep(.3)
    assert launch.poll() is None and Path(f'/proc/{pid}').exists(), \
        'AppImage game failed during %s swimming/restart' % ('Fish' if fish else 'amoeba')


assert APPIMAGE.exists(), 'Build it first: python3 scripts/desktop_release.py appimage'
assert NATIVE.exists(), 'Build the native game first: make native'
if SCRATCH.exists():
    shutil.rmtree(SCRATCH)
(SCRATCH / 'tmp').mkdir(parents=True)
inspect_contents()
read_fd, write_fd = os.pipe()
server = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x1024x24', '-nolisten', 'tcp'],
                          pass_fds=(write_fd,), env=env, stdout=subprocess.DEVNULL)
os.close(write_fd)
try:
    with os.fdopen(read_fd) as display:
        number = display.readline().strip()
    assert number, 'Private Xvfb did not start'
    env['DISPLAY'] = ':' + number
    shots = {}
    for fish in (False, True):
        mode = 'fish' if fish else 'dish'
        # Opened from the profile folder, which has no assets of its own.
        run_title([APPIMAGE], PROFILE, fish, SCRATCH / f'appimage-{mode}.png')
        run_title([NATIVE], ROOT, fish, SCRATCH / f'native-{mode}.png')
        shots[mode] = compare(mode, SCRATCH / f'appimage-{mode}.png', SCRATCH / f'native-{mode}.png')
    modes = difference(SCRATCH / 'appimage-dish.png', SCRATCH / 'appimage-fish.png')
    assert modes > 0.05, f'Fish title art did not replace the dish title: {modes:.4f}'
    print('Choano AppImage local test passed on private Xvfb: assets and libraries packed, titles match the '
          f'native build (RMSE dish {shots["dish"]:.4f}, fish {shots["fish"]:.4f}; modes differ by {modes:.4f}), '
          'and both modes swim, dash and restart.')
finally:
    stop(server)
    # Title captures only served the comparison above; the runtime keeps what it unpacked.
    for shot in SCRATCH.glob('*.png'):
        shot.unlink()
    shutil.rmtree(SCRATCH / 'tmp', ignore_errors=True)
