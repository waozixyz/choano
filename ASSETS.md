# Choano assets

Choano ships 178 replacement PNG images and 11 replacement PCM WAV sounds.
The artwork was generated and assembled for Choano; the sound effects were
synthesized for Choano. No original Moeboid artwork, audio, executable, DLL,
or extracted game payload is distributed in this repository or its builds.

The replacement art preserves the native implementation's animation frames,
dimensions and dish geometry. The dish is 500 × 420, centered at (245, 209)
with radius 208. Audio preserves the channel, rate, width and frame contracts
used during the native implementation. `assets/manifest.json` records the
exact replacement-file digests. `python3 tests/assets_test.py` verifies them.

Choano is an independent reimplementation inspired by the gameplay of
Moeboid. Moeboid and ZapSpot names identify the historical source only;
Choano does not claim affiliation with its creators.
