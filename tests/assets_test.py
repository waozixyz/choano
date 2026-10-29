#!/usr/bin/env python3
"""Verify distributed replacement assets and the independent package contract."""
import hashlib
import json
from pathlib import Path
import struct
import wave

ROOT = Path(__file__).resolve().parents[1]
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
        if path.name.startswith('blob-'):
            assert (width, height) == (39, 39) and header[25] == 6, name
    elif path.suffix == '.wav':
        with wave.open(str(path)) as sound:
            assert sound.getcomptype() == 'NONE' and sound.getnchannels() == 1
            assert sound.getframerate() == 22050 and sound.getsampwidth() == 2
            assert .04 <= sound.getnframes()/sound.getframerate() < .25
            raw = sound.readframes(sound.getnframes())
            assert len(set(raw)) > 1, name
            samples = struct.unpack('<' + 'h' * (len(raw)//2), raw)
            assert max(map(abs, samples)) <= .12 * 32767, 'Effect too loud: ' + name
assert len([p for p in actual if p.endswith('.png')]) == 185
assert len([p for p in actual if p.endswith('.wav')]) == 6
assert not (ROOT / 'assets/original').exists()
for p in (ROOT / 'assets').rglob('*'):
    assert p.suffix.lower() not in {'.exe', '.dll', '.gam', '.gif'}, p
catalog = json.loads((ROOT / 'catalog.json').read_text())
assert catalog['id'] == 'xyz.waozi.choano' and catalog['module_api'] == 2
assert (ROOT / catalog['source']).is_file() and (ROOT / catalog['preview']).is_file()
assert '[dependencies.arcade]' not in (ROOT / 'ziran.toml').read_text()
print('Choano local asset and package tests passed: 185 PNGs, 6 quiet WAVs.')

for name, minimum in [('organisms-hd.png',1254),('title-landscape.png',1024),('title-portrait.png',1024)]:
    with (ROOT / 'assets/choano' / name).open('rb') as handle:
        header=handle.read(33)
    assert min(struct.unpack('>II',header[16:24])) >= minimum, name
