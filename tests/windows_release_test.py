#!/usr/bin/env python3
"""Install build/Choano-setup.exe silently in a private Wine prefix and play it
on a fresh private Xvfb display.

The installer must place the program, font and every asset, its shortcuts and
its uninstall entry for this user only. Started from another folder, the
installed game opens its 900x680 window, draws the JPEG title art close to
the native build's (and Fish mode's art differently), opens raylib's audio
device for its chimes, swims, dashes and restarts, and saves its settings in
Local AppData. The silent uninstaller then removes it all but the settings.
Wine gets a private HOME and a silent ALSA device, so nothing reaches the
owner's desktop folder or speakers; only this test's prefix, display and
processes are touched.
"""
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from desktop_release import check_windows_program
SETUP = ROOT / 'build/Choano-setup.exe'
NATIVE = ROOT / 'build/Choano-native'
SCRATCH = ROOT / 'work/windows-test'
PREFIX = SCRATCH / 'prefix'
HOME = SCRATCH / 'home'
NATIVE_PROFILE = SCRATCH / 'native-profile'
DRIVE = PREFIX / 'drive_c'
USER = DRIVE / 'users' / getpass.getuser()
INSTALLED = USER / 'AppData/Local/Programs/Choano'
SETTINGS = USER / 'AppData/Local/Choano/preferences.v1'
SHORTCUTS = (USER / 'AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Choano.lnk', USER / 'Desktop/Choano.lnk')

env = {k: v for k, v in os.environ.items() if k not in
       ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER',
        'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR', 'PULSE_SERVER')}
env.update(YUE_DESKTOP_RECOVERY='0', WINEPREFIX=str(PREFIX), WINEDEBUG='-all', HOME=str(HOME),
           WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree=d;mshtml=d', XDG_RUNTIME_DIR=str(SCRATCH / 'runtime'),
           ALSA_CONFIG_PATH=str(SCRATCH / 'alsa.conf'), PULSE_SERVER='unix:' + str(SCRATCH / 'no-pulse'),
           SDL_AUDIODRIVER='dummy')


def wine(*args, timeout=180, **options):
    return subprocess.run(['wine', *map(str, args)], env=env, timeout=timeout, **options)


def wait_prefix(timeout=120):
    """Waits until this prefix's own Wine processes have all ended."""
    subprocess.run(['wineserver', '-w'], env=env, timeout=timeout, check=True)


def stop(*processes):
    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()


def window_for(launch, name):
    for _ in range(300):
        assert launch.poll() is None, f'{name} exited before opening'
        found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Choano$'],
                               env=env, text=True, capture_output=True)
        if found.returncode == 0:
            return found.stdout.split()[0]
        time.sleep(.1)
    raise AssertionError(f'{name} window missing')


def window_gone():
    for _ in range(100):
        if subprocess.run(['xdotool', 'search', '--name', '^Choano$'], env=env, capture_output=True).returncode:
            return
        time.sleep(.1)


def capture(window, path):
    """The window's own 900x680 pixels, wherever the display placed it."""
    time.sleep(2)
    geometry = dict(line.split('=', 1) for line in subprocess.check_output(
        ['xdotool', 'getwindowgeometry', '--shell', window], env=env, text=True).split())
    assert (geometry['WIDTH'], geometry['HEIGHT']) == ('900', '680'), geometry
    subprocess.run(['magick', 'import', '-window', 'root', '-crop', f'900x680+{geometry["X"]}+{geometry["Y"]}', path],
                   check=True, env=env)


def difference(a, b):
    result = subprocess.run(['magick', 'compare', '-metric', 'RMSE', a, b, 'null:'],
                            env=env, text=True, capture_output=True)
    return float(result.stderr.split('(')[1].split(')')[0])


def key(window, *names):
    subprocess.run(['xdotool', 'windowfocus', window, 'key', *names], check=True, env=env)


def install():
    """A fresh prefix whose audio is a silent ALSA device, then the installer."""
    for path in (PREFIX, HOME):
        if path.exists():
            shutil.rmtree(path)
    HOME.mkdir(parents=True)
    (SCRATCH / 'runtime').mkdir(mode=0o700, exist_ok=True)
    (SCRATCH / 'alsa.conf').write_text('pcm.!default { type null }\n')
    wine('wineboot', '--init', timeout=300, check=True, capture_output=True)
    wine('reg', 'add', r'HKCU\Software\Wine\Drivers', '/v', 'Audio', '/d', 'alsa', '/f', check=True,
         capture_output=True)
    wait_prefix()
    wine(SETUP, '/S', check=True)
    wait_prefix()
    for name in ('Choano.exe', 'Uninstall.exe', 'kryon-font.ttf'):
        assert (INSTALLED / name).is_file(), f'{name} is not installed in {INSTALLED}'
    check_windows_program(INSTALLED / 'Choano.exe')
    source = ROOT / 'assets'
    count = 0
    for path in source.rglob('*'):
        if path.is_file():
            packed = INSTALLED / 'assets' / path.relative_to(source)
            assert packed.read_bytes() == path.read_bytes(), f'{packed} differs from {path}'
            count += 1
    for shortcut in SHORTCUTS:
        assert shortcut.is_file(), f'{shortcut} missing'
    registry = (PREFIX / 'user.reg').read_text(errors='replace')
    assert r'[Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Choano]' in registry, \
        'the uninstall entry is not in HKCU'
    version = (ROOT / 'VERSION').read_text().strip()
    assert f'"DisplayVersion"="{version}"' in registry, f'the uninstall entry does not name {version}'
    # Per-user only: nothing under Program Files or the machine's registry.
    assert not (DRIVE / 'Program Files/Choano').exists() and not (DRIVE / 'Program Files (x86)/Choano').exists()
    assert 'Uninstall\\\\Choano]' not in (PREFIX / 'system.reg').read_text(errors='replace')
    return count


def run_title(fish, shot, log):
    """Opens the installed game on its title screen from another folder, and
    in the dish also plays and mutes its sound, which saves the settings."""
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    # Controls, sound, then Fish mode unlocked and picked.
    SETTINGS.write_text('1s011' if fish else '1s000')
    with open(log, 'w') as output:
        launch = subprocess.Popen(['wine', INSTALLED / 'Choano.exe'], cwd=SCRATCH, env=env,
                                  stdout=output, stderr=subprocess.STDOUT)
    try:
        window = window_for(launch, 'Choano.exe')
        capture(window, shot)
        if not fish:
            key(window, 'Return')
            time.sleep(1)
            subprocess.run(['xdotool', 'keydown', 'Right'], check=True, env=env)
            time.sleep(.5)
            subprocess.run(['xdotool', 'key', 'x'], check=True, env=env)
            time.sleep(.3)
            subprocess.run(['xdotool', 'keyup', 'Right', 'key', 'r'], check=True, env=env)
            time.sleep(.5)
            key(window, 'm')
            for _ in range(50):
                if SETTINGS.read_text() == '1s100':
                    break
                time.sleep(.1)
            assert SETTINGS.read_text() == '1s100', f'muting saved {SETTINGS.read_text()!r}, not 1s100'
        assert launch.poll() is None, 'the Windows game exited while playing'
    finally:
        stop(launch)
        subprocess.run(['wineserver', '-k'], env=env, timeout=60)
        window_gone()


def run_native(fish, shot):
    NATIVE_PROFILE.mkdir(parents=True, exist_ok=True)
    (NATIVE_PROFILE / 'preferences.v1').write_text('1s011' if fish else '1s000')
    launch = subprocess.Popen([NATIVE], cwd=ROOT, env=dict(env, CHOANO_DATA=str(NATIVE_PROFILE)),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        capture(window_for(launch, 'Choano-native'), shot)
    finally:
        stop(launch)
        window_gone()


def uninstall():
    wine(INSTALLED / 'Uninstall.exe', '/S', check=True)
    # The uninstaller finishes from a copy of itself in the prefix's Temp.
    wait_prefix()
    assert not INSTALLED.exists(), f'{INSTALLED} remains after uninstalling'
    for shortcut in SHORTCUTS:
        assert not shortcut.exists(), f'{shortcut} remains after uninstalling'
    registry = (PREFIX / 'user.reg').read_text(errors='replace')
    assert 'Uninstall\\\\Choano]' not in registry, 'the uninstall entry remains'
    assert SETTINGS.is_file(), 'the player\'s settings must stay'


assert SETUP.exists(), 'Build it first: python3 scripts/desktop_release.py windows'
assert NATIVE.exists(), 'Build the native game first: make native'
SCRATCH.mkdir(parents=True, exist_ok=True)
for stale in SCRATCH.glob('*.png'):
    stale.unlink()
read_fd, write_fd = os.pipe()
server = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x1024x24', '-nolisten', 'tcp'],
                          pass_fds=(write_fd,), env=env, stdout=subprocess.DEVNULL)
os.close(write_fd)
try:
    with os.fdopen(read_fd) as display:
        number = display.readline().strip()
    assert number, 'Private Xvfb did not start'
    env['DISPLAY'] = ':' + number
    assets = install()
    shots = {}
    for fish in (False, True):
        mode = 'fish' if fish else 'dish'
        run_title(fish, SCRATCH / f'windows-{mode}.png', SCRATCH / f'windows-{mode}.log')
        run_native(fish, SCRATCH / f'native-{mode}.png')
        shots[mode] = difference(SCRATCH / f'windows-{mode}.png', SCRATCH / f'native-{mode}.png')
    modes = difference(SCRATCH / 'windows-dish.png', SCRATCH / 'windows-fish.png')
    log = (SCRATCH / 'windows-dish.log').read_text(errors='replace')
    for line in ('AUDIO: Device initialized successfully', 'game-start.wav] File loaded successfully'):
        assert line in log, f'raylib did not report {line!r}; see {SCRATCH / "windows-dish.log"}'
    for mode, value in shots.items():
        assert value < 0.04, f'Windows {mode} title differs from the native build: {value:.4f}'
    assert modes > 0.05, f'Fish title art did not replace the dish title: {modes:.4f}'
    uninstall()
    print(f'Choano Windows installer local test passed in a private Wine prefix on private Xvfb: {assets} assets, '
          'font, shortcuts and per-user uninstall entry installed; titles close to the native build (RMSE dish '
          f'{shots["dish"]:.4f}, fish {shots["fish"]:.4f}; modes differ by {modes:.4f}); audio device and chime '
          'loaded; swims, dashes, restarts and saves muted settings to Local AppData; silent uninstall removes '
          'the game and keeps the settings.')
finally:
    subprocess.run(['wineserver', '-k'], env=env, timeout=60)
    stop(server)
    # Captures only served the comparisons above.
    for shot in SCRATCH.glob('*.png'):
        shot.unlink()
