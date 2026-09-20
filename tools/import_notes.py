"""Copy an episode's notes JSON from the LAPod notes pipeline into content/episodes/.

    python tools/import_notes.py 033        # one episode
    python tools/import_notes.py            # every NNN/docs/notes_NNN.json that exists

Then: python build.py, commit, push.
"""
import shutil
import sys
from pathlib import Path

VODS = Path("G:/My Drive/LAVods")
DEST = Path(__file__).resolve().parents[1] / "content" / "episodes"

nums = sys.argv[1:] or sorted(p.name for p in VODS.iterdir() if p.name.isdigit())
copied = 0
for n in nums:
    n = n.zfill(3)
    src = VODS / n / "docs" / f"notes_{n}.json"
    if src.exists():
        shutil.copy2(src, DEST / src.name)
        print("imported", src.name)
        copied += 1
    elif sys.argv[1:]:
        print("missing", src)
print(f"{copied} file(s)")
