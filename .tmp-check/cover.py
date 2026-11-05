"""Draw the cover for agent-state-machines: a deterministic state graph.

Style follows the existing covers in source/img: near-black navy field, one
violet->cyan gradient ramp, soft glow, generous negative space.
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 900, 675
S = 3  # supersample factor
BG = (11, 8, 33)
VIOLET = (124, 92, 240)
CYAN = (53, 224, 200)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ramp(t):
    return lerp(VIOLET, CYAN, max(0.0, min(1.0, t)))


# ── background: navy field with a soft radial glow behind the graph ──
yy, xx = np.mgrid[0:H * S, 0:W * S]
cx, cy = W * S * 0.5, H * S * 0.52
r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
glow = np.clip(1.0 - r / (W * S * 0.62), 0.0, 1.0) ** 2.4

base = np.zeros((H * S, W * S, 3), dtype=np.float64)
base[:, :, 0] = BG[0]
base[:, :, 1] = BG[1]
base[:, :, 2] = BG[2]

# glow tint: violet on the left, cyan on the right
mix = np.clip((xx / (W * S) - 0.15) / 0.7, 0.0, 1.0)
for i, (a, b) in enumerate(zip(VIOLET, CYAN)):
    tint = a + (b - a) * mix
    base[:, :, i] += glow * tint * 0.22

# faint dot grid for texture
grid = ((xx % (34 * S)) < 2) & ((yy % (34 * S)) < 2)
base[grid] += np.array([26, 22, 58], dtype=np.float64)

bg_img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))

# ── graph geometry ──
NODE_R = 46
Y = 330
nodes = [
    dict(x=112, y=Y, t=0.02),
    dict(x=302, y=Y, t=0.28),
    dict(x=492, y=Y, t=0.55, checkpoint=True),
    dict(x=682, y=Y, t=0.78),
    dict(x=822, y=Y, t=1.0, small=True),
]
edges = [(0, 1), (1, 2), (2, 3), (3, 4)]
loop_from, loop_to = 3, 1  # reject / retry edge

# ── layers: glow (blurred) + crisp ──
glow_layer = Image.new("RGB", (W * S, H * S), (0, 0, 0))
crisp_layer = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow_layer)
cd = ImageDraw.Draw(crisp_layer)


def s(v):
    return int(v * S)


def arrow(p0, p1, color, width=5, head=15, alpha=255, glow_scale=1.0):
    x0, y0 = p0
    x1, y1 = p1
    ang = math.atan2(y1 - y0, x1 - x0)
    # shorten the shaft so it stops at the arrow head
    sx, sy = x1 - math.cos(ang) * head, y1 - math.sin(ang) * head
    gd.line([s(x0), s(y0), s(sx), s(sy)], fill=color, width=s(width) * 3)
    cd.line([(s(x0), s(y0)), (s(sx), s(sy))], fill=color + (alpha,), width=s(width))
    tip = (x1, y1)
    left = (x1 - math.cos(ang - 0.42) * head, y1 - math.sin(ang - 0.42) * head)
    right = (x1 - math.cos(ang + 0.42) * head, y1 - math.sin(ang + 0.42) * head)
    tri = [tip, left, right]
    gd.polygon([(s(px), s(py)) for px, py in tri], fill=color)
    cd.polygon([(s(px), s(py)) for px, py in tri], fill=color + (alpha,))


def disc(x, y, r, color, alpha=255):
    gd.ellipse([s(x - r), s(y - r), s(x + r), s(y + r)], fill=color)
    cd.ellipse([s(x - r), s(y - r), s(x + r), s(y + r)], fill=color + (alpha,))


# edges (drawn first so nodes sit on top)
for a, b in edges:
    na, nb = nodes[a], nodes[b]
    arrow(
        (na["x"] + NODE_R + 6, na["y"]),
        (nb["x"] - NODE_R - 4, nb["y"]),
        ramp((na["t"] + nb["t"]) / 2),
        width=4,
        head=13,
        alpha=200,
    )

# feedback (retry) edge: a bezier that dips below the row
nf, nt = nodes[loop_from], nodes[loop_to]
p0 = (nf["x"], nf["y"] + NODE_R + 4)
p3 = (nt["x"], nt["y"] + NODE_R + 4)
p1 = (nf["x"] - 30, nf["y"] + 128)
p2 = (nt["x"] + 30, nt["y"] + 128)


def bez(t):
    mt = 1 - t
    return (
        mt ** 3 * p0[0] + 3 * mt ** 2 * t * p1[0] + 3 * mt * t ** 2 * p2[0] + t ** 3 * p3[0],
        mt ** 3 * p0[1] + 3 * mt ** 2 * t * p1[1] + 3 * mt * t ** 2 * p2[1] + t ** 3 * p3[1],
    )


pts = [bez(i / 40) for i in range(41)]
gd.line([(s(x), s(y)) for x, y in pts], fill=(150, 130, 235), width=s(4) * 3, joint="curve")
cd.line([(s(x), s(y)) for x, y in pts], fill=(150, 130, 235, 150), width=s(4), joint="curve")
# arrow head pointing up into the node's bottom
head_ang = -math.pi / 2
hx, hy = p3
gd.polygon(
    [(s(hx), s(hy - 14)), (s(hx - 9), s(hy + 2)), (s(hx + 9), s(hy + 2))],
    fill=(150, 130, 235),
)
cd.polygon(
    [(s(hx), s(hy - 14)), (s(hx - 9), s(hy + 2)), (s(hx + 9), s(hy + 2))],
    fill=(150, 130, 235, 170),
)

# nodes
for n in nodes:
    r = NODE_R - 8 if n.get("small") else NODE_R
    color = ramp(n["t"])
    if n.get("checkpoint"):
        # outer ring marks the deterministic boundary
        for rr, a in ((r + 16, 90), (r + 9, 140)):
            gd.ellipse(
                [s(n["x"] - rr), s(n["y"] - rr), s(n["x"] + rr), s(n["y"] + rr)],
                outline=color,
                width=s(2) * 3,
            )
            cd.ellipse(
                [s(n["x"] - rr), s(n["y"] - rr), s(n["x"] + rr), s(n["y"] + rr)],
                outline=color + (a,),
                width=s(2),
            )
    # node body: dark fill with a bright rim, so the glow reads as light not paint
    disc(n["x"], n["y"], r, color)
    cd.ellipse(
        [s(n["x"] - r), s(n["y"] - r), s(n["x"] + r), s(n["y"] + r)],
        fill=(12, 10, 36, 255),
        outline=color + (255,),
        width=s(4),
    )
    gd.ellipse(
        [s(n["x"] - r), s(n["y"] - r), s(n["x"] + r), s(n["y"] + r)],
        outline=color,
        width=s(4) * 2,
    )

# check mark inside the checkpoint node
n = nodes[2]
ck = (n["x"], n["y"])
pts_ck = [(ck[0] - 14, ck[1] + 1), (ck[0] - 4, ck[1] + 12), (ck[0] + 16, ck[1] - 13)]
gd.line([(s(x), s(y)) for x, y in pts_ck], fill=(53, 224, 200), width=s(6) * 3, joint="curve")
cd.line(
    [(s(x), s(y)) for x, y in pts_ck],
    fill=(53, 224, 200, 255),
    width=s(6),
    joint="curve",
)

# ── composite: blurred glow multiplied in, then crisp art ──
glow_blur = glow_layer.filter(ImageFilter.GaussianBlur(radius=26 * S / 3))
glow_np = np.asarray(glow_blur, dtype=np.float64) * 0.85
bg_np = np.asarray(bg_img, dtype=np.float64)
merged = np.clip(bg_np + glow_np, 0, 255).astype(np.uint8)
out = Image.fromarray(merged).convert("RGBA")
out.alpha_composite(crisp_layer)

out = out.convert("RGB").resize((W, H), Image.LANCZOS)

# vignette: pull the corners down so the eye stays on the graph
arr = np.asarray(out, dtype=np.float64)
vy, vx = np.mgrid[0:H, 0:W]
d = np.sqrt(((vx - W / 2) / (W / 2)) ** 2 + ((vy - H / 2) / (H / 2)) ** 2)
vig = 1.0 - 0.28 * np.clip(d - 0.55, 0, None) ** 1.6
arr *= vig[:, :, None]
out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
out.save("source/img/agent-state-machines.jpg", quality=82, optimize=True)
print("ok", out.size)
