"""Render the Proof demo as a terminal-style animated GIF (no external recorder).

Pure Pillow. Produces assets/demo.gif: a faux-terminal that types a false
completion claim, fires the Stop hook, runs the verifier, and busts the claim.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H = 960, 540
PAD = 28
LINE = 26
BG = (13, 17, 23)        # GitHub dark
BAR = (22, 27, 34)
FG = (201, 209, 217)
DIM = (110, 118, 129)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
YELLOW = (210, 153, 34)
CYAN = (88, 166, 255)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def load_font(size):
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


MONO = load_font(18)
MONO_B = load_font(18)
TITLE = load_font(14)

# (text, color) segments; None text means a blank line.
SCRIPT = [
    ("$ # agent finishes its turn with a confident claim", DIM),
    ('agent> "All done, tests pass."', FG),
    ("", FG),
    ("[proof] Stop hook fired on completion claim", CYAN),
    ("[proof] spawning INDEPENDENT verifier (trusts only real output)", CYAN),
    ("", FG),
    ("FAIL  tests: `python -m pytest -q`", RED),
    ("  E   assert 1 == 2", RED),
    ("  FAILED test_bad.py::test_bad", RED),
    ("", FG),
    ("[proof] re-blocking turn: attempt 2 of 3, receipts attached", YELLOW),
    ('agent> "Fixed for real this time."', FG),
    ("", FG),
    ("PASS  tests: `python -m pytest -q` (1 passed)", GREEN),
    ("", FG),
    ("$ proof stats", FG),
    ("Honesty rate: 50% (2 verified, 1 lie caught)", FG),
    ('Last catch: "All done, tests pass."', RED),
]


def base_frame():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 34], fill=BAR)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([PAD + i * 22 - 6, 11, PAD + i * 22 + 6, 23], fill=c)
    d.text((W // 2 - 60, 9), "proof - live demo", font=TITLE, fill=DIM)
    return img, d


def draw_lines(d, lines, reveal_last=None):
    y = 52
    for idx, (text, color) in enumerate(lines):
        shown = text
        if reveal_last is not None and idx == len(lines) - 1:
            shown = text[:reveal_last]
        d.text((PAD, y), shown, font=MONO, fill=color)
        y += LINE


frames = []
durations = []

# Progressive reveal: add one line at a time; type the claim and command chars.
shown = []
for text, color in SCRIPT:
    if text.startswith('agent>') or text.startswith('$ proof stats'):
        # typewriter effect on these "active" lines
        for n in range(1, len(text) + 1, 2):
            img, d = base_frame()
            draw_lines(d, shown + [(text, color)], reveal_last=n)
            frames.append(img)
            durations.append(28)
        shown.append((text, color))
        img, d = base_frame()
        draw_lines(d, shown)
        frames.append(img)
        durations.append(420)
    else:
        shown.append((text, color))
        img, d = base_frame()
        draw_lines(d, shown)
        frames.append(img)
        # linger longer on the verdict and key lines
        key = text.strip().startswith(("FAIL", "PASS", "Honesty"))
        durations.append(700 if key else 320)

# hold the final frame
img, d = base_frame()
draw_lines(d, shown)
for _ in range(6):
    frames.append(img)
    durations.append(500)

out = Path(__file__).resolve().parent / "demo.gif"
frames[0].save(
    out, save_all=True, append_images=frames[1:], duration=durations,
    loop=0, optimize=True, disposal=2,
)
print(f"wrote {out} ({len(frames)} frames)")
