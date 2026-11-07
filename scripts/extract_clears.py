#!/usr/bin/env python3
"""
extract_clears.py — turn Endfield CC "Operation Success" screenshots into clears.json entries.

For each screenshot it reads:
  1) risk   — the big "Total Test Criteria" number (OCR)
  2) date   — from the file's EXIF timestamp, falling back to its modified-time
  3) squad  — the four operator portraits, matched against a folder of reference images

Output matches the schema your site already uses:
  "<filename>": { "risk": int, "group": int, "squad": [{"name": ...}], "tag": str,
                  "submitter": str, "date": "YYYY-MM-DD" }

USAGE
  # preview to stdout
  python3 extract_clears.py shots/*.png --refs icons/ops

  # merge into your real data file (keeps existing entries)
  python3 extract_clears.py shots/*.png --refs icons/ops --out data/beta/clears.json \
          --tag -CCEFB --submitter Anon

REFERENCE IMAGES
  --refs points at a folder of one image per operator. Your existing
  icons/ops/<Name>_Banner.webp files work directly: the "_Banner" suffix is
  stripped and underscores become spaces, so "Zhuang_Fangyi_Banner.webp" -> "Zhuang Fangyi".
  Plain "<Name>.png/.webp/.jpg" also work.

MATCHING BACKENDS  (--backend auto|clip|phash)
  clip  : CLIP image embeddings (needs `torch` + `open_clip_torch`). Best accuracy,
          robust when the results-screen art differs from your reference art.
  phash : perceptual hash + colour histogram. No heavy deps, runs anywhere, but
          weaker — fine when characters look distinct, shakier on look-alikes.
  auto  : use clip if it imports, else phash.

  Matches below --min-score (and near-ties) are emitted with a trailing "?" and a
  warning, so you can eyeball and fix them rather than trusting a silent guess.

NOTE
  "group" (Day 1 / Week 1 / ...) is NOT on the results screen, so it can't be read.
  It defaults to 0 (--group to change); set it per entry by hand afterwards.
  Two results-screen layouts are supported and auto-detected per image (--layout to force):
    red    = season 1 (Re-Ignition)     yellow = Indigo onward
  If the game redesigns the screen again, add a new profile to LAYOUTS.
"""

import argparse, json, os, re, sys, pickle
from collections import Counter
from datetime import datetime

import numpy as np
from PIL import Image, ImageOps

# ---- calibration: one profile per results-screen layout (fractions of the image) ----
# x0, y0, x1, y1 for risk; face slots share a y-range.
LAYOUTS = {
    # season 1 (Re-Ignition): red risk panel mid-left, wide portraits. Calibrated on 2560x1440.
    "red": {
        "risk":   (0.205, 0.315, 0.285, 0.405),
        "face_y": (0.135, 0.450),
        "face_x": [(0.523, 0.620), (0.636, 0.733), (0.751, 0.847), (0.864, 0.962)],
    },
    # season 2+ (Indigo): big yellow number top-left, narrow tall cards. Calibrated on 2367x1247.
    "yellow": {
        "risk":   (0.040, 0.140, 0.140, 0.262),
        "face_y": (0.125, 0.440),
        "face_x": [(0.585, 0.660), (0.676, 0.752), (0.768, 0.846), (0.862, 0.943)],
    },
}


def crop_frac(im, box):
    W, H = im.size
    return im.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H)))


def detect_layout(im):
    """The new layout has big yellow digits where its risk box is; the old one has none there."""
    a = np.asarray(crop_frac(im, LAYOUTS["yellow"]["risk"])).astype(int)
    yellow = ((a[..., 0] > 180) & (a[..., 1] > 180) & (a[..., 2] < 110)).mean()
    return "yellow" if yellow > 0.08 else "red"


# ----------------------------------------------------------------------------- #
# risk number (OCR)
# ----------------------------------------------------------------------------- #
def read_risk(im, layout):
    try:
        import pytesseract
    except ImportError:
        sys.exit("pytesseract not installed. `pip install pytesseract` and install the "
                 "tesseract engine (e.g. `apt install tesseract-ocr`).")
    g = crop_frac(im, LAYOUTS[layout]["risk"]).convert("L")

    votes = []
    for thr in (140, 160, 180):
        bw = g.point(lambda p: 255 if p > thr else 0)
        bw = ImageOps.invert(bw)                                  # black digits on white
        bw = bw.resize((bw.width * 4, bw.height * 4), Image.LANCZOS)
        bw = ImageOps.expand(bw, 30, fill=255)
        for psm in (6, 7, 8, 13):
            txt = pytesseract.image_to_string(
                bw, config=f"--psm {psm} -c tessedit_char_whitelist=0123456789")
            digits = "".join(re.findall(r"\d", txt))
            if digits:
                votes.append(digits)
    if not votes:
        return None
    best = Counter(votes).most_common(1)[0][0]
    val = int(best)
    return val if 0 <= val <= 999 else None


# ----------------------------------------------------------------------------- #
# date
# ----------------------------------------------------------------------------- #
def read_date(path):
    try:
        exif = Image.open(path)._getexif() or {}
        for tag in (36867, 306):                                   # DateTimeOriginal, DateTime
            if exif.get(tag):
                return datetime.strptime(exif[tag], "%Y:%m:%d %H:%M:%S").date().isoformat()
    except Exception:
        pass
    return datetime.fromtimestamp(os.path.getmtime(path)).date().isoformat()


# ----------------------------------------------------------------------------- #
# matching backends
# ----------------------------------------------------------------------------- #
class PHashBackend:
    """perceptual hash (structure) + HSV histogram (colour). similarity in [0,1]."""
    name = "phash"

    def __init__(self):
        import imagehash
        self._ih = imagehash

    def descriptor(self, img):
        img = img.convert("RGB")
        ph = self._ih.phash(img, hash_size=16).hash.flatten().astype(np.float32)
        hsv = np.asarray(img.convert("HSV").resize((64, 64)))
        hist, _ = np.histogramdd(
            hsv.reshape(-1, 3), bins=(18, 4, 4),
            range=((0, 256), (0, 256), (0, 256)))
        hist = hist.flatten().astype(np.float32)
        hist /= (hist.sum() + 1e-6)
        return ph, hist

    def similarity(self, a, b):
        pa, ha = a
        pb, hb = b
        ph_sim = 1.0 - np.mean(pa != pb)                            # 1 - normalised hamming
        col_sim = float(np.dot(ha, hb) / ((np.linalg.norm(ha) * np.linalg.norm(hb)) + 1e-6))
        return 0.5 * ph_sim + 0.5 * col_sim


class ClipBackend:
    """CLIP image embeddings; similarity = cosine."""
    name = "clip"

    def __init__(self):
        import torch, open_clip
        self._torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k")
        self.model.eval()

    def descriptor(self, img):
        with self._torch.no_grad():
            t = self.preprocess(img.convert("RGB")).unsqueeze(0)
            f = self.model.encode_image(t)
            f = f / f.norm(dim=-1, keepdim=True)
        return f[0].cpu().numpy().astype(np.float32)

    def similarity(self, a, b):
        return float(np.dot(a, b))


def make_backend(choice):
    if choice in ("auto", "clip"):
        try:
            return ClipBackend()
        except Exception as e:
            if choice == "clip":
                sys.exit(f"CLIP backend unavailable: {e}\nInstall with: pip install torch open_clip_torch")
            print(f"[info] CLIP unavailable ({e.__class__.__name__}); using phash backend.", file=sys.stderr)
    return PHashBackend()


# ----------------------------------------------------------------------------- #
# reference library
# ----------------------------------------------------------------------------- #
def op_name_from_filename(fn):
    stem = os.path.splitext(os.path.basename(fn))[0]
    stem = re.sub(r"_Banner$", "", stem)
    return stem.replace("_", " ").strip()


def load_references(refs_dir, backend):
    exts = (".png", ".webp", ".jpg", ".jpeg")
    files = sorted(f for f in os.listdir(refs_dir) if f.lower().endswith(exts))
    if not files:
        sys.exit(f"No reference images ({', '.join(exts)}) found in {refs_dir}")

    cache_path = os.path.join(refs_dir, f".refcache_{backend.name}.pkl")
    cache = {}
    if os.path.exists(cache_path):
        try:
            cache = pickle.load(open(cache_path, "rb"))
        except Exception:
            cache = {}

    names, descs = [], []
    dirty = False
    for fn in files:
        path = os.path.join(refs_dir, fn)
        key = (fn, os.path.getmtime(path))
        if key not in cache:
            cache[key] = backend.descriptor(Image.open(path))
            dirty = True
        names.append(op_name_from_filename(fn))
        descs.append(cache[key])

    if dirty:
        try:
            pickle.dump({k: cache[k] for k in [(f, os.path.getmtime(os.path.join(refs_dir, f))) for f in files]},
                        open(cache_path, "wb"))
        except Exception:
            pass
    return names, descs


def identify_squad(im, layout, backend, ref_names, ref_descs, min_score):
    L = LAYOUTS[layout]
    squad, uncertain = [], []
    for i, (x0, x1) in enumerate(L["face_x"]):
        crop = crop_frac(im, (x0, L["face_y"][0], x1, L["face_y"][1]))
        d = backend.descriptor(crop)
        scores = sorted(((backend.similarity(d, rd), n) for rd, n in zip(ref_descs, ref_names)),
                        reverse=True)
        best_score, best_name = scores[0]
        margin = best_score - (scores[1][0] if len(scores) > 1 else 0.0)
        if best_score < min_score or margin < 0.02:
            squad.append(best_name + " ?")
            uncertain.append((i + 1, best_name, best_score, margin))
        else:
            squad.append(best_name)
    return squad, uncertain


# ----------------------------------------------------------------------------- #
# main
# ----------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Extract CC clear data from result screenshots.")
    ap.add_argument("shots", nargs="+", help="screenshot file(s)")
    ap.add_argument("--refs", required=True, help="folder of per-operator reference images")
    ap.add_argument("--out", help="merge into this clears.json (default: print to stdout)")
    ap.add_argument("--backend", default="auto", choices=("auto", "clip", "phash"))
    ap.add_argument("--min-score", type=float, default=None,
                    help="confidence floor; below this a match is flagged with '?' "
                         "(default 0.9 for clip, 0.6 for phash)")
    ap.add_argument("--group", type=int, default=0, help="phase group, not detectable (default 0)")
    ap.add_argument("--submitter", default="Anon")
    ap.add_argument("--tag", default="")
    ap.add_argument("--date", help="override date for all shots (YYYY-MM-DD)")
    ap.add_argument("--layout", default="auto", choices=("auto", *LAYOUTS),
                    help="results-screen layout: red = season 1, yellow = Indigo onward (default: detect)")
    args = ap.parse_args()

    backend = make_backend(args.backend)
    min_score = args.min_score if args.min_score is not None else (0.9 if backend.name == "clip" else 0.6)
    ref_names, ref_descs = load_references(args.refs, backend)
    print(f"[info] backend={backend.name}  references={len(ref_names)}  min_score={min_score}", file=sys.stderr)

    entries = {}
    for path in args.shots:
        try:
            im = Image.open(path).convert("RGB")
        except Exception as e:
            print(f"[skip] {path}: {e}", file=sys.stderr)
            continue

        W, H = im.size
        if not 1.70 <= W / H <= 2.00:
            print(f"[warn] {os.path.basename(path)} is {W}x{H} (unusual aspect); crops may be off.", file=sys.stderr)

        layout = args.layout if args.layout != "auto" else detect_layout(im)
        risk = read_risk(im, layout)
        date = args.date or read_date(path)
        squad, uncertain = identify_squad(im, layout, backend, ref_names, ref_descs, min_score)

        key = os.path.basename(path)
        entry = {
            "risk": risk if risk is not None else 0,
            "group": args.group,
            "squad": [{"name": n} for n in squad],
            "submitter": args.submitter,
            "date": date,
        }
        if args.tag:
            entry["tag"] = args.tag
        entries[key] = entry

        flags = []
        if risk is None:
            flags.append("RISK UNREAD")
        if uncertain:
            flags.append("squad: " + ", ".join(f"slot{n}={nm}({s:.2f},Δ{m:.2f})" for n, nm, s, m in uncertain))
        print(f"[done] {key}  layout={layout}  risk={risk}  date={date}  squad={squad}"
              + (("  <-- " + "; ".join(flags)) if flags else ""), file=sys.stderr)

    if args.out:
        existing = {}
        if os.path.exists(args.out):
            try:
                existing = json.load(open(args.out, encoding="utf-8"))
            except Exception as e:
                sys.exit(f"Could not read existing {args.out}: {e}")
        existing.update(entries)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent="\t")
            f.write("\n")
        print(f"[write] merged {len(entries)} entr{'y' if len(entries)==1 else 'ies'} into {args.out}", file=sys.stderr)
    else:
        print(json.dumps(entries, ensure_ascii=False, indent="\t"))


if __name__ == "__main__":
    main()
