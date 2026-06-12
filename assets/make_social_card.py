"""Render the GitHub social preview card (1280x640) for the Proof repo.

Pure Pillow. Output: assets/social-card.png. Upload via repo Settings >
Social preview.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 640
BG = (13, 17, 23)
BAR = (22, 27, 34)
FG = (201, 209, 217)
DIM = (110, 118, 129)
RED = (248, 81, 73)
GREEN = (63, 185, 80)
CYAN = (88, 166, 255)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
MONO_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
]


def load(cands, size):
    for p in cands:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


TITLE = load(FONT_CANDIDATES, 84)
SUB = load(FONT_CANDIDATES, 34)
MONO = load(MONO_CANDIDATES, 30)
MONO_SM = load(MONO_CANDIDATES, 24)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# Title block (left)
d.text((70, 110), "Proof", font=TITLE, fill=FG)
d.text((70, 225), "Your coding agent can no longer", font=SUB, fill=DIM)
d.text((70, 270), 'say "done" without receipts.', font=SUB, fill=DIM)

# Mini terminal (right/bottom)
TX, TY, TW, TH = 70, 360, 1140, 210
d.rounded_rectangle([TX, TY, TX + TW, TY + TH], radius=14, fill=BAR,
                    outline=(48, 54, 61), width=2)
for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
    d.ellipse([TX + 22 + i * 26, TY + 16, TX + 38 + i * 26, TY + 32], fill=c)

y = TY + 52
d.text((TX + 28, y), 'agent> "All done, tests pass."', font=MONO, fill=FG)
y += 44
d.text((TX + 28, y), "[proof] Stop hook fired, spawning independent verifier",
       font=MONO_SM, fill=CYAN)
y += 40
d.text((TX + 28, y), "FAIL  tests: `python -m pytest -q`  (1 failed)",
       font=MONO, fill=RED)
y += 44
d.text((TX + 28, y), "caught.", font=MONO, fill=RED)

# Footer
d.text((W - 460, 50), "github.com/EricFinland/proof", font=MONO_SM, fill=DIM)

out = Path(__file__).resolve().parent / "social-card.png"
img.save(out, optimize=True)
print(f"wrote {out}")
