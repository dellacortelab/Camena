#!/usr/bin/env bash
# Rasterise frontend/icons/icon.svg into the PNGs iOS and the manifest need.
# Headless Chrome's viewport is shorter than its window, so render big and crop.
set -euo pipefail
cd "$(dirname "$0")/../frontend/icons"
CHROME=${CHROME:-google-chrome}
html=$(mktemp --suffix=.html)
printf '<html><body style="margin:0"><img src="file://%s/icon.svg" width="512" height="512"></body></html>' "$PWD" > "$html"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --window-size=700,800 --screenshot="$PWD/_full.png" "file://$html" >/dev/null 2>&1
rm -f "$html"
/usr/bin/python3 - <<'PY'
from PIL import Image
full = Image.open("_full.png").convert("RGB").crop((0, 0, 512, 512))
for size, name in [(512, "icon-512.png"), (192, "icon-192.png"), (180, "apple-touch-icon.png")]:
    full.resize((size, size), Image.LANCZOS).save(name, optimize=True)
PY
rm -f _full.png
ls -l *.png
