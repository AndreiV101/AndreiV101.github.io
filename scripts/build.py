#!/usr/bin/env python3
"""Fetch public Google Sheet + Drive images, resize, emit static HTML."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "scripts" / "_cache"

DRIVE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{10,}$")
USER_AGENT = (
    "Mozilla/5.0 (compatible; DriveToWebsite/1.0; +https://github.com/)"
)

DEFAULT_CONFIG = {
    "spreadsheet_id": "",
    "sheet_gid": "0",
    "settings_gid": "",
    "site_title": "Photo Journal",
    "site_tagline": "Stories and pictures from the field",
    "image_max_width": 1400,
    "image_quality": 82,
    "output_dir": "site",
}

SETTINGS_KEYS = (
    "site_title",
    "site_tagline",
    "image_max_width",
    "image_quality",
)


def load_config() -> dict:
    """Defaults + Settings tab / env. No config.json."""
    cfg = dict(DEFAULT_CONFIG)

    # Spreadsheet id/gid first so Settings-tab CSV fetch can run before env brand overrides
    for key in ("spreadsheet_id", "sheet_gid", "settings_gid", "output_dir"):
        env_key = key.upper()
        if os.environ.get(env_key):
            cfg[key] = os.environ[env_key]

    sheet_url = os.environ.get("SPREADSHEET_URL", "")
    if sheet_url:
        sid = extract_sheet_id(sheet_url)
        if sid:
            cfg["spreadsheet_id"] = sid
        gid = extract_gid(sheet_url)
        if gid is not None:
            cfg["sheet_gid"] = gid

    apply_settings_dict(cfg, parse_settings_json(os.environ.get("SETTINGS_JSON", "")))

    settings_csv_path = os.environ.get("SETTINGS_CSV_PATH", "").strip()
    if settings_csv_path:
        path = Path(settings_csv_path)
        if path.is_file():
            print(f"Loading settings CSV: {path}")
            apply_settings_dict(
                cfg, parse_settings_rows(parse_csv_text(path.read_text(encoding="utf-8-sig")))
            )
        else:
            print(f"WARN SETTINGS_CSV_PATH missing: {path}", file=sys.stderr)
    elif not os.environ.get("SETTINGS_JSON", "").strip():
        fetch_settings_for_spreadsheet(cfg)

    # Brand / image env overrides win (Actions vars)
    for key in ("site_title", "site_tagline"):
        if os.environ.get(key.upper()):
            cfg[key] = os.environ[key.upper()]
    if os.environ.get("IMAGE_MAX_WIDTH"):
        cfg["image_max_width"] = int(os.environ["IMAGE_MAX_WIDTH"])
    if os.environ.get("IMAGE_QUALITY"):
        cfg["image_quality"] = int(os.environ["IMAGE_QUALITY"])

    return cfg


def parse_settings_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"WARN invalid SETTINGS_JSON: {exc}", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        print("WARN SETTINGS_JSON must be a JSON object", file=sys.stderr)
        return {}
    return {normalize_key(str(k)): v for k, v in data.items()}


def parse_settings_rows(rows: list[dict]) -> dict:
    """Parse Settings tab rows: key/value (or setting/value) columns."""
    out: dict = {}
    for row in rows:
        key = (
            row.get("key")
            or row.get("setting")
            or row.get("name")
            or row.get("property")
            or ""
        )
        if not key and len(row) >= 2:
            # Fallback: first two column values when headers are odd
            vals = list(row.values())
            key, val = vals[0], vals[1]
        else:
            val = row.get("value")
            if val is None:
                val = row.get("val")
        key = normalize_key(str(key or ""))
        if not key:
            continue
        if val is None:
            continue
        out[key] = val if not isinstance(val, str) else val.strip()
    return out


def apply_settings_dict(cfg: dict, settings: dict) -> None:
    if not settings:
        return
    for key in SETTINGS_KEYS:
        if key not in settings or settings[key] in ("", None):
            continue
        if key in ("image_max_width", "image_quality"):
            try:
                cfg[key] = int(settings[key])
            except (TypeError, ValueError):
                print(f"WARN invalid {key}={settings[key]!r}", file=sys.stderr)
        else:
            cfg[key] = str(settings[key])


def fetch_settings_for_spreadsheet(cfg: dict) -> None:
    """Optional public CSV of Settings tab when settings_gid is known."""
    spreadsheet_id = cfg.get("spreadsheet_id") or ""
    settings_gid = str(cfg.get("settings_gid") or "").strip()
    if not spreadsheet_id or not settings_gid:
        return
    if spreadsheet_id.startswith("REPLACE_"):
        return
    url = sheet_csv_url(spreadsheet_id, settings_gid)
    try:
        rows = fetch_csv(url)
        apply_settings_dict(cfg, parse_settings_rows(rows))
        print(f"Loaded {len(rows)} settings rows from sheet gid={settings_gid}")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN could not fetch settings tab: {exc}", file=sys.stderr)


def extract_sheet_id(value: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", value)
    return m.group(1) if m else None


def extract_gid(value: str) -> str | None:
    m = re.search(r"[?#&]gid=([0-9]+)", value)
    return m.group(1) if m else None


def extract_drive_id(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    if DRIVE_ID_RE.match(value):
        return value

    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"/open\?id=([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
        r"/uc\?.*?id=([a-zA-Z0-9_-]+)",
        r"/thumbnail\?.*?id=([a-zA-Z0-9_-]+)",
        r"lh[0-9]\.googleusercontent\.com/d/([a-zA-Z0-9_-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, value)
        if m:
            return m.group(1)

    parsed = urlparse(value)
    qs = parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        return qs["id"][0]
    return None


def sheet_csv_url(spreadsheet_id: str, gid: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        f"/export?format=csv&gid={gid}"
    )


def parse_csv_text(text: str, source: str = "sheet") -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise RuntimeError(f"{source} CSV has no header row.")
    rows = []
    for raw in reader:
        row = {normalize_key(k): (v or "").strip() for k, v in raw.items() if k}
        if any(row.values()):
            rows.append(row)
    return rows


def fetch_csv(url: str) -> list[dict]:
    print(f"Fetching sheet: {url}")
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    # Google sometimes returns HTML login/access page
    ctype = r.headers.get("content-type", "")
    text = r.content.decode("utf-8-sig", errors="replace")
    if "text/html" in ctype and "<html" in text.lower()[:500]:
        raise RuntimeError(
            "Sheet export returned HTML. Share the spreadsheet as "
            "'Anyone with the link can view' (or Publish to web)."
        )
    return parse_csv_text(text, source="exported sheet")


def load_csv_from_path(path: Path) -> list[dict]:
    print(f"Loading sheet from dispatch payload: {path}")
    text = path.read_text(encoding="utf-8-sig")
    return parse_csv_text(text, source="dispatch sheet")


def normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (key or "").strip().lower()).strip("_")


def is_published(row: dict) -> bool:
    val = row.get("published", "yes").strip().lower()
    return val in ("", "yes", "y", "true", "1", "published")


def download_drive_file(file_id: str) -> bytes:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{file_id}.bin"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        print(f"  cache hit: {file_id}")
        return cache_path.read_bytes()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    urls = [
        f"https://drive.google.com/uc?export=download&id={file_id}",
        f"https://drive.google.com/thumbnail?id={file_id}&sz=w2000",
        f"https://lh3.googleusercontent.com/d/{file_id}=w2000",
    ]

    data = None
    last_err = None
    for url in urls:
        try:
            print(f"  downloading: {url}")
            r = session.get(url, timeout=120, allow_redirects=True)
            # Handle virus-scan confirm interstitial for larger files
            if "download_warning" in r.text[:2000] or "confirm=" in r.url:
                for k, v in r.cookies.items():
                    if k.startswith("download_warning"):
                        confirm = v
                        break
                else:
                    m = re.search(r"confirm=([0-9A-Za-z_]+)", r.text)
                    confirm = m.group(1) if m else "t"
                r = session.get(
                    f"https://drive.google.com/uc?export=download&id={file_id}&confirm={confirm}",
                    timeout=120,
                )
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "text/html" in ctype and len(r.content) < 50_000:
                last_err = f"HTML response from {url}"
                continue
            if len(r.content) < 100:
                last_err = f"Tiny response from {url}"
                continue
            data = r.content
            break
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            continue

    if data is None:
        raise RuntimeError(f"Could not download Drive file {file_id}: {last_err}")

    cache_path.write_bytes(data)
    return data


def resize_image(data: bytes, max_width: int, quality: int) -> tuple[bytes, str]:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if img.width > max_width:
        ratio = max_width / float(img.width)
        new_size = (max_width, max(1, int(img.height * ratio)))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue(), "jpg"


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "item"


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_html(cfg: dict, items: list[dict], built_at: str) -> str:
    title = html_escape(cfg["site_title"])
    tagline = html_escape(cfg["site_tagline"])
    featured = next((i for i in items if i.get("section") == "featured"), None)
    if featured is None and items:
        featured = items[0]
    gallery = [i for i in items if i is not featured]

    hero_block = ""
    if featured and featured.get("image_src"):
        hero_alt = html_escape(featured.get("title") or tagline)
        hero_title = html_escape(featured.get("title") or "")
        hero_block = f"""
  <section class="hero-banner" aria-label="Featured artwork">
    <div class="hero-banner__media">
      <img src="{html_escape(featured['image_src'])}" alt="{hero_alt}">
    </div>
    <div class="hero-banner__copy">
      <h1>{tagline}</h1>
      {"<p class='hero-banner__caption'>" + hero_title + "</p>" if hero_title else ""}
    </div>
  </section>"""

    intro_block = ""
    if featured and featured.get("description"):
        intro_block = f"""
  <section class="intro" aria-label="Introduction">
    <p>{html_escape(featured.get('description') or '')}</p>
  </section>"""

    cards = []
    for item in gallery:
        if not item.get("image_src"):
            continue
        item_title = html_escape(item.get("title") or "")
        item_desc = html_escape(item.get("description") or "")
        item_src = html_escape(item["image_src"])
        desc_html = f"<p>{item_desc}</p>" if item_desc else ""
        cards.append(
            f"""
      <article class="artwork">
        <button type="button" class="artwork__thumb" data-lightbox="{item_src}" data-caption="{item_title}" aria-label="View {item_title}">
          <img src="{item_src}" alt="{item_title}" loading="lazy" width="1400" height="933">
        </button>
        <div class="artwork__meta">
          <h2>{item_title}</h2>
          {desc_html}
        </div>
      </article>"""
        )

    gallery_html = "\n".join(cards) if cards else (
        '<p class="portfolio__empty">No gallery items yet.</p>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{tagline}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400&family=Source+Sans+3:wght@300;400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="assets/site.css">
</head>
<body>
  <header class="site-header">
    <a class="site-header__brand" href="#">{title}</a>
    <nav class="site-header__nav">
      <a href="#gallery">Gallery</a>
    </nav>
  </header>
  {hero_block}
  {intro_block}
  <main id="gallery" class="portfolio">
    <div class="portfolio__grid">
      {gallery_html}
    </div>
  </main>
  <footer class="site-footer">
    <p>{title}</p>
  </footer>
  <div class="lightbox" id="lightbox" hidden aria-hidden="true">
    <button type="button" class="lightbox__close" aria-label="Close">&times;</button>
    <figure class="lightbox__figure">
      <img class="lightbox__img" src="" alt="">
      <figcaption class="lightbox__caption"></figcaption>
    </figure>
  </div>
  <script src="assets/site.js"></script>
</body>
</html>
"""


SITE_CSS = """:root {
  --ink: #1a1a1a;
  --muted: #666;
  --line: #e8e6e3;
  --paper: #faf9f7;
  --white: #fff;
  --display: "Cormorant Garamond", Georgia, serif;
  --body: "Source Sans 3", system-ui, sans-serif;
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  color: var(--ink);
  font-family: var(--body);
  font-weight: 400;
  background: var(--white);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}

.site-header {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.9rem clamp(1.25rem, 4vw, 2.5rem);
  background: var(--white);
  border-bottom: 1px solid var(--line);
}
.site-header__brand {
  font-family: var(--display);
  font-size: clamp(1.15rem, 2.5vw, 1.45rem);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  text-decoration: none;
  color: var(--ink);
}
.site-header__nav a {
  font-size: 0.8rem;
  font-weight: 500;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  text-decoration: none;
  color: var(--muted);
  transition: color 0.2s ease;
}
.site-header__nav a:hover { color: var(--ink); }

.hero-banner {
  position: relative;
  min-height: clamp(320px, 65vh, 620px);
  display: flex;
  align-items: flex-end;
  overflow: hidden;
  background: var(--paper);
}
.hero-banner__media {
  position: absolute;
  inset: 0;
}
.hero-banner__media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.hero-banner__copy {
  position: relative;
  z-index: 1;
  width: 100%;
  padding: clamp(2rem, 5vw, 3.5rem) clamp(1.25rem, 4vw, 2.5rem);
  background: linear-gradient(180deg, transparent 0%, rgba(255,255,255,0.75) 40%, rgba(255,255,255,0.95) 100%);
}
.hero-banner__copy h1 {
  font-family: var(--display);
  font-size: clamp(1.75rem, 4vw, 2.75rem);
  font-weight: 400;
  line-height: 1.2;
  margin: 0;
  max-width: 36rem;
}
.hero-banner__caption {
  margin: 0.5rem 0 0;
  font-size: 0.8rem;
  font-weight: 500;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}

.intro {
  max-width: 42rem;
  margin: 0 auto;
  padding: clamp(2rem, 5vw, 3rem) clamp(1.25rem, 4vw, 2.5rem) 0;
  text-align: center;
}
.intro p {
  font-family: var(--display);
  font-size: clamp(1.2rem, 2.5vw, 1.55rem);
  font-weight: 400;
  font-style: italic;
  line-height: 1.55;
  margin: 0;
  color: var(--muted);
}

.portfolio {
  padding: clamp(2rem, 5vw, 3.5rem) clamp(1rem, 3vw, 2rem) clamp(2.5rem, 5vw, 4rem);
  background: var(--paper);
}
.portfolio__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: clamp(1.5rem, 3vw, 2.25rem);
  max-width: 1280px;
  margin: 0 auto;
}
@media (min-width: 900px) {
  .portfolio__grid {
    grid-template-columns: repeat(4, 1fr);
  }
}
@media (min-width: 600px) and (max-width: 899px) {
  .portfolio__grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.artwork {
  opacity: 0;
  transform: translateY(12px);
  transition: opacity 0.5s ease, transform 0.5s ease;
}
.artwork.is-in {
  opacity: 1;
  transform: none;
}
.artwork__thumb {
  display: block;
  width: 100%;
  padding: 0;
  border: none;
  background: none;
  cursor: pointer;
  overflow: hidden;
}
.artwork__thumb img {
  width: 100%;
  height: auto;
  display: block;
  vertical-align: middle;
  transition: transform 0.35s ease, opacity 0.35s ease;
}
.artwork__thumb:hover img {
  transform: scale(1.03);
  opacity: 0.92;
}
.artwork__meta {
  padding: 0.75rem 0.15rem 0;
}
.artwork__meta h2 {
  font-family: var(--display);
  font-size: 1.05rem;
  font-weight: 600;
  margin: 0 0 0.25rem;
  line-height: 1.3;
}
.artwork__meta p {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.45;
  color: var(--muted);
}

.portfolio__empty {
  grid-column: 1 / -1;
  text-align: center;
  color: var(--muted);
  padding: 3rem 1rem;
  font-size: 0.95rem;
}

.site-footer {
  padding: 2rem clamp(1.25rem, 4vw, 2.5rem);
  text-align: center;
  border-top: 1px solid var(--line);
  background: var(--white);
}
.site-footer p {
  margin: 0;
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}

.lightbox {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  background: rgba(0, 0, 0, 0.88);
}
.lightbox[hidden] { display: none; }
.lightbox__close {
  position: absolute;
  top: 1rem;
  right: 1.25rem;
  border: none;
  background: none;
  color: #fff;
  font-size: 2rem;
  line-height: 1;
  cursor: pointer;
  opacity: 0.8;
  padding: 0.25rem;
}
.lightbox__close:hover { opacity: 1; }
.lightbox__figure {
  max-width: min(1100px, 100%);
  max-height: 90vh;
  margin: 0;
}
.lightbox__img {
  max-width: 100%;
  max-height: 82vh;
  width: auto;
  height: auto;
  display: block;
  margin: 0 auto;
}
.lightbox__caption {
  margin-top: 0.75rem;
  text-align: center;
  font-family: var(--display);
  font-size: 1.1rem;
  color: #fff;
  opacity: 0.9;
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .artwork { opacity: 1; transform: none; transition: none; }
  .artwork__thumb img { transition: none; }
}
"""

SITE_JS = """const artworks = document.querySelectorAll('.artwork');
if ('IntersectionObserver' in window) {
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        e.target.classList.add('is-in');
        io.unobserve(e.target);
      }
    }
  }, { threshold: 0.08, rootMargin: '0px 0px -20px 0px' });
  artworks.forEach((el) => io.observe(el));
} else {
  artworks.forEach((el) => el.classList.add('is-in'));
}

const lightbox = document.getElementById('lightbox');
const lightboxImg = lightbox && lightbox.querySelector('.lightbox__img');
const lightboxCaption = lightbox && lightbox.querySelector('.lightbox__caption');
const lightboxClose = lightbox && lightbox.querySelector('.lightbox__close');

function openLightbox(src, caption) {
  if (!lightbox || !lightboxImg) return;
  lightboxImg.src = src;
  lightboxImg.alt = caption || '';
  if (lightboxCaption) lightboxCaption.textContent = caption || '';
  lightbox.hidden = false;
  lightbox.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
}

function closeLightbox() {
  if (!lightbox) return;
  lightbox.hidden = true;
  lightbox.setAttribute('aria-hidden', 'true');
  if (lightboxImg) lightboxImg.src = '';
  document.body.style.overflow = '';
}

document.querySelectorAll('[data-lightbox]').forEach((btn) => {
  btn.addEventListener('click', () => {
    openLightbox(btn.dataset.lightbox, btn.dataset.caption || '');
  });
});

if (lightboxClose) lightboxClose.addEventListener('click', closeLightbox);
if (lightbox) {
  lightbox.addEventListener('click', (e) => {
    if (e.target === lightbox) closeLightbox();
  });
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && lightbox && !lightbox.hidden) closeLightbox();
});
"""


def write_assets(out: Path) -> None:
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    (assets / "site.css").write_text(SITE_CSS, encoding="utf-8")
    (assets / "site.js").write_text(SITE_JS, encoding="utf-8")


def process_rows(cfg: dict, rows: list[dict]) -> list[dict]:
    out_dir = ROOT / cfg["output_dir"]
    img_dir = out_dir / "images"
    if img_dir.exists():
        shutil.rmtree(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)

    published = [r for r in rows if is_published(r)]

    def sort_key(r: dict):
        try:
            order = int(r.get("order") or 9999)
        except ValueError:
            order = 9999
        return (r.get("section") != "featured", order, r.get("title") or "")

    published.sort(key=sort_key)

    items = []
    for idx, row in enumerate(published):
        title = row.get("title") or row.get("name") or f"Item {idx + 1}"
        description = row.get("description") or row.get("caption") or row.get("body") or ""
        section = (row.get("section") or "gallery").lower()
        image_field = (
            row.get("image")
            or row.get("image_id")
            or row.get("drive_id")
            or row.get("photo")
            or ""
        )
        file_id = extract_drive_id(image_field)
        image_src = ""

        if file_id:
            try:
                raw = download_drive_file(file_id)
                resized, ext = resize_image(
                    raw, int(cfg["image_max_width"]), int(cfg["image_quality"])
                )
                digest = hashlib.sha1(file_id.encode()).hexdigest()[:8]
                filename = f"{slugify(title)}-{digest}.{ext}"
                path = img_dir / filename
                path.write_bytes(resized)
                image_src = f"images/{filename}"
                print(f"  saved {path} ({len(resized)} bytes)")
            except Exception as exc:  # noqa: BLE001
                print(f"  WARN image failed for '{title}': {exc}", file=sys.stderr)
        elif image_field.startswith("http"):
            # Non-Drive URL: keep remote reference
            image_src = image_field

        items.append(
            {
                "title": title,
                "description": description,
                "section": section,
                "image_src": image_src,
                "raw": row,
            }
        )
    return items


def build_from_local_sample(cfg: dict) -> list[dict]:
    sample = ROOT / "sample" / "content.csv"
    settings_sample = ROOT / "sample" / "settings.csv"
    # Don't clobber Settings already supplied via SETTINGS_JSON / SETTINGS_CSV_PATH
    has_inline_settings = bool(
        os.environ.get("SETTINGS_JSON", "").strip()
        or os.environ.get("SETTINGS_CSV_PATH", "").strip()
    )
    if settings_sample.is_file() and not has_inline_settings:
        print(f"Loading sample settings: {settings_sample}")
        apply_settings_dict(
            cfg,
            parse_settings_rows(
                parse_csv_text(settings_sample.read_text(encoding="utf-8-sig"))
            ),
        )
        # Env brand/image overrides still win over sample/settings.csv
        for key in ("site_title", "site_tagline"):
            if os.environ.get(key.upper()):
                cfg[key] = os.environ[key.upper()]
        if os.environ.get("IMAGE_MAX_WIDTH"):
            cfg["image_max_width"] = int(os.environ["IMAGE_MAX_WIDTH"])
        if os.environ.get("IMAGE_QUALITY"):
            cfg["image_quality"] = int(os.environ["IMAGE_QUALITY"])
    print(f"Using local sample sheet: {sample}")
    with sample.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            {normalize_key(k): (v or "").strip() for k, v in raw.items() if k}
            for raw in reader
            if any((v or "").strip() for v in raw.values())
        ]
    # Sample has placeholder image IDs — generate placeholder JPEGs
    out_dir = ROOT / cfg["output_dir"]
    img_dir = out_dir / "images"
    if img_dir.exists():
        shutil.rmtree(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)

    colors = [(31, 61, 50), (90, 110, 94), (196, 92, 38), (55, 80, 70)]
    items = []
    for idx, row in enumerate(rows):
        if not is_published(row):
            continue
        title = row.get("title") or f"Item {idx + 1}"
        img = Image.new("RGB", (1400, 900), colors[idx % len(colors)])
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        filename = f"{slugify(title)}-sample.jpg"
        (img_dir / filename).write_bytes(buf.getvalue())
        items.append(
            {
                "title": title,
                "description": row.get("description") or "",
                "section": (row.get("section") or "gallery").lower(),
                "image_src": f"images/{filename}",
                "raw": row,
            }
        )
    return items


def main() -> int:
    cfg = load_config()
    out_dir = ROOT / cfg["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    spreadsheet_id = cfg.get("spreadsheet_id") or ""
    use_sample = (
        os.environ.get("USE_SAMPLE", "").lower() in ("1", "true", "yes")
        or not spreadsheet_id
        or spreadsheet_id.startswith("REPLACE_")
    )

    sheet_csv_path = os.environ.get("SHEET_CSV_PATH", "").strip()
    inline_csv = os.environ.get("SHEET_CSV", "").strip()

    if sheet_csv_path:
        path = Path(sheet_csv_path)
        if not path.is_file():
            raise RuntimeError(f"SHEET_CSV_PATH does not exist: {path}")
        rows = load_csv_from_path(path)
        print(f"Loaded {len(rows)} rows from dispatch payload")
        items = process_rows(cfg, rows)
    elif inline_csv:
        rows = parse_csv_text(inline_csv, source="SHEET_CSV env")
        print(f"Loaded {len(rows)} rows from SHEET_CSV env")
        items = process_rows(cfg, rows)
    elif use_sample:
        print("No real spreadsheet configured — building demo site from sample/content.csv")
        items = build_from_local_sample(cfg)
    else:
        url = sheet_csv_url(spreadsheet_id, str(cfg.get("sheet_gid") or "0"))
        rows = fetch_csv(url)
        print(f"Loaded {len(rows)} rows")
        items = process_rows(cfg, rows)

    built_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = render_html(cfg, items, built_at)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    write_assets(out_dir)

    # Keep a copy of last-fetched data for debugging
    data_path = out_dir / "data.json"
    data_path.write_text(
        json.dumps(
            {
                "built_at": built_at,
                "site_title": cfg["site_title"],
                "site_tagline": cfg["site_tagline"],
                "image_max_width": cfg["image_max_width"],
                "image_quality": cfg["image_quality"],
                "count": len(items),
                "items": [
                    {
                        "title": i["title"],
                        "description": i["description"],
                        "section": i["section"],
                        "image_src": i["image_src"],
                    }
                    for i in items
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Wrote {out_dir / 'index.html'} ({len(items)} items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
