"""Download the Kokoro voice model (Apache-2.0) at image build time, pinned by checksum."""

import hashlib
import sys
import urllib.request
from pathlib import Path

BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
FILES = {
    "kokoro-v1.0.fp16.onnx": "c1610a859f3bdea01107e73e50100685af38fff88f5cd8e5c56df109ec880204",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}

dest = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/kokoro")
dest.mkdir(parents=True, exist_ok=True)
for name, sha in FILES.items():
    path = dest / name
    urllib.request.urlretrieve(f"{BASE}/{name}", path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != sha:
        sys.exit(f"{name}: checksum {digest} != {sha}")
    print("ok", name, path.stat().st_size)
