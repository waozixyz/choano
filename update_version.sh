#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
version=$(python3 - "$root" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
from release import release_version
print(release_version((root / 'CHANGELOG.md').read_text()))
PY
)
temporary="$root/VERSION.tmp"
printf '%s\n' "$version" > "$temporary"
mv -f "$temporary" "$root/VERSION"
