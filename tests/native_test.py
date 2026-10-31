#!/usr/bin/env python3
"""Open only our Choano process on a fresh private Xvfb display."""
import os
from pathlib import Path
import subprocess
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
env = {k: v for k, v in os.environ.items() if k not in
       ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'SESSION_MANAGER')}
env.update(YUE_DESKTOP_RECOVERY='0', SDL_AUDIODRIVER='dummy', CHOANO_DATA=str(ROOT / 'work/native-profile'))
SHOTS = ROOT / 'work/visual-review'
subprocess.run(['git', 'check-ignore', str(SHOTS)], cwd=ROOT, check=True, capture_output=True)
SHOTS.mkdir(parents=True, exist_ok=True)
def play(env, fish):
    """Opens Choano, starts a run in the saved mode and swims."""
    profile = ROOT / 'work/native-profile'
    profile.mkdir(parents=True, exist_ok=True)
    # Controls, sound, then Fish mode unlocked and picked.
    (profile / 'preferences.v1').write_text('1s011' if fish else '1s000')
    app = subprocess.Popen([str(ROOT / 'build/Choano-native')], cwd=ROOT, env=env)
    try:
        window = ''
        for _ in range(100):
            assert app.poll() is None, 'Native game exited before opening'
            found = subprocess.run(['xdotool', 'search', '--onlyvisible', '--pid', str(app.pid), '--name', 'Choano'],
                                   env=env, text=True, capture_output=True)
            if found.returncode == 0:
                window = found.stdout.splitlines()[0]
                break
            time.sleep(.1)
        assert window, 'Native Choano window missing'
        geometry = subprocess.check_output(['xdotool', 'getwindowgeometry', '--shell', window], env=env, text=True)
        assert 'WIDTH=900' in geometry and 'HEIGHT=680' in geometry, geometry
        if not fish:
            # Open the actual packaged Profile without signing in or spending.
            time.sleep(.3)
            subprocess.run(['xdotool', 'mousemove', '--window', window, '780', '26', 'click', '1'], check=True, env=env)
            time.sleep(.6)
            subprocess.run(['import', '-window', window, str(SHOTS / 'native-profile.png')], check=True, env=env)
            assert (profile / 'profile/client.id').read_text().strip(), 'The isolated account provider did not start'
            assert app.poll() is None, 'Native Profile failed to draw'
            subprocess.run(['xdotool', 'mousemove', '--window', window, '50', '24', 'click', '1'], check=True, env=env)
            time.sleep(.2)
        subprocess.run(['xdotool', 'windowfocus', window, 'key', 'Return'], check=True, env=env)
        time.sleep(.2)
        for width, height in ((320, 640), (390, 844), (900, 680)):
            subprocess.run(['xdotool', 'windowsize', window, str(width), str(height)], check=True, env=env)
            time.sleep(.5)
            path = SHOTS / (('fish' if fish else 'amoeba') + f'-{width}.png')
            subprocess.run(['import', '-window', window, str(path)], check=True, env=env)
            with Image.open(path) as screenshot:
                score = screenshot.convert('RGB').crop((68, 19, width - 116, 47))
                assert sum(min(pixel) >= 210 for pixel in score.getdata()) > 8, 'Score must render bright text on the dark HUD'
            # Exercise the actual icon hit target, then resume the same run.
            subprocess.run(['xdotool', 'mousemove', '--window', window, '32', '25', 'click', '1'], check=True, env=env)
            time.sleep(.1)
            subprocess.run(['xdotool', 'key', 'Escape'], check=True, env=env)
        subprocess.run(['xdotool', 'keydown', 'Right'], check=True, env=env)
        time.sleep(.4)
        subprocess.run(['xdotool', 'keyup', 'Right', 'key', 'r'], check=True, env=env)
        time.sleep(.3)
        assert app.poll() is None, 'Native game failed during %s swimming/restart' % ('Fish' if fish else 'amoeba')
    finally:
        if app.poll() is None:
            app.terminate()
            try:
                app.wait(timeout=10)
            except subprocess.TimeoutExpired:
                app.kill(); app.wait()


read_fd, write_fd = os.pipe()
server = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0', '1280x1024x24', '-nolisten', 'tcp'],
                          pass_fds=(write_fd,), env=env, stdout=subprocess.DEVNULL)
os.close(write_fd)
try:
    with os.fdopen(read_fd) as display:
        number = display.readline().strip()
    assert number, 'Private Xvfb did not start'
    env['DISPLAY'] = ':' + number
    play(env, False)
    play(env, True)
    print('Choano local native window/input test passed on private Xvfb, in the dish and in Fish mode.')
finally:
    server.terminate()
    server.wait(timeout=10)
