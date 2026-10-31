#!/usr/bin/env python3
"""Render owned Choano scenes on a private display; no account or real wallet."""
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
env = {k: v for k, v in os.environ.items() if k not in (
    'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
env.update(YUE_DESKTOP_RECOVERY='0', SDL_AUDIODRIVER='dummy')
output = ROOT / 'work/visual-review'
subprocess.run(['git', 'check-ignore', str(output)], check=True, capture_output=True)
output.mkdir(parents=True, exist_ok=True)
env['CHOANO_DATA'] = str(output / 'fixture-profile')
env['LDLIBS'] = subprocess.check_output(['pkg-config', '--libs', 'sdl2', 'cairo', 'freetype2',
    'fontconfig', 'pangocairo'], text=True).strip()
subprocess.run(['ziran', 'build', '--project', '--locked', '--target=c', '--define', 'CHOANO_SHOP_TEST',
    '--exe', '--entry', 'visual_scene:main', '-o', 'build/visual-test', 'tests/visual_scene.zi'], env=env, check=True)
read_fd, write_fd = os.pipe()
server = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x1024x24',
    '-nolisten', 'tcp'], pass_fds=(write_fd,), env=env, stdout=subprocess.DEVNULL)
os.close(write_fd)
try:
    with os.fdopen(read_fd) as display:
        number = display.readline().strip()
    assert number
    env['DISPLAY'] = ':' + number
    for scene in ('shark-hit', 'crown', 'ribbon', 'pearl', 'flower', 'wizard', 'guide', 'shop', 'shop-locked', 'purchase', 'settings'):
        app = subprocess.Popen(['build/visual-test/visual_scene'], env=dict(env, CHOANO_TEST_SCENE=scene))
        try:
            window = None
            for _ in range(100):
                assert app.poll() is None, scene + ' exited'
                found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(app.pid)],
                    env=env, capture_output=True, text=True)
                if found.returncode == 0:
                    window = found.stdout.splitlines()[0]
                    break
                time.sleep(.05)
            assert window, scene + ' window missing'
            sizes = ((900, 680), (390, 844), (320, 640)) if scene in ('shop', 'shop-locked', 'purchase', 'guide', 'settings') else ((900, 680),)
            for width, height in sizes:
                subprocess.run(['xdotool', 'windowsize', window, str(width), str(height)], env=env, check=True)
                time.sleep(.6)
                subprocess.run(['import', '-window', window, str(output / f'{scene}-{width}.png')], env=env, check=True)
            if scene == 'shop':
                subprocess.run(['xdotool', 'mousemove', '--window', window, '286', '26', 'click', '1'], env=env, check=True)
                time.sleep(.3)
                subprocess.run(['import', '-window', window, str(output / 'shop-to-settings-320.png')], env=env, check=True)
            assert app.poll() is None
        finally:
            if app.poll() is None:
                app.terminate()
                app.wait(timeout=10)
    print('Choano local private visual scenes passed: headwear, fins, guide, Shop and Settings.')
finally:
    server.terminate()
    server.wait(timeout=10)
