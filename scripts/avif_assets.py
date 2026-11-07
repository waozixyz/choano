#!/usr/bin/env python3
"""Export Choano's shipped art as AVIF from local masters.

Settings follow Jungle's tools/avif_codec.py and tools/image_exports.py:
libavif's avifenc (AVIFENC), 8-bit, full range, speed 6, one thread.

- scaled: pictures of 512 px or more that hosts draw into a layout rectangle
  are Lanczos-downscaled to 75%, then q35 (opaque YUV420; transparent YUV444
  with q90 alpha). Code keeps their design sizes (src/shell.zi).
- cutout: source-rectangle sheets, accessory overlays and pictures under
  512 px keep their pixels: q70 YUV444 color with exact alpha.
- scene: opaque pictures under 512 px keep their size at q35 YUV420, or
  lossless when that is smaller.

Masters (the former PNG/JPEG files) stay in the ignored backup/image-masters/.
`assets/choano/icon.png` stays PNG: it is the install, favicon, Windows and
Android icon source, read by tools that do not decode AVIF.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets/choano'
MASTERS = ROOT / 'backup/image-masters'
AVIFENC = os.environ.get('AVIFENC', 'avifenc')
SPEED = 6
SCALE = 0.75
# Shipped PNG exceptions, each with the host that needs it.
PNG_EXCEPTIONS = {'icon.png': 'install, favicon, Windows and Android icon source'}
# Hosts draw these into layout rectangles, so they take the 75% standard.
SCALED = {'title-landscape', 'title-portrait', 'fish/title-landscape', 'fish/title-portrait',
          'title-clean-landscape', 'title-clean-portrait', 'title-clean-fish-landscape',
          'title-clean-fish-portrait', 'title-logo', 'gear', 'lock', 'shop', 'fish/sea'}


def has_alpha(picture):
    return picture.mode == 'RGBA' and picture.getchannel('A').getextrema()[0] < 255


def role(name):
    """The export role of shipped NAME (relative to assets/choano, no suffix)."""
    return 'scaled' if name in SCALED else 'pixels'


def encode(picture, destination, *, quality=35, alpha_quality=100, lossless=False):
    """One avifenc run with Jungle's settings; transparent pictures use YUV444."""
    alpha = has_alpha(picture)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='avif-', dir=destination.parent) as folder:
        source = Path(folder) / 'input.png'
        output = Path(folder) / 'output.avif'
        (picture if alpha else picture.convert('RGB')).save(source, 'PNG')
        command = [AVIFENC, '--jobs', '1', '--speed', str(SPEED), '--depth', '8', '--range', 'full',
                   '--qalpha', str(alpha_quality if alpha else 100)]
        if lossless:
            command += ['--lossless', '--yuv', '444', '--cicp', '1/13/0']
        else:
            command += ['--qcolor', str(quality), '--yuv', '444' if alpha else '420', '--cicp', '1/13/6']
        subprocess.run(command + [str(source), str(output)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        output.replace(destination)


def export(master, destination, name):
    with Image.open(master) as original:
        picture = ImageOps.exif_transpose(original).convert('RGBA')
    alpha = has_alpha(picture)
    if role(name) == 'scaled':
        size = max(1, round(picture.width * SCALE)), max(1, round(picture.height * SCALE))
        picture = picture.resize(size, Image.Resampling.LANCZOS)
        encode(picture, destination, quality=35, alpha_quality=90)
    elif alpha:
        encode(picture, destination, quality=70)
    else:
        encode(picture, destination, quality=35)
        smaller = destination.with_suffix('.exact.avif')
        try:
            encode(picture, smaller, lossless=True)
            if smaller.stat().st_size < destination.stat().st_size:
                smaller.replace(destination)
        finally:
            smaller.unlink(missing_ok=True)
    with Image.open(destination) as decoded:
        decoded.load()
        assert decoded.format == 'AVIF' and decoded.size == picture.size, destination
        if alpha and role(name) != 'scaled':
            # Cut-outs keep every alpha value exactly.
            assert decoded.convert('RGBA').getchannel('A').tobytes() == picture.getchannel('A').tobytes(), destination
    return picture.size, alpha


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('names', nargs='*', help='shipped names to re-export (default: every master)')
    options = parser.parse_args()
    # First run: shipped PNG/JPEG art becomes the local masters.
    for path in sorted(ASSETS.rglob('*')):
        relative = path.relative_to(ASSETS)
        if path.suffix.lower() in ('.png', '.jpg') and relative.as_posix() not in PNG_EXCEPTIONS:
            master = MASTERS / relative
            master.parent.mkdir(parents=True, exist_ok=True)
            if not master.exists():
                shutil.copy2(path, master)
            elif master.read_bytes() != path.read_bytes():
                sys.exit(f'avif assets: {relative} differs from its master; move one aside first')
    masters = sorted(p for p in MASTERS.rglob('*') if p.suffix.lower() in ('.png', '.jpg'))
    if options.names:
        masters = [p for p in masters if p.relative_to(MASTERS).with_suffix('').as_posix() in options.names]
    before = after = 0
    for master in masters:
        relative = master.relative_to(MASTERS)
        name = relative.with_suffix('').as_posix()
        destination = ASSETS / relative.with_suffix('.avif')
        size, alpha = export(master, destination, name)
        (ASSETS / relative).unlink(missing_ok=True)
        before += master.stat().st_size
        after += destination.stat().st_size
        print(f'{relative.with_suffix(".avif")} {size[0]}x{size[1]} {role(name)}{" alpha" if alpha else ""} '
              f'{master.stat().st_size} -> {destination.stat().st_size}')
    print(f'{len(masters)} images: {before} -> {after} bytes')


if __name__ == '__main__':
    main()
