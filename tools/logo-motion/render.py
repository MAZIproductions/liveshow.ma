#!/usr/bin/env python3
"""LIVESHOW.ma — logo motion promo sur fond noir.

Reconstruit le logo en vectoriel (panneau orange + texte Montserrat Black),
puis rend :
  - liveshow_logo_motion_16x9.mp4   1920x1080, 30 fps
  - liveshow_logo_motion_9x16.mp4   1080x1920, 30 fps (Reels / TikTok)
  - liveshow_logo_black_4k.png      logo final sur fond noir, 3840x2160
  - liveshow_logo_transparent.png   logo seul, fond transparent

Police : Montserrat (npm pack @fontsource/montserrat), fichiers .woff
dans --fonts (latin-900-normal et latin-600-normal).

  python render.py --fonts path/to/package/files --out rendu
"""
import argparse
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ORANGE = (243, 132, 17)
WHITE = (255, 255, 255)
TEXT = "LIVESHOW.ma"
TAGLINE = "BOOKING D'ARTISTES  ·  ÉVÉNEMENTS  ·  SCÈNE"
FPS = 30
DURATION = 5.0

# géométrie relevée sur le logo original (unités du logo d'origine)
PANEL = [(165, 213), (406, 240), (406, 478), (165, 511)]
TEXT_X, CAP_TOP, TEXT_SIZE = 170, 325, 95
LOGO_BOX = (160, 205, 925, 520)  # zone utile du logo


# ---------------------------------------------------------------- easing
def clamp(x):
    return max(0.0, min(1.0, x))


def ease_out_cubic(t):
    return 1 - (1 - clamp(t)) ** 3


def ease_out_back(t, s=1.9):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def ease_in_out(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def seg(t, a, b):
    return clamp((t - a) / (b - a))


# ---------------------------------------------------------------- assets
class Logo:
    def __init__(self, fonts, k):
        """k = pixels par unité du logo d'origine."""
        self.k = k
        self.font = ImageFont.truetype(str(fonts / "montserrat-latin-900-normal.woff"), round(TEXT_SIZE * k))
        self.tag_font = ImageFont.truetype(str(fonts / "montserrat-latin-600-normal.woff"), round(19 * k))
        x0, y0, x1, y1 = LOGO_BOX
        self.ox, self.oy = x0, y0
        self.W, self.H = round((x1 - x0) * k), round((y1 - y0) * k)
        self.panel = self._panel()
        self.letters = self._letters()

    def p(self, x, y):
        return ((x - self.ox) * self.k, (y - self.oy) * self.k)

    def _panel(self):
        ss = 4  # supersampling
        k = self.k * ss
        img = Image.new("L", (self.W * ss, self.H * ss), 0)
        ImageDraw.Draw(img).polygon([((x - self.ox) * k, (y - self.oy) * k) for x, y in PANEL], fill=255)
        # coins arrondis : flou puis seuil
        img = img.filter(ImageFilter.GaussianBlur(9 * k)).point(lambda v: 255 if v > 128 else 0)
        img = img.resize((self.W, self.H), Image.LANCZOS)
        layer = Image.new("RGBA", img.size, ORANGE + (0,))
        layer.putalpha(img)
        return layer

    def _letters(self):
        f = self.font
        top_off = f.getbbox("L")[1]
        y = (CAP_TOP - self.oy) * self.k - top_off
        out = []
        for i, ch in enumerate(TEXT):
            x = (TEXT_X - self.ox) * self.k + f.getlength(TEXT[:i])
            bb = f.getbbox(ch)
            pad = round(12 * self.k)
            w, h = bb[2] + 2 * pad, bb[3] + 2 * pad
            glyph = Image.new("L", (w, h), 0)
            ImageDraw.Draw(glyph).text((pad, pad), ch, font=f, fill=255)
            shadow = glyph.filter(ImageFilter.GaussianBlur(4 * self.k))
            out.append({"glyph": glyph, "shadow": shadow, "x": x - pad, "y": y - pad})
        return out

    def tagline(self):
        f = self.tag_font
        bb = f.getbbox(TAGLINE)
        img = Image.new("L", (bb[2] + 4, bb[3] + 4), 0)
        ImageDraw.Draw(img).text((2, 2), TAGLINE, font=f, fill=255)
        return img


# ---------------------------------------------------------------- frame
def render_logo(logo, t, final=False):
    """Logo (RGBA, taille logo.W x logo.H + marges) à l'instant t."""
    m = round(80 * logo.k)
    canvas = Image.new("RGBA", (logo.W + 2 * m, logo.H + 2 * m), (0, 0, 0, 0))

    # 1. panneau orange : pop avec rebond + légère rotation
    pt = 1.0 if final else seg(t, 0.0, 0.7)
    if pt > 0:
        s = ease_out_back(pt)
        rot = (1 - ease_out_cubic(pt)) * -12
        cx = ((165 + 406) / 2 - logo.ox) * logo.k + m
        cy = ((213 + 511) / 2 - logo.oy) * logo.k + m
        panel_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        panel_layer.alpha_composite(logo.panel, (m, m))
        if abs(s - 1) > 1e-4 or rot:
            # mise à l'échelle + rotation autour du centre du panneau
            s = max(s, 0.01)
            th = math.radians(rot)
            a, b = math.cos(th) / s, math.sin(th) / s
            d, e = -math.sin(th) / s, math.cos(th) / s
            panel_layer = panel_layer.transform(
                canvas.size, Image.AFFINE,
                (a, b, cx - a * cx - b * cy, d, e, cy - d * cx - e * cy), resample=Image.BICUBIC)
        a = np.array(panel_layer)
        a[..., 3] = (a[..., 3] * clamp(pt * 3)).astype(np.uint8)
        canvas.alpha_composite(Image.fromarray(a))

    # 2. lettres : chute en cascade
    for i, L in enumerate(logo.letters):
        lt = 1.0 if final else seg(t, 0.45 + i * 0.06, 0.95 + i * 0.06)
        if lt <= 0:
            continue
        e = ease_out_cubic(lt)
        dy = (1 - e) * -60 * logo.k
        alpha = clamp(lt * 1.6)
        x, y = round(L["x"] + m), round(L["y"] + m + dy)
        sh = L["shadow"].point(lambda v: v * 0.55 * alpha)
        canvas.alpha_composite(Image.merge("RGBA", (*[sh.point(lambda v: 0)] * 3, sh)), (x + round(5 * logo.k), y + round(5 * logo.k)))
        g = L["glyph"].point(lambda v: v * alpha)
        canvas.alpha_composite(Image.merge("RGBA", (g.point(lambda v: 255), g.point(lambda v: 255), g.point(lambda v: 255), g)), (x, y))

    # 3. reflet lumineux qui balaie le logo
    st = seg(t, 1.75, 2.45)
    if 0 < st < 1 and not final:
        w, h = canvas.size
        xs = np.arange(w)[None, :] + np.arange(h)[:, None] * 0.45
        center = -0.2 * w + ease_in_out(st) * 1.6 * w
        band = np.exp(-((xs - center) / (60 * logo.k)) ** 2) * 0.75
        rgba = np.array(canvas).astype(np.float32)
        a = rgba[..., 3:4] / 255
        rgba[..., :3] = rgba[..., :3] + (255 - rgba[..., :3]) * band[..., None] * a
        canvas = Image.fromarray(rgba.clip(0, 255).astype(np.uint8))
    return canvas, m


def frame(logo, t, size, final=False):
    W, H = size
    img = Image.new("RGBA", size, (0, 0, 0, 255))
    lg, m = render_logo(logo, t, final)

    # halo orange discret derrière le panneau
    gt = 1.0 if final else ease_out_cubic(seg(t, 0.3, 1.3))
    push = 1.0 if final else 1 + 0.035 * ease_in_out(seg(t, 2.0, DURATION))
    if push != 1:
        lg = lg.resize((round(lg.width * push), round(lg.height * push)), Image.BICUBIC)
    x, y = (W - lg.width) // 2, (H - lg.height) // 2 - round(20 * logo.k)
    if gt > 0:
        glow = lg.getchannel("A").filter(ImageFilter.GaussianBlur(45 * logo.k)).point(lambda v: v * 0.35 * gt)
        img.alpha_composite(Image.merge("RGBA", (glow.point(lambda v: ORANGE[0]), glow.point(lambda v: ORANGE[1]),
                                                 glow.point(lambda v: ORANGE[2]), glow)), (x, y))
    img.alpha_composite(lg, (x, y))

    # slogan
    tt = 1.0 if final else seg(t, 2.3, 3.0)
    if tt > 0:
        tag = logo.tagline()
        e = ease_out_cubic(tt)
        a = tag.point(lambda v: v * 0.85 * e)
        ty = y + lg.height - m + round(10 * logo.k) + round((1 - e) * 15 * logo.k)
        img.alpha_composite(Image.merge("RGBA", (a.point(lambda v: 255),) * 3 + (a,)), ((W - tag.width) // 2, ty))
    return img.convert("RGB")


# ---------------------------------------------------------------- export
def encode(frames_dir, out):
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", str(frames_dir / "%04d.png"), "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", required=True, type=Path)
    ap.add_argument("--out", default="rendu", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    formats = {"16x9": ((1920, 1080), 1.45), "9x16": ((1080, 1920), 1.15)}
    for name, (size, k) in formats.items():
        logo = Logo(args.fonts, k)
        tmp = Path(tempfile.mkdtemp())
        n = round(DURATION * FPS)
        for i in range(n):
            frame(logo, i / FPS, size).save(tmp / f"{i:04d}.png")
        encode(tmp, args.out / f"liveshow_logo_motion_{name}.mp4")
        shutil.rmtree(tmp)
        print(f"✓ liveshow_logo_motion_{name}.mp4")

    logo = Logo(args.fonts, 2.9)
    frame(logo, DURATION, (3840, 2160), final=True).save(args.out / "liveshow_logo_black_4k.png")
    lg, m = render_logo(logo, 0, final=True)
    lg.crop(lg.getbbox()).save(args.out / "liveshow_logo_transparent.png")
    print("✓ PNG")


if __name__ == "__main__":
    main()
