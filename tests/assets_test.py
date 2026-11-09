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

def mean_visible_color(image, region):
    crop = image.crop(region).convert('RGBA')
    red = green = blue = weight = 0
    for alpha, pixel in zip(crop.getchannel('A').getdata(), crop.convert('RGB').getdata()):
        red += pixel[0] * alpha
        green += pixel[1] * alpha
        blue += pixel[2] * alpha
        weight += alpha
    return red / weight, green / weight, blue / weight

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
        # The one PNG: the install, favicon, Windows and Android icon source.
        assert path.name == 'icon.png', name
        assert path.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n', name
    elif path.suffix == '.avif':
        # scripts/avif_assets.py: Jungle's AVIF settings from local masters.
        assert path.read_bytes()[4:12] == b'ftypavif', name
        with Image.open(path) as image:
            assert image.format == 'AVIF', name
            width, height = image.size
            rgba = image.mode == 'RGBA'
        assert width > 0 and height > 0, name
        if path.name.startswith(('player-', 'enemy-')):
            size = int(path.stem.split('-')[-2])
            assert (width, height) == (size, size) and rgba, name
        if path.name.startswith('accessory-'):
            # Source rectangles are in the overlay's 512 px pixels.
            assert (width, height) == (512, 512) and rgba, name
            with Image.open(path) as image:
                alpha_bbox = image.convert('RGBA').getchannel('A').getbbox()
            assert alpha_bbox and all(margin > 0 for margin in (
                alpha_bbox[0], alpha_bbox[1], width - alpha_bbox[2], height - alpha_bbox[3])), name
            if path.name == 'accessory-ribbon.avif':
                with Image.open(path) as ribbon:
                    opaque = [pixel for pixel in ribbon.convert('RGBA').getdata() if pixel[3] >= 240]
                assert opaque and sum(r > 150 and g < 175 and r > g * 1.2 and r > b * 1.1
                                      for r, g, b, a in opaque) > len(opaque) * .6, \
                    'The ribbon must be a coral satin bow, not a second golden halo'
        if path.name == 'turtle-hd.avif':
            assert (width, height) == (640, 427) and rgba, name
        if path.name == 'title-logo.avif':
            # 75% of the 2416 x 736 master.
            assert (width, height) == (1812, 552) and rgba, name
            with Image.open(path) as image:
                image = image.convert('RGBA')
                alpha = image.getchannel('A').point(lambda value: 255 if value > 8 else 0)
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
            assert (width, height) == (39, 39) and rgba, name
    elif path.name == 'shark-music.wav':
        # The one loop: only while a shark hunts, and still kept quiet.
        with wave.open(str(path)) as sound:
            assert sound.getnchannels() == 1 and sound.getframerate() == 22050 and sound.getsampwidth() == 2
            assert 4 <= sound.getnframes()/sound.getframerate() <= 10
            raw = sound.readframes(sound.getnframes())
            samples = struct.unpack('<' + 'h' * (len(raw)//2), raw)
            assert max(map(abs, samples)) <= .35 * 32767, 'Shark loop too loud'
    elif path.suffix == '.wav':
        with wave.open(str(path)) as sound:
            assert sound.getcomptype() == 'NONE' and sound.getnchannels() == 1
            assert sound.getframerate() == 22050 and sound.getsampwidth() == 2
            assert .04 <= sound.getnframes()/sound.getframerate() < .25
            raw = sound.readframes(sound.getnframes())
            assert len(set(raw)) > 1, name
            samples = struct.unpack('<' + 'h' * (len(raw)//2), raw)
            assert max(map(abs, samples)) <= .12 * 32767, 'Effect too loud: ' + name
assert [p for p in actual if p.endswith('.png')] == ['assets/choano/icon.png']
assert len([p for p in actual if p.endswith('.avif')]) == 201
assert not [p for p in actual if p.endswith(('.jpg', '.jpeg', '.webp'))]
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
# The title art is drawn in its 1024 x 1536 / 1536 x 1024 design space
# (src/shell.zi); it ships at 75% under the AVIF standard.
for name, size in [('title-portrait.avif', (768, 1152)), ('title-landscape.avif', (1152, 768)),
                   ('fish/title-portrait.avif', (768, 1152)), ('fish/title-landscape.avif', (1152, 768))]:
    with Image.open(ROOT / 'assets/choano' / name) as image:
        assert image.mode == 'RGB' and image.size == size, name

for name, minimum in [('organisms-hd.avif', 1254)]:
    with Image.open(ROOT / 'assets/choano' / name) as image:
        assert min(image.size) >= minimum and image.mode == 'RGBA', name
        first_enemy = mean_visible_color(image, (81, 407, 281, 596))
        largest_enemy = mean_visible_color(image, (371, 972, 619, 1183))
        assert first_enemy[0] > first_enemy[1] + 80 and first_enemy[2] > first_enemy[1] + 50
        assert largest_enemy[1] > largest_enemy[0] + 30 and largest_enemy[2] > largest_enemy[0]

print('Choano local asset and package tests passed: 201 AVIF images, the PNG icon, 6 quiet chimes and the shark loop.')

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
    # 75% of the 1024 px masters.
    image = Image.open(ROOT/f'assets/choano/{name}.avif').convert('RGBA')
    assert image.size == (768,768)
    assert all(image.getpixel(point)[3] == 0 for point in ((0,0),(767,0),(0,767),(767,767)))
    alpha = image.getchannel('A')
    # A white plate inside transparent corners is still a plate: keep every
    # outer edge transparent, with padding, and require a cut-out silhouette.
    left, top, right, bottom = alpha.point(lambda value: 255 if value > 8 else 0).getbbox()
    assert min(left, top, 768-right, 768-bottom) >= 18, name
    histogram = alpha.histogram()
    assert sum(histogram[:9]) > 768*768*.25, name
    assert sum(histogram[200:]) > sum(histogram[9:])*.9, name

for path in (ROOT/'src/locales').glob('*.txt'):
    values = dict(re.findall(r'\[([^\]]+)\]\n([^\n]+)\n---', path.read_text()))
    for key in ('choano_shop', 'choano_settings', *('choano_settings_'+name for name in ('controls','swipe','pad','sound','sound_on','sound_off','done','save_error'))):
        assert values[key] and values[key] in (ROOT/'src/ui_strings.zi').read_text(), (path, key)

for path in (ROOT/'assets/choano/achievement-locales').glob('*.json'):
    text = json.loads(path.read_text())['choano_fish_unlock']
    assert text and text in (ROOT/'src/locales'/f'{path.stem}.txt').read_text()
    assert text in (ROOT/'src/ui_strings.zi').read_text()
for name in ('portrait', 'landscape', 'fish-portrait', 'fish-landscape'):
    with Image.open(ROOT/f'assets/choano/title-clean-{name}.avif') as image:
        assert largest_pink_component(image.convert('RGB'), (0,0,*image.size)) < 1000
