"""Quick inspection of the render manifest to see publish_ready / score state."""
import json
import sys
from pathlib import Path

content_id = sys.argv[1] if len(sys.argv) > 1 else "quality_smoke_browser_use"
root = Path(__file__).resolve().parents[1] / "output" / content_id
manifest_path = root / "render_manifest.v6.json"

if not manifest_path.exists():
    print(f"manifest not found: {manifest_path}")
    sys.exit(1)

data = json.loads(manifest_path.read_text(encoding="utf-8"))
print("top-level keys:", list(data.keys()))
print()

candidates = ["video_quality_report", "quality_report", "quality"]
for c in candidates:
    if c in data:
        print(f"## {c}")
        print(json.dumps(data[c], ensure_ascii=False, indent=2))
        break
else:
    print("no quality_report found, dumping full manifest:")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
