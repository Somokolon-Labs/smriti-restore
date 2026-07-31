"""Verify face detection on real photographs, not drawn shapes."""

import io
import os
import sys
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for candidate in (ROOT / ".env", ROOT.parent / "nakshi-studio" / ".env"):
    if candidate.exists():
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from worker.imaging import detect_faces  # noqa: E402

KEY = os.getenv("PEXELS_ACCESS_KEY", "")
if not KEY:
    sys.exit("PEXELS_ACCESS_KEY needed to fetch test portraits")

out = ROOT / "outputs" / "face-check"
out.mkdir(parents=True, exist_ok=True)


def search(query: str, count: int) -> list[str]:
    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(query)}&per_page={count}"
    # Pexels rejects urllib's default User-Agent with a bare 403.
    req = urllib.request.Request(
        url, headers={"Authorization": KEY, "User-Agent": "smriti-restore/0.1 (+face-check)"}
    )
    import json

    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.loads(r.read().decode())
    return [p["src"]["large"] for p in data.get("photos", [])]


import urllib.parse  # noqa: E402

lines = []
total_faces = 0
tested = 0

for query in ("portrait face person", "group of people faces"):
    for index, url in enumerate(search(query, 3)):
        try:
            image_req = urllib.request.Request(
                url, headers={"User-Agent": "smriti-restore/0.1 (+face-check)"}
            )
            with urllib.request.urlopen(image_req, timeout=60) as r:
                image = Image.open(io.BytesIO(r.read())).convert("RGB")
        except Exception as exc:
            lines.append(f"  fetch failed: {exc}")
            continue

        image.thumbnail((900, 900), Image.LANCZOS)
        faces = detect_faces(image, min_size=48)
        tested += 1
        total_faces += len(faces)

        marked = image.copy()
        from PIL import ImageDraw

        draw = ImageDraw.Draw(marked)
        for x, y, w, h in faces:
            draw.rectangle([x, y, x + w, y + h], outline=(255, 200, 30), width=4)
        name = f"{query.split()[0]}-{index}.jpg"
        marked.save(out / name, quality=88)
        lines.append(f"  {name:24} {image.width}x{image.height}  faces={len(faces)}")

print(f"tested {tested} real photographs, {total_faces} faces detected total")
print("\n".join(lines))
(out / "report.txt").write_text(
    f"tested={tested} faces={total_faces}\n" + "\n".join(lines) + "\n", encoding="utf-8"
)
