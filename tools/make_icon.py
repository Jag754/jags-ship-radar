"""Write the app icon (.ico) used by the exe and installer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ship_radar.tray import make_icon  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icon.ico")
out.parent.mkdir(parents=True, exist_ok=True)
make_icon(True, 256).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
