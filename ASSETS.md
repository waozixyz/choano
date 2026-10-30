# Choano assets

Choano ships 184 replacement PNG images, 4 compressed JPEG title images, and
7 replacement PCM WAV sounds.
The artwork was generated and assembled for Choano; the sound effects were
synthesized for Choano. No original Moeboid artwork, audio, executable, DLL,
or extracted game payload is distributed in this repository or its builds.

The replacement art preserves the native implementation's animation frames,
dimensions and dish geometry. The dish is 500 × 420, centered at (245, 209)
with radius 208. Audio uses short mono 22050 Hz PCM chimes synthesized by
`scripts/generate-audio.py`; there is no ambient beat or spawn thump. `assets/manifest.json` records the
exact replacement-file digests. `python3 tests/assets_test.py` verifies them.

Choano is an independent reimplementation inspired by the gameplay of
Moeboid. Moeboid and ZapSpot names identify the historical source only;
Choano does not claim affiliation with its creators.

The title screen has newly generated landscape and portrait artwork. Prompts
and source roles are recorded in `assets/ARTWORK.json`. Organisms render
from the full 1254 × 1254 generated atlas through per-frame source rectangles,
with mirroring handled by the standard Kryon Image mesh. Their game-space
sizes and collision rules remain unchanged. Fish mode's seahorse, lobster and
starfish come from one generated sheet, `assets/choano/fish/sea-animals-hd.png`,
recorded with its prompt in `assets/ARTWORK.json`. The visiting sea turtle,
`assets/choano/fish/turtle-hd.png`, is a 640 × 427 RGBA encoding of its
generated 1536 × 1024 picture, also recorded there with its prompt.
