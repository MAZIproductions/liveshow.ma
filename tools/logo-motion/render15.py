#!/usr/bin/env python3
"""LIVESHOW.ma — promo motion 15 s sur fond noir.

Déroulé :
  0–4.5 s   construction du logo (panneau, lettres, reflet, slogan)
  4.5–5.2   le logo monte et rétrécit
  5.2–11.2  3 services, 2 s chacun (texte cinétique + barre orange)
  11.2–12   le logo revient au centre
  12–15     appel à l'action : « RÉSERVEZ VOTRE SHOW » + www.liveshow.ma

  python render15.py --fonts path/to/package/files --out rendu
"""
import argparse
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import render as base
from render import ORANGE, clamp, ease_in_out, ease_out_cubic, seg

DURATION = 15.0
SERVICES = [
    ("01", "BOOKING D'ARTISTES", "Chanteurs · Musiciens · DJ"),
    ("02", "SCÈNE · SON · LUMIÈRE", "Technique professionnelle"),
    ("03", "DÉCORATION & ÉVÉNEMENTS", "Hôtels · Salles · Restaurants"),
]
CTA = "RÉSERVEZ VOTRE SHOW"
URL = "www.liveshow.ma"


def text_img(text, font, color, alpha=1.0, spacing=0):
    if spacing:
        widths = [font.getlength(c) + spacing for c in text]
        w = int(sum(widths)) + 4
    else:
        w = int(font.getlength(text)) + 4
    bb = font.getbbox("ÉÀgy")
    h = bb[3] + 8
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    if spacing:
        x = 2
        for c, cw in zip(text, widths):
            d.text((x, 4), c, font=font, fill=255)
            x += cw
    else:
        d.text((2, 4), text, font=font, fill=255)
    mask = mask.point(lambda v: v * clamp(alpha))
    img = Image.new("RGBA", mask.size, color + (0,))
    img.putalpha(mask)
    return img


def globe_icon(d, color, alpha=1.0, ss=4):
    """Icône globe terrestre (site web), diamètre d px."""
    D = d * ss
    lw = max(2, round(D * 0.07))
    r = (D - lw) / 2
    c = D / 2
    m = Image.new("L", (D, D), 0)
    dr = ImageDraw.Draw(m)
    dr.ellipse((c - r, c - r, c + r, c + r), outline=255, width=lw)            # contour
    dr.ellipse((c - r * 0.45, c - r, c + r * 0.45, c + r), outline=255, width=lw)  # méridien
    dr.line((c - r, c, c + r, c), fill=255, width=lw)                           # équateur
    for k in (-0.55, 0.55):                                                     # parallèles
        y = c + k * r
        half = (r * r - (k * r) ** 2) ** 0.5
        dr.line((c - half, y, c + half, y), fill=255, width=lw)
    m = m.resize((d, d), Image.LANCZOS).point(lambda v: v * clamp(alpha))
    img = Image.new("RGBA", (d, d), color + (0,))
    img.putalpha(m)
    return img


def fit_font(path, text, max_w, size):
    while size > 10:
        f = ImageFont.truetype(str(path), size)
        if f.getlength(text) <= max_w:
            return f
        size -= 2
    return ImageFont.truetype(str(path), size)


class Promo:
    def __init__(self, fonts, size, k):
        self.W, self.H = size
        self.logo = base.Logo(fonts, k)
        self.fonts = fonts
        final, m = base.render_logo(self.logo, 0, final=True)
        self.final_logo, self.m = final, m
        u = min(self.W, self.H) / 1080
        self.u = u
        f900, f600 = fonts / "montserrat-latin-900-normal.woff", fonts / "montserrat-latin-600-normal.woff"
        self.f_num = ImageFont.truetype(str(f900), round(40 * u))
        self.f_srv = {s[1]: fit_font(f900, s[1], self.W * 0.86, round(92 * u)) for s in SERVICES}
        self.f_sub = ImageFont.truetype(str(f600), round(34 * u))
        self.f_cta = fit_font(f900, CTA, self.W * 0.8, round(64 * u))
        self.f_url = ImageFont.truetype(str(f600), round(44 * u))

    def place_logo(self, img, t_build, scale, cy, glow=1.0, final=False):
        lg = self.final_logo if final else base.render_logo(self.logo, t_build)[0]
        if scale != 1:
            lg = lg.resize((max(1, round(lg.width * scale)), max(1, round(lg.height * scale))), Image.BICUBIC)
        x, y = (self.W - lg.width) // 2, round(cy - lg.height / 2)
        if glow > 0:
            g = lg.getchannel("A").filter(ImageFilter.GaussianBlur(45 * self.logo.k * scale)).point(lambda v: v * 0.35 * glow)
            gl = Image.new("RGBA", g.size, ORANGE + (0,))
            gl.putalpha(g)
            img.alpha_composite(gl, (x, y))
        img.alpha_composite(lg, (x, y))
        return y + lg.height - self.m * scale  # bas visuel du logo

    def frame(self, t):
        W, H, u = self.W, self.H, self.u
        img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        cy0 = H / 2 - 20 * u

        # ---------------- logo : position / échelle selon la phase
        up = ease_in_out(seg(t, 4.5, 5.2)) - ease_in_out(seg(t, 11.2, 12.0))
        small = 0.42
        scale = 1 - (1 - small) * up
        cy_top = H * (0.2 if H > W else 0.17)
        cy = cy0 + (cy_top - cy0) * up
        push = 1 + 0.03 * ease_in_out(seg(t, 2.0, 4.5)) * (1 - up) + 0.03 * ease_in_out(seg(t, 12.0, 15.0))
        build_done = t >= 3.0
        if t < 3.0:
            bottom = self.place_logo(img, t, push, cy0, glow=ease_out_cubic(seg(t, 0.3, 1.3)))
        else:
            # second reflet sur le logo final pendant l'appel à l'action
            st = seg(t, 12.3, 13.0)
            if 0 < st < 1:
                lg = base.render_logo(self.logo, 1.75 + st * 0.7)[0]
                lg = lg.resize((round(lg.width * scale * push), round(lg.height * scale * push)), Image.BICUBIC)
                x, y = (W - lg.width) // 2, round(cy - lg.height / 2)
                g = lg.getchannel("A").filter(ImageFilter.GaussianBlur(45 * self.logo.k)).point(lambda v: v * 0.35)
                gl = Image.new("RGBA", g.size, ORANGE + (0,))
                gl.putalpha(g)
                img.alpha_composite(gl, (x, y))
                img.alpha_composite(lg, (x, y))
                bottom = y + lg.height - self.m * scale * push
            else:
                bottom = self.place_logo(img, 0, scale * push, cy, final=build_done)

        # ---------------- slogan de l'intro
        ta = seg(t, 2.3, 3.0) * (1 - seg(t, 4.2, 4.6))
        if ta > 0:
            tag = self.logo.tagline()
            e = ease_out_cubic(seg(t, 2.3, 3.0))
            a = tag.point(lambda v: v * 0.85 * ta)
            ti = Image.new("RGBA", tag.size, (255, 255, 255, 0))
            ti.putalpha(a)
            img.alpha_composite(ti, ((W - tag.width) // 2, round(bottom + 10 * self.logo.k + (1 - e) * 15 * u)))

        # ---------------- services
        for i, (num, title, sub) in enumerate(SERVICES):
            t0 = 5.2 + i * 2.0
            if not (t0 <= t < t0 + 2.0):
                continue
            tin = ease_out_cubic(seg(t, t0, t0 + 0.5))
            tout = ease_in_out(seg(t, t0 + 1.6, t0 + 2.0))
            alpha = tin * (1 - tout)
            dx = (1 - tin) * 120 * u - tout * 120 * u
            cyc = H * 0.55 if H > W else H * 0.58

            ttl = text_img(title, self.f_srv[title], (255, 255, 255), alpha)
            x = (W - ttl.width) // 2 + round(dx)
            y = round(cyc - ttl.height / 2)
            n = text_img(num, self.f_num, ORANGE, alpha)
            img.alpha_composite(n, ((W - n.width) // 2 + round(dx * 1.4), y - n.height - round(18 * u)))
            img.alpha_composite(ttl, (x, y))
            # barre orange qui s'étire
            bar_w = round(ttl.width * 0.5 * ease_out_cubic(seg(t, t0 + 0.15, t0 + 0.7)) * (1 - tout))
            if bar_w > 2:
                bh = round(8 * u)
                bar = Image.new("RGBA", (bar_w, bh), ORANGE + (255,))
                img.alpha_composite(bar, ((W - bar_w) // 2, y + ttl.height + round(14 * u)))
            sa = ease_out_cubic(seg(t, t0 + 0.3, t0 + 0.8)) * (1 - tout)
            s = text_img(sub, self.f_sub, (220, 220, 220), sa)
            img.alpha_composite(s, ((W - s.width) // 2 + round(dx * 0.6), y + ttl.height + round(40 * u)))

        # ---------------- appel à l'action
        ca = ease_out_cubic(seg(t, 12.2, 12.8))
        if ca > 0:
            c = text_img(CTA, self.f_cta, (255, 255, 255), ca)
            yb = round(bottom + 30 * u + (1 - ca) * 20 * u)
            img.alpha_composite(c, ((W - c.width) // 2, yb))
            ua = ease_out_cubic(seg(t, 12.6, 13.2))
            url = text_img(URL, self.f_url, (255, 255, 255), ua, spacing=round(3 * u))
            gd = round(self.f_url.size * 1.1)
            globe = globe_icon(gd, ORANGE, ua)
            gap = round(16 * u)
            gx = (W - (gd + gap + url.width)) // 2
            uy = yb + c.height + round(18 * u)
            # globe centré sur la hauteur des lettres
            xb = self.f_url.getbbox("lw")
            img.alpha_composite(globe, (gx, uy + 4 + (xb[1] + xb[3]) // 2 - gd // 2))
            img.alpha_composite(url, (gx + gd + gap, uy))
        return img.convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", required=True, type=Path)
    ap.add_argument("--out", default="rendu", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, size, k in [("16x9", (1920, 1080), 1.45), ("9x16", (1080, 1920), 1.15)]:
        promo = Promo(args.fonts, size, k)
        tmp = Path(tempfile.mkdtemp())
        for i in range(round(DURATION * base.FPS)):
            promo.frame(i / base.FPS).save(tmp / f"{i:04d}.png")
        out = args.out / f"liveshow_promo_15s_{name}.mp4"
        base.encode(tmp, out)
        shutil.rmtree(tmp)
        print(f"✓ {out.name}")


if __name__ == "__main__":
    main()
