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
            assert sound.getframerate() == (8000 if path.name == 'game-start.wav' else 11025) and sound.getnframes() > 0
            assert len(set(sound.readframes(sound.getnframes()))) > 1, name
assert len([p for p in actual if p.endswith('.png')]) == 178
assert len([p for p in actual if p.endswith('.wav')]) == 11
assert not (ROOT / 'assets/original').exists()
for p in (ROOT / 'assets').rglob('*'):
    assert p.suffix.lower() not in {'.exe', '.dll', '.gam', '.gif'}, p
catalog = json.loads((ROOT / 'catalog.json').read_text())
assert catalog['id'] == 'xyz.waozi.choano' and catalog['module_api'] == 2
assert (ROOT / catalog['source']).is_file() and (ROOT / catalog['preview']).is_file()
assert '[dependencies.arcade]' not in (ROOT / 'ziran.toml').read_text()
print('Choano local asset and package tests passed: 178 PNGs, 11 WAVs.')
