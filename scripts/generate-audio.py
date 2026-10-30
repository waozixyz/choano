#!/usr/bin/env python3
"""Generate Choano's short, quiet event chimes, and the one loop that plays
only while a shark hunts in Fish mode."""
from pathlib import Path
import math
import random
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


def shark_music():
    """A tense, seamless loop: a driving low pulse, drums and a climbing
    tremolo, 16 beats at 150 BPM."""
    beat = 60 / 150
    count = round(16 * beat * RATE)
    mix = [0.0] * count
    noise = random.Random(7)

    def add(start, length, voice):
        first = round(start * RATE)
        for index in range(min(round(length * RATE), count - first)):
            mix[first + index] += voice(index / RATE, length)

    # Eighth-note bass pulse on D, leaning up a step at the end of each bar.
    pulse = [73.4, 73.4, 73.4, 73.4, 73.4, 73.4, 77.8, 87.3]
    for step in range(32):
        frequency = pulse[step % 8]
        add(step * beat / 2, beat / 2 * .9, lambda t, n, f=frequency: .30 * math.exp(-5 * t / n) * min(1, t / .004)
            * (math.sin(2 * math.pi * f * t) + .45 * math.sin(4 * math.pi * f * t) + .2 * math.sin(6 * math.pi * f * t)))
    # Deep drum on every beat, an accent on the first of each bar.
    for step in range(16):
        weight = .55 if step % 4 == 0 else .35
        add(step * beat, .3, lambda t, n, w=weight: w * math.exp(-14 * t)
            * math.sin(2 * math.pi * (55 + 70 * math.exp(-30 * t)) * t))
    # Hushed ticking sixteenths.
    for step in range(64):
        weight = .08 if step % 2 else .05
        add(step * beat / 4, .04, lambda t, n, w=weight: w * math.exp(-90 * t) * (noise.random() * 2 - 1))
    # A string-like tremolo climbing through the second half.
    for bar, frequency in enumerate([293.7, 311.1, 349.2, 370.0]):
        add((8 + bar * 2) * beat, 2 * beat, lambda t, n, f=frequency: .07 * min(1, t / .05) * min(1, (n - t) / .05)
            * (.6 + .4 * math.sin(2 * math.pi * 12 * t)) * sum(math.sin(2 * math.pi * f * k * t) / k for k in (1, 2, 3)))
    peak = max(abs(value) for value in mix)
    return struct.pack('<' + 'h' * count, *(round(32767 * .3 * value / peak) for value in mix))


if __name__ == '__main__':
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, (notes, length, gain) in EFFECTS.items():
        with wave.open(str(ROOT / (name + '.wav')), 'wb') as output:
            output.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
            output.writeframes(synth(notes, length, gain))
    with wave.open(str(ROOT / 'shark-music.wav'), 'wb') as output:
        output.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        output.writeframes(shark_music())
    print('Generated six short, quiet Choano event chimes and the shark loop.')
