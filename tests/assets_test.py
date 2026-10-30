#!/usr/bin/env python3
"""Verify distributed replacement assets and the independent package contract."""
import hashlib
import json
from pathlib import Path
import struct
import wave

ROOT = Path(__file__).resolve().parents[1]

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
        if path.name == 'turtle-hd.png':
            assert (width, height) == (640, 427) and header[25] == 6, name
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
assert len([p for p in actual if p.endswith('.png')]) == 184
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
    assert {k for a in awards['achievements'] for k in (a['title_key'], a['description_key'])} <= set(json.loads(path.read_text())), path
assert '[dependencies.arcade]' not in (ROOT / 'ziran.toml').read_text()
print('Choano local asset and package tests passed: 184 PNGs, 4 JPEG titles, 6 quiet chimes and the shark loop.')

for name, minimum in [('organisms-hd.png',1254)]:
    with (ROOT / 'assets/choano' / name).open('rb') as handle:
        header=handle.read(33)
    assert min(struct.unpack('>II',header[16:24])) >= minimum, name
