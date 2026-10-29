#!/usr/bin/env python3
"""Generate Choano's short, quiet event chimes; no beat, bass or ambience."""
from pathlib import Path
import math
import struct
import wave

ROOT = Path(__file__).resolve().parents[1] / 'assets/choano/audio'
RATE = 22050
EFFECTS = {
    'game-start': ([660, 880], .052, .10),
    'eat': ([740], .048, .075),
    'grow': ([784, 1046], .065, .10),
    'extra-life': ([880, 1109, 1318], .055, .10),
    'lose-life': ([660, 523], .052, .075),
    'game-over': ([523, 440], .075, .075),
}


def synth(notes, length, gain):
    samples = []
    for frequency in notes:
        count = round(length * RATE)
        for index in range(count):
            time = index / RATE
            attack = min(1.0, time / .006)
            release = min(1.0, (length - time) / .009)
            envelope = math.sin(attack * math.pi / 2) ** 2 * release * math.exp(-3.5 * time / length)
            tone = .95 * math.sin(2 * math.pi * frequency * time) + .05 * math.sin(4 * math.pi * frequency * time)
            samples.append(round(32767 * gain * envelope * tone))
        samples.extend([0] * round(.012 * RATE))
    return struct.pack('<' + 'h' * len(samples), *samples)


if __name__ == '__main__':
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, (notes, length, gain) in EFFECTS.items():
        with wave.open(str(ROOT / (name + '.wav')), 'wb') as output:
            output.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
            output.writeframes(synth(notes, length, gain))
    print('Generated six short, quiet Choano event chimes.')
