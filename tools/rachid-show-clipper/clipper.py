#!/usr/bin/env python3
"""Rachid Show clipper — retrouve automatiquement tes passages dans les épisodes.

Pipeline :
  1. Télécharge les épisodes YouTube (URLs, playlist ou recherche).
  2. Scanne chaque vidéo (1 image / seconde par défaut) et reconnaît ton visage
     à partir d'une ou plusieurs photos de référence.
  3. Regroupe les détections en passages (segments).
  4. Exporte :
       - segments.csv            timecodes + lien YouTube direct (&t=)
       - clips/*.mp4             chaque passage découpé (16:9, et 9:16 avec --vertical)
       - montage.mp4             tous les passages bout à bout
       - premiere_sequence.xml   séquence à importer dans Premiere Pro
                                 (Fichier > Importer) avec les rushs originaux

Exemple :
  python clipper.py --ref ref/ --search "Rachid Show 2M" --max 30 --vertical
  python clipper.py --ref moi.jpg --url https://www.youtube.com/playlist?list=XXXX
  python clipper.py --ref ref/ --local mes_videos/
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import cv2
import face_recognition as fr
import imageio_ffmpeg
import numpy as np

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


# ---------------------------------------------------------------- référence
def load_reference(paths):
    files = []
    for p in paths:
        p = Path(p)
        files += sorted(f for f in p.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}) if p.is_dir() else [p]
    encodings = []
    for f in files:
        img = fr.load_image_file(str(f))
        locs = fr.face_locations(img, number_of_times_to_upsample=1)
        if not locs:
            print(f"  ! aucun visage trouvé dans {f.name}, ignorée")
            continue
        # plus grand visage de la photo = toi
        big = max(locs, key=lambda l: (l[2] - l[0]) * (l[1] - l[3]))
        encodings.append(fr.face_encodings(img, [big])[0])
        print(f"  ✓ référence : {f.name}")
    if not encodings:
        sys.exit("Aucune photo de référence exploitable.")
    return encodings


# ---------------------------------------------------------------- téléchargement
def download(urls, search, max_results, dest, max_height):
    import yt_dlp

    dest.mkdir(parents=True, exist_ok=True)
    targets = list(urls)
    if search:
        targets.append(f"ytsearch{max_results}:{search}")
    opts = {
        "format": f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/b[height<={max_height}]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(dest / "%(id)s.%(ext)s"),
        "ffmpeg_location": FFMPEG,
        "ignoreerrors": True,
        "noplaylist": False,
        "writeinfojson": True,
        "quiet": False,
    }
    if search and max_results:
        opts["playlistend"] = max_results
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download(targets)


def video_meta(path):
    info = path.with_suffix(".info.json")
    if info.exists():
        d = json.loads(info.read_text())
        return d.get("title", path.stem), d.get("webpage_url", "")
    return path.stem, ""


# ---------------------------------------------------------------- scan
def scan(path, refs, step, tolerance, scan_width, upsample, cache_dir):
    cache = cache_dir / f"{path.stem}.scan.json"
    key = {"step": step, "tolerance": tolerance, "scan_width": scan_width, "upsample": upsample}
    if cache.exists():
        d = json.loads(cache.read_text())
        if d.get("key") == key:
            return d["fps"], d["duration"], d["width"], d["height"], d["hits"]

    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = nframes / fps
    every = max(1, round(step * fps))
    scale = min(1.0, scan_width / W) if W else 1.0

    hits = []  # [t, distance, centre_x (0-1)]
    idx = 0
    while True:
        if not cap.grab():
            break
        if idx % every == 0:
            ok, frame = cap.retrieve()
            if ok:
                small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                locs = fr.face_locations(rgb, number_of_times_to_upsample=upsample)
                if locs:
                    encs = fr.face_encodings(rgb, locs)
                    for loc, enc in zip(locs, encs):
                        d = float(np.min(fr.face_distance(refs, enc)))
                        if d <= tolerance:
                            cx = (loc[1] + loc[3]) / 2 / rgb.shape[1]
                            hits.append([idx / fps, d, cx])
                            break
            if idx % round(60 * fps) < every:
                print(f"    {idx / fps / 60:5.1f} / {duration / 60:.1f} min  — {len(hits)} détections", end="\r")
        idx += 1
    cap.release()
    print()
    cache.write_text(json.dumps({"key": key, "fps": fps, "duration": duration, "width": W, "height": H, "hits": hits}))
    return fps, duration, W, H, hits


def to_segments(hits, gap, pad, min_len, min_hits, duration):
    segs = []
    for t, d, cx in hits:
        if segs and t - segs[-1]["end"] <= gap:
            s = segs[-1]
            s["end"] = t
            s["hits"] += 1
            s["dist"].append(d)
            s["cx"].append(cx)
        else:
            segs.append({"start": t, "end": t, "hits": 1, "dist": [d], "cx": [cx]})
    out = []
    for s in segs:
        if s["hits"] < min_hits:
            continue
        start, end = max(0.0, s["start"] - pad), min(duration, s["end"] + pad)
        if end - start < min_len:
            continue
        out.append({
            "start": start,
            "end": end,
            "hits": s["hits"],
            "confidence": round(1 - float(np.mean(s["dist"])), 3),
            "cx": float(np.median(s["cx"])),
        })
    return out


# ---------------------------------------------------------------- export
def tc(seconds):
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def cut(src, seg, dst, vertical=False, W=1920, H=1080):
    if vertical:
        # recadrage 9:16 centré sur ton visage
        cw = int(H * 9 / 16) // 2 * 2
        x = int(min(max(seg["cx"] * W - cw / 2, 0), W - cw))
        vf = f"crop={cw}:{H}:{x}:0,scale=1080:1920"
    else:
        vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1"
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error",
        "-ss", f"{seg['start']:.3f}", "-i", str(src), "-t", f"{seg['end'] - seg['start']:.3f}",
        "-vf", vf, "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        str(dst),
    ], check=True)


def concat(clips, dst):
    lst = dst.with_suffix(".txt")
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(dst)], check=True)
    lst.unlink()


def premiere_xml(items, dst):
    """Séquence Final Cut Pro 7 XML (xmeml) — importable dans Premiere Pro."""
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    seq_fps = round(items[0][1])
    video, audio, t = [], [], 0
    files_done = set()
    for i, (path, fps, dur, W, H, seg, title) in enumerate(items):
        rate = round(fps)
        fid = f"file-{path.stem}"
        a, b = round(seg["start"] * rate), round(seg["end"] * rate)
        start, length = t, round((seg["end"] - seg["start"]) * seq_fps)
        if fid in files_done:
            fdef = f'<file id="{fid}"/>'
        else:
            files_done.add(fid)
            fdef = (f'<file id="{fid}"><name>{esc(path.name)}</name>'
                    f'<pathurl>file://{quote(str(path.resolve()))}</pathurl>'
                    f'<rate><timebase>{rate}</timebase></rate><duration>{round(dur * rate)}</duration>'
                    f'<media><video><samplecharacteristics><width>{W}</width><height>{H}</height>'
                    f'</samplecharacteristics></video><audio><channelcount>2</channelcount></audio></media></file>')
        common = (f'<name>{esc(title)} #{i + 1}</name><rate><timebase>{rate}</timebase></rate>'
                  f'<start>{start}</start><end>{start + length}</end><in>{a}</in><out>{b}</out>')
        video.append(f'<clipitem id="v{i}">{common}{fdef}</clipitem>')
        audio.append(f'<clipitem id="a{i}">{common}<file id="{fid}"/>'
                     f'<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack></clipitem>')
        t = start + length
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence>'
           f'<name>Rachid Show — mes passages</name><duration>{t}</duration>'
           f'<rate><timebase>{seq_fps}</timebase></rate><media>'
           f'<video><format><samplecharacteristics><width>1920</width><height>1080</height></samplecharacteristics></format>'
           f'<track>{"".join(video)}</track></video>'
           f'<audio><track>{"".join(audio)}</track></audio>'
           '</media></sequence></xmeml>\n')
    dst.write_text(xml)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", nargs="+", required=True, help="photo(s) de toi ou dossier de photos")
    ap.add_argument("--url", nargs="*", default=[], help="URLs YouTube (vidéos, playlist, chaîne)")
    ap.add_argument("--search", help='recherche YouTube, ex. "Rachid Show 2M"')
    ap.add_argument("--max", type=int, default=20, help="nb max de résultats de recherche")
    ap.add_argument("--local", help="dossier de vidéos déjà téléchargées (pas de téléchargement)")
    ap.add_argument("--out", default="rendu", help="dossier de sortie")
    ap.add_argument("--max-height", type=int, default=1080)
    ap.add_argument("--step", type=float, default=1.0, help="secondes entre deux images analysées")
    ap.add_argument("--tolerance", type=float, default=0.5, help="plus bas = plus strict (0.45-0.6)")
    ap.add_argument("--scan-width", type=int, default=960, help="largeur d'analyse (plus grand = visages lointains)")
    ap.add_argument("--upsample", type=int, default=1, help="2 pour détecter les visages très petits (plus lent)")
    ap.add_argument("--gap", type=float, default=6.0, help="fusionne 2 détections séparées de moins de X s")
    ap.add_argument("--pad", type=float, default=1.5, help="marge ajoutée avant/après chaque passage")
    ap.add_argument("--min-len", type=float, default=3.0, help="durée minimale d'un passage")
    ap.add_argument("--min-hits", type=int, default=2, help="nb minimal de détections par passage")
    ap.add_argument("--vertical", action="store_true", help="exporte aussi des clips 9:16 (Reels/TikTok)")
    ap.add_argument("--no-render", action="store_true", help="seulement CSV + XML Premiere, pas de mp4")
    args = ap.parse_args()

    out = Path(args.out)
    videos_dir = Path(args.local) if args.local else out / "episodes"
    (out / "cache").mkdir(parents=True, exist_ok=True)

    print("① Photos de référence")
    refs = load_reference(args.ref)

    if not args.local:
        print("② Téléchargement des épisodes")
        download(args.url, args.search, args.max, videos_dir, args.max_height)

    videos = sorted(p for p in videos_dir.iterdir() if p.suffix.lower() in VIDEO_EXT)
    if not videos:
        sys.exit("Aucune vidéo trouvée.")

    print(f"③ Analyse de {len(videos)} vidéo(s)")
    items = []
    for v in videos:
        title, url = video_meta(v)
        print(f"  ▶ {title}")
        fps, dur, W, H, hits = scan(v, refs, args.step, args.tolerance, args.scan_width, args.upsample, out / "cache")
        segs = to_segments(hits, args.gap, args.pad, args.min_len, args.min_hits, dur)
        print(f"    → {len(segs)} passage(s), {sum(s['end'] - s['start'] for s in segs):.0f} s au total")
        items += [(v, fps, dur, W, H, s, title) for s in segs]

    if not items:
        sys.exit("Aucun passage trouvé. Essaie --tolerance 0.55, --upsample 2 ou ajoute d'autres photos de référence.")

    print("④ Export")
    with open(out / "segments.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["#", "episode", "debut", "fin", "duree_s", "confiance", "lien_youtube", "fichier"])
        for i, (v, fps, dur, W, H, s, title) in enumerate(items, 1):
            _, url = video_meta(v)
            link = f"{url}{'&' if '?' in url else '?'}t={int(s['start'])}s" if url else ""
            w.writerow([i, title, tc(s["start"]), tc(s["end"]), round(s["end"] - s["start"], 1),
                        s["confidence"], link, v.name])
    premiere_xml(items, out / "premiere_sequence.xml")
    print(f"  ✓ {out / 'segments.csv'}\n  ✓ {out / 'premiere_sequence.xml'}")

    if args.no_render:
        return
    clips_dir = out / "clips"
    clips_dir.mkdir(exist_ok=True)
    clips = []
    for i, (v, fps, dur, W, H, s, title) in enumerate(items, 1):
        slug = re.sub(r"[^\w-]+", "_", title)[:40].strip("_")
        dst = clips_dir / f"{i:03d}_{slug}_{int(s['start'])}s.mp4"
        cut(v, s, dst, W=W, H=H)
        clips.append(dst)
        if args.vertical:
            vdir = out / "clips_9x16"
            vdir.mkdir(exist_ok=True)
            cut(v, s, vdir / dst.name, vertical=True, W=W, H=H)
        print(f"  ✓ clip {i}/{len(items)}", end="\r")
    print()
    concat(clips, out / "montage.mp4")
    print(f"  ✓ {out / 'montage.mp4'}\nTerminé : {len(items)} passages.")


if __name__ == "__main__":
    main()
