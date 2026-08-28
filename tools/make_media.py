"""Generate the site's ambient hero loop, poster, OG image and parallax layers.

Everything here is procedural: no stock footage or third-party assets are used,
so the repository stays self-contained and every byte shipped is reproducible
with `python3 tools/make_media.py`.
"""
import math
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO_DIR = os.path.join(ROOT, "assets", "video")
IMG_DIR = os.path.join(ROOT, "assets", "img")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

W, H = 1280, 720
SW, SH = 320, 180          # low-res simulation buffer, upscaled for soft focus
FPS, SECONDS = 24, 8
FRAMES = FPS * SECONDS

INK = np.array([14, 8, 10], dtype=np.float32)
BROTH = np.array([46, 12, 14], dtype=np.float32)
EMBER = np.array([214, 70, 42], dtype=np.float32)
CHILI = np.array([232, 96, 54], dtype=np.float32)
GOLD = np.array([236, 176, 96], dtype=np.float32)


def base_gradient(w, h, top, bottom):
    ramp = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    col = top[None, None, :] * (1 - ramp) + bottom[None, None, :] * ramp
    return np.repeat(col, w, axis=1)


def steam_field(t):
    """Layered, phase-drifting noise. Every term advances an integer number of
    cycles over one loop, so frame 0 and frame FRAMES are identical."""
    y, x = np.mgrid[0:SH, 0:SW].astype(np.float32)
    u, v = x / SW, y / SH
    field = np.zeros((SH, SW), dtype=np.float32)
    for fx, fy, cycles, amp, phase in (
        (1.0, 1.6, 1, 0.55, 0.0),
        (2.3, 2.9, 2, 0.28, 1.7),
        (4.1, 5.2, 3, 0.13, 3.1),
        (7.7, 9.4, 5, 0.06, 5.5),
    ):
        field += amp * np.sin(2 * math.pi * (fx * u + fy * v + cycles * t) + phase)
    field = (field + 1.0) * 0.5
    rise = np.clip(1.0 - v * 1.35, 0.0, 1.0) ** 1.6      # steam thins as it climbs
    hug = np.clip((v - 0.18) * 1.6, 0.0, 1.0)            # nothing at the very top
    return np.clip(field, 0, 1) ** 2.2 * rise * hug


def ember_glow(t):
    y, x = np.mgrid[0:SH, 0:SW].astype(np.float32)
    u, v = x / SW, y / SH
    breathe = 0.5 + 0.5 * math.sin(2 * math.pi * t)
    r = np.sqrt(((u - 0.5) * 1.15) ** 2 + ((v - 0.92) * 1.75) ** 2)
    return np.clip(1.0 - r / (0.72 + 0.06 * breathe), 0.0, 1.0) ** 2.1


def droplets(t, rng_state=7):
    """Soft out-of-focus chilli-oil beads on closed, looping paths."""
    rng = np.random.default_rng(rng_state)
    y, x = np.mgrid[0:SH, 0:SW].astype(np.float32)
    acc = np.zeros((SH, SW), dtype=np.float32)
    for _ in range(26):
        cx = rng.uniform(-0.05, 1.05)
        cy = rng.uniform(0.25, 1.05)
        ax, ay = rng.uniform(0.01, 0.05), rng.uniform(0.04, 0.12)
        ph = rng.uniform(0, 1)
        rad = rng.uniform(3.0, 11.0)
        gain = rng.uniform(0.10, 0.34)
        px = (cx + ax * math.sin(2 * math.pi * (t + ph))) * SW
        py = (cy - ay * ((t + ph) % 1.0)) * SH
        d2 = (x - px) ** 2 + (y - py) ** 2
        acc += gain * np.exp(-d2 / (2 * rad * rad))
    return np.clip(acc, 0, 1)


def render_frame(i):
    t = i / FRAMES
    small = base_gradient(SW, SH, INK, BROTH)
    small += ember_glow(t)[..., None] * EMBER * 0.85
    small += droplets(t)[..., None] * GOLD * 0.9
    steam = steam_field(t)
    small = small * (1 - steam[..., None] * 0.35) + steam[..., None] * np.array(
        [236, 214, 205], dtype=np.float32
    ) * 0.62
    small = np.clip(small, 0, 255).astype(np.uint8)

    frame = Image.fromarray(small).resize((W, H), Image.LANCZOS)
    frame = frame.filter(ImageFilter.GaussianBlur(1.1))
    arr = np.asarray(frame).astype(np.float32)

    grain = np.random.default_rng(1000 + i).normal(0, 2.4, (H, W, 1)).astype(np.float32)
    arr += grain

    yy = np.linspace(-1, 1, H, dtype=np.float32)[:, None]
    xx = np.linspace(-1, 1, W, dtype=np.float32)[None, :]
    vignette = np.clip(1.12 - 0.42 * (xx ** 2 + yy ** 2), 0.35, 1.0)[..., None]
    arr *= vignette
    return np.clip(arr, 0, 255).astype(np.uint8)


def encode(frames_iter, out, extra):
    cmd = [
        FFMPEG, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
        "-i", "pipe:0",
    ] + extra + [out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames_iter:
        proc.stdin.write(f.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit(f"ffmpeg failed for {out}")


def build_video():
    os.makedirs(VIDEO_DIR, exist_ok=True)
    print("rendering", FRAMES, "frames")
    frames = [render_frame(i) for i in range(FRAMES)]
    Image.fromarray(frames[0]).save(
        os.path.join(VIDEO_DIR, "hero-poster.jpg"), quality=78, optimize=True, progressive=True
    )
    encode(frames, os.path.join(VIDEO_DIR, "hero.mp4"), [
        "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p",
        "-crf", "32", "-preset", "slow", "-g", "48", "-an", "-movflags", "+faststart",
    ])
    encode(frames, os.path.join(VIDEO_DIR, "hero.webm"), [
        "-c:v", "libvpx-vp9", "-crf", "40", "-b:v", "0", "-row-mt", "1",
        "-pix_fmt", "yuv420p", "-an",
    ])


def parallax_layers():
    """Three depth plates. Back = ember field, mid = spice bokeh, front = steam."""
    os.makedirs(IMG_DIR, exist_ok=True)
    w, h = 1600, 900

    back = np.clip(base_gradient(w, h, np.array([18, 9, 12], np.float32), BROTH), 0, 255)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / w, yy / h
    for cx, cy, rad, col, gain in (
        (0.22, 0.72, 0.55, EMBER, 0.85),
        (0.78, 0.30, 0.48, CHILI, 0.55),
        (0.52, 1.02, 0.60, GOLD, 0.35),
    ):
        r = np.sqrt(((u - cx) * 1.1) ** 2 + ((v - cy) * 1.5) ** 2)
        back += (np.clip(1 - r / rad, 0, 1) ** 2.2)[..., None] * col * gain
    Image.fromarray(np.clip(back, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(6)
    ).save(os.path.join(IMG_DIR, "layer-back.webp"), quality=72, method=6)

    mid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(mid)
    rng = np.random.default_rng(11)
    for _ in range(70):
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        rad = rng.uniform(6, 46)
        col = (CHILI, GOLD, EMBER)[int(rng.integers(0, 3))]
        a = int(rng.uniform(28, 120))
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                  fill=(int(col[0]), int(col[1]), int(col[2]), a))
    mid.filter(ImageFilter.GaussianBlur(7)).save(
        os.path.join(IMG_DIR, "layer-mid.webp"), quality=70, method=6
    )

    steam = np.zeros((h, w), dtype=np.float32)
    for fx, fy, amp, ph in ((1.2, 1.9, 0.6, 0.4), (2.7, 3.3, 0.3, 2.0), (5.3, 6.1, 0.12, 4.4)):
        steam += amp * np.sin(2 * math.pi * (fx * u + fy * v) + ph)
    steam = np.clip((steam + 1) * 0.5, 0, 1) ** 2.6 * np.clip(1 - v * 0.9, 0, 1)
    front = np.zeros((h, w, 4), dtype=np.float32)
    front[..., :3] = np.array([255, 236, 226], np.float32)
    front[..., 3] = steam * 140
    Image.fromarray(front.astype(np.uint8)).filter(ImageFilter.GaussianBlur(9)).save(
        os.path.join(IMG_DIR, "layer-front.webp"), quality=68, method=6
    )


def font(size, bold=True):
    name = "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf"
    return ImageFont.truetype(f"/usr/share/fonts/truetype/liberation/{name}", size)


def og_image():
    ow, oh = 1200, 630
    base = np.clip(base_gradient(ow, oh, np.array([16, 8, 11], np.float32), BROTH), 0, 255)
    yy, xx = np.mgrid[0:oh, 0:ow].astype(np.float32)
    u, v = xx / ow, yy / oh
    for cx, cy, rad, col, gain in ((0.80, 0.78, 0.62, EMBER, 1.0), (0.18, 0.20, 0.5, CHILI, 0.45)):
        r = np.sqrt(((u - cx) * 1.05) ** 2 + ((v - cy) * 1.4) ** 2)
        base += (np.clip(1 - r / rad, 0, 1) ** 2.0)[..., None] * col * gain
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(2)
    ).convert("RGB")
    d = ImageDraw.Draw(img)

    d.text((80, 92), "WANGSA MAJU  ·  KUALA LUMPUR", font=font(26), fill=(240, 176, 140))
    d.text((80, 158), "Sup & Api", font=font(104), fill=(255, 249, 245))
    d.text((80, 268), "MALATANG", font=font(104), fill=(240, 122, 74))
    d.text((80, 402), "Pick your bowl. We fire it fresh.", font=font(38, bold=False),
           fill=(236, 214, 206))
    d.rounded_rectangle([80, 486, 470, 556], radius=35, fill=(240, 122, 74))
    d.text((112, 505), "4.5 ★  ·  125 reviews", font=font(30), fill=(28, 10, 8))
    d.text((500, 505), "RM 1–40 per person", font=font(30, bold=False), fill=(232, 206, 198))
    img.save(os.path.join(IMG_DIR, "og.jpg"), quality=82, optimize=True, progressive=True)


if __name__ == "__main__":
    parallax_layers()
    og_image()
    build_video()
    for root, _, files in os.walk(os.path.join(ROOT, "assets")):
        for f in sorted(files):
            p = os.path.join(root, f)
            print(f"{os.path.relpath(p, ROOT):40s} {os.path.getsize(p)/1024:8.1f} KB")
