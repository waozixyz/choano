#!/usr/bin/env python3
"""Verify distributed replacement assets and the independent package contract."""
import hashlib
import json
from pathlib import Path
import struct
import wave

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

def largest_pink_component(image, region):
    active = bytearray(red > 180 and green < 120 and blue > 140 and red - green > 60
                       for red, green, blue in image.crop(region).getdata())
    visited = bytearray(len(active))
    width, height = image.crop(region).size
    largest = 0
    for start, is_active in enumerate(active):
        if not is_active or visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        size = 0
        while stack:
            offset = stack.pop()
            size += 1
            y, x = divmod(offset, width)
            for neighbor_y, neighbor_x in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= neighbor_y < height and 0 <= neighbor_x < width:
                    neighbor = neighbor_y * width + neighbor_x
                    if active[neighbor] and not visited[neighbor]:
                        visited[neighbor] = 1
                        stack.append(neighbor)
        largest = max(largest, size)
    return largest

def jpeg_details(data):
    offset = 2
    while offset + 4 < len(data):
        if data[offset] != 0xff:
            return None
        marker = data[offset + 1]
        offset += 2
        if marker in (0x01, 0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
            continue
        length = int.from_bytes(data[offset:offset + 2], 'big')
        if 0xc0 <= marker <= 0xcf and marker not in (0xc4, 0xc8, 0xcc):
            components = data[offset + 7]
            sampling = [data[offset + 9 + index * 3] for index in range(components)]
            return marker, int.from_bytes(data[offset + 3:offset + 5], 'big'), components, sampling
        if marker == 0xda:
            break
        offset += length
    return None

manifest = json.loads((ROOT / 'assets/manifest.json').read_text())
files = manifest['files']
actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'assets/choano').rglob('*') if p.is_file()}
assert actual == set(files), 'Missing or unexpected replacement assets'
assert hashlib.sha256(''.join(k+' '+v+'\n' for k,v in files.items()).encode()).hexdigest() == manifest['sha256']
for name, digest in files.items():
    path = ROOT / name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, name
    if path.suffix == '.png':
        with path.open('rb') as handle:
            header = handle.read(33)
        assert header[:8] == b'\x89PNG\r\n\x1a\n', name
        width, height = struct.unpack('>II', header[16:24])
        assert width > 0 and height > 0, name
        if path.name.startswith(('player-', 'enemy-')):
            size = int(path.stem.split('-')[-2])
            assert (width, height) == (size, size) and header[25] == 6, name
        if path.name.startswith('accessory-'):
            assert (width, height) == (512, 512) and header[25] == 6, name
            with Image.open(path) as image:
                alpha_bbox = image.convert('RGBA').getchannel('A').getbbox()
            assert alpha_bbox and all(margin > 0 for margin in (
                alpha_bbox[0], alpha_bbox[1], width - alpha_bbox[2], height - alpha_bbox[3])), name
        if path.name == 'turtle-hd.png':
            assert (width, height) == (640, 427) and header[25] == 6, name
        if path.name == 'title-logo.png':
            assert width >= 2048 and header[25] == 6, name
            with Image.open(path) as image:
                assert image.mode == 'RGBA', name
                alpha = image.getchannel('A')
                alpha_bbox = alpha.getbbox()
                assert alpha_bbox, name
                margins = (alpha_bbox[0], alpha_bbox[1],
                           width - alpha_bbox[2], height - alpha_bbox[3])
                assert min(margins) > 0 and max(margins) - min(margins) <= 2, name
                # Transparent space around/between letters, not an opaque panel.
                artwork = image.crop(alpha_bbox)
                artwork.thumbnail((512, 256))
                pixels = list(artwork.getdata())
                opaque = [(r, g, b) for r, g, b, a in pixels if a >= 250]
                assert .35 < len(opaque) / len(pixels) < .88, name
                assert sum(r > 150 and r - g > 40 and b > 70
                           for r, g, b in opaque) > len(opaque) * .55, name
                assert sum(max(r, g, b) < 110 for r, g, b in opaque) > len(opaque) * .005, name
        if path.name.startswith('blob-'):
            assert (width, height) == (39, 39) and header[25] == 6, name
    elif path.name == 'shark-music.wav':
        # The one loop: only while a shark hunts, and still kept quiet.
        with wave.open(str(path)) as sound:
            assert sound.getnchannels() == 1 and sound.getframerate() == 22050 and sound.getsampwidth() == 2
            assert 4 <= sound.getnframes()/sound.getframerate() <= 10
            raw = sound.readframes(sound.getnframes())
            samples = struct.unpack('<' + 'h' * (len(raw)//2), raw)
            assert max(map(abs, samples)) <= .35 * 32767, 'Shark loop too loud'
    elif path.suffix == '.jpg':
        data = path.read_bytes()
        details = jpeg_details(data)
        assert data[:2] == b'\xff\xd8' and data[-2:] == b'\xff\xd9', name
        assert b'JFIF' in data[:32] and details is not None, name
        marker, height, components, sampling = details
        assert marker == 0xc0 and components == 3 and sampling == [0x11] * 3, name
        assert len(data) < 800_000 and height >= 1024, name
    elif path.suffix == '.wav':
        with wave.open(str(path)) as sound:
            assert sound.getcomptype() == 'NONE' and sound.getnchannels() == 1
            assert sound.getframerate() == 22050 and sound.getsampwidth() == 2
            assert .04 <= sound.getnframes()/sound.getframerate() < .25
            raw = sound.readframes(sound.getnframes())
            assert len(set(raw)) > 1, name
            samples = struct.unpack('<' + 'h' * (len(raw)//2), raw)
            assert max(map(abs, samples)) <= .12 * 32767, 'Effect too loud: ' + name
assert len([p for p in actual if p.endswith('.png')]) == 195
assert len([p for p in actual if p.endswith('.jpg')]) == 4
assert len([p for p in actual if p.endswith('.wav')]) == 7
assert not (ROOT / 'assets/original').exists()
for p in (ROOT / 'assets').rglob('*'):
    assert p.suffix.lower() not in {'.exe', '.dll', '.gam', '.gif'}, p
catalog = json.loads((ROOT / 'catalog.json').read_text())
assert catalog['id'] == 'xyz.waozi.choano' and catalog['module_api'] == 2
assert (ROOT / catalog['source']).is_file() and (ROOT / catalog['preview']).is_file()
awards = json.loads((ROOT / 'assets/choano/achievements.json').read_text())
assert awards['app'] == catalog['id'] and all(a['metric'].startswith(catalog['id'] + '.') for a in awards['achievements'])
assert all((ROOT / a['icon']).is_file() for a in awards['achievements'])
for path in (ROOT / 'assets/choano/achievement-locales').glob('*.json'):
    values = json.loads(path.read_text())
    assert {k for a in awards['achievements'] for k in (a['title_key'], a['description_key'])} <= set(values), path
    assert values.get('fish_first_hint', '').strip(), path
assert '[dependencies.arcade]' not in (ROOT / 'ziran.toml').read_text()
title_regions = {
    'title-portrait.jpg': (78, 173, 941, 395),
    'title-landscape.jpg': (280, 88, 1255, 320),
    'fish/title-portrait.jpg': (40, 70, 980, 307),
    'fish/title-landscape.jpg': (480, 25, 1035, 170),
}
for name, size in [('title-portrait.jpg', (1024, 1536)), ('title-landscape.jpg', (1536, 1024)),
                   ('fish/title-portrait.jpg', (1024, 1536)), ('fish/title-landscape.jpg', (1536, 1024))]:
    with Image.open(ROOT / 'assets/choano' / name) as image:
        assert image.mode == 'RGB' and image.size == size, name
        # Original artwork is retained; a separate patch removes its baked logo.
        pass

for name, minimum in [('organisms-hd.png',1254)]:
    with (ROOT / 'assets/choano' / name).open('rb') as handle:
        header=handle.read(33)
    assert min(struct.unpack('>II',header[16:24])) >= minimum, name

print('Choano local asset and package tests passed: 195 PNGs, 4 JPEG titles, 6 quiet chimes and the shark loop.')

# UI labels must stay within the bundled Latin font's coverage. In particular,
# a check or padlock must be geometry/an image, never a missing text glyph.
import re
import subprocess
font = Path(subprocess.check_output(['ziran', 'pkg', 'path', 'kryon', *([] if (ROOT / 'ziran.local.toml').exists() else ['--locked'])], text=True).strip()) / 'assets/fonts/LiberationSans-Regular.ttf'
# Read the font cmap with the standard library (CI needs no fontTools install).
data = font.read_bytes()
tables = {data[12+i*16:16+i*16].decode(): struct.unpack_from('>II', data, 20+i*16) for i in range(struct.unpack_from('>H', data, 4)[0])}
offset, size = tables['cmap']
cmap = data[offset:offset+size]
covered = set()
for i in range(struct.unpack_from('>H', cmap, 2)[0]):
    sub = struct.unpack_from('>I', cmap, 8+i*8)[0]
    if struct.unpack_from('>H', cmap, sub)[0] != 4: continue
    count = struct.unpack_from('>H', cmap, sub+6)[0]//2
    end = sub+14
    start = end+count*2+2
    for j in range(count):
        lo = struct.unpack_from('>H', cmap, start+j*2)[0]
        hi = struct.unpack_from('>H', cmap, end+j*2)[0]
        covered.update(range(lo, hi+1))
for name in ('shell.zi', 'app.zi', 'accessories.zi'):
    source = re.sub(r'//[^\n]*', '', (ROOT/'src'/name).read_text())
    for text in re.findall(r'"([^"\n]*)"', source):
        assert all(ord(c) in covered or c in '\n\t' for c in text), (name,text)
for name in ('gear', 'shop', 'lock'):
    image = Image.open(ROOT/f'assets/choano/{name}.png').convert('RGBA')
    assert image.size == (1024,1024)
    assert all(image.getpixel(point)[3] == 0 for point in ((0,0),(1023,0),(0,1023),(1023,1023)))
    alpha = image.getchannel('A')
    # A white plate inside transparent corners is still a plate: keep every
    # outer edge transparent, with padding, and require a cut-out silhouette.
    left, top, right, bottom = alpha.getbbox()
    assert min(left, top, 1024-right, 1024-bottom) >= 24, name
    histogram = alpha.histogram()
    assert histogram[0] > 1024*1024*.25, name
    assert sum(histogram[200:]) > sum(histogram[1:])*.9, name

for path in (ROOT/'src/locales').glob('*.txt'):
    values = dict(re.findall(r'\[([^\]]+)\]\n([^\n]+)\n---', path.read_text()))
    for key in ('choano_shop', 'choano_settings', *('choano_settings_'+name for name in ('controls','swipe','pad','sound','sound_on','sound_off','done','save_error'))):
        assert values[key] and values[key] in (ROOT/'src/ui_strings.zi').read_text(), (path, key)

for path in (ROOT/'assets/choano/achievement-locales').glob('*.json'):
    text = json.loads(path.read_text())['choano_fish_unlock']
    assert text and text in (ROOT/'src/locales'/f'{path.stem}.txt').read_text()
    assert text in (ROOT/'src/ui_strings.zi').read_text()
for name in ('portrait', 'landscape', 'fish-portrait', 'fish-landscape'):
    with Image.open(ROOT/f'assets/choano/title-clean-{name}.png') as image:
        assert largest_pink_component(image.convert('RGB'), (0,0,*image.size)) < 1000
