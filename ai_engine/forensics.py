"""
Document forensics: looks for signs that the certificate FILE was edited.

Images (PNG / JPG)
    * Error Level Analysis (ELA): the image is re-saved as JPEG and compared
      with the original. Regions that were pasted in or edited have a
      different compression history, so they show a different error level
      from the rest of the page. We measure how uneven the error is across
      the page and produce a heatmap for the result page.
    * EXIF "Software" tag: flags files saved by editors such as Photoshop.

PDF
    * Metadata: Creator / Producer written by an editing tool.
    * Modification date later than the creation date.
    * Incremental updates: every time a PDF is edited and saved "in place",
      a new %%EOF marker is appended. More than one means it was changed
      after it was first produced.
"""

import base64
import io
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

EDITOR_KEYWORDS = [
    "photoshop", "gimp", "canva", "picsart", "paint.net", "pixlr", "snapseed",
    "illustrator", "affinity", "inkscape", "coreldraw", "sejda", "pdfescape",
    "smallpdf", "ilovepdf", "pdf editor", "pdffiller", "foxit phantompdf",
    "nitro", "acrobat pro", "pdf-xchange editor", "dochub",
]

BLOCK = 16


# -------------------------------
# IMAGE FORENSICS
# -------------------------------

def error_level_analysis(image, quality=90):
    """Return the per-pixel ELA difference (grayscale numpy array)."""
    image = image.convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    buffer.seek(0)
    resaved = Image.open(buffer).convert("RGB")

    difference = ImageChops.difference(image, resaved)
    return np.asarray(difference, dtype=np.float32).max(axis=2)


def _ela_heatmap(ela, page):
    """
    Overlay the error levels on a faded copy of the page so you can see
    WHERE the suspicious areas are. Returned as a base64 PNG.
    """
    level = np.clip(ela / max(float(np.percentile(ela, 99.7)), 1.0), 0, 1)

    background = np.asarray(page.convert("L"), dtype=np.float32)
    background = 255 - (255 - background) * 0.35  # fade the page

    red = np.array([220, 40, 40], dtype=np.float32)
    alpha = level[..., None] * 0.9
    base = np.repeat(background[..., None], 3, axis=2)
    blended = base * (1 - alpha) + red * alpha

    heatmap = Image.fromarray(blended.astype(np.uint8))
    heatmap.thumbnail((900, 900))

    buffer = io.BytesIO()
    heatmap.save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _block_means(array, h, w):
    return array[:h, :w].reshape(h // BLOCK, BLOCK, w // BLOCK, BLOCK)


def jpeg_ghost_analysis(image):
    """
    JPEG-ghost Error Level Analysis (Farid, 2009).

    The page is re-saved at several JPEG qualities. At the quality the
    original was compressed with, untouched areas almost disappear from the
    error map (a "ghost"), while text that was pasted or edited afterwards
    still shows a high error. We look at every ghost quality and measure how
    far the brightest content blocks stand out from typical content.

    Returns (risk 0..1, ghost_quality, error-map used for the heatmap).
    """
    gray_page = np.asarray(image.convert("L"), dtype=np.float32)
    h, w = gray_page.shape
    h, w = h - h % BLOCK, w - w % BLOCK
    if h < BLOCK * 4 or w < BLOCK * 4:
        return 0.0, None, error_level_analysis(image)

    # Only judge blocks that contain ink (text, logos, signatures)
    content = _block_means(gray_page, h, w).std(axis=(1, 3)) > 12
    if content.sum() < 20:
        return 0.0, None, error_level_analysis(image)

    qualities = list(range(60, 100, 5))
    maps, medians, peaks = {}, [], []

    for quality in qualities:
        ela = error_level_analysis(image, quality)
        blocks = _block_means(ela, h, w).mean(axis=(1, 3))[content]
        maps[quality] = ela
        medians.append(float(np.median(blocks)))
        peaks.append(float(np.percentile(blocks, 99)))

    best_gap, best_quality = 0.0, None
    for i, quality in enumerate(qualities):
        left = medians[i - 1] if i > 0 else float("inf")
        right = medians[i + 1] if i < len(qualities) - 1 else float("inf")
        is_ghost = medians[i] < left and medians[i] < right
        if is_ghost and medians[i] < 1.5:
            gap = peaks[i] - medians[i]
            if gap > best_gap:
                best_gap, best_quality = gap, quality

    if best_quality is None:
        # Never JPEG-compressed (e.g. a clean PNG export) - plain ELA view
        return 0.0, None, maps[90]

    # Untouched pages measured ~1.5-3.3 grey levels; edited ones 5+
    risk = min(1.0, max(0.0, (best_gap - 3.5) / 2.5))
    return risk, best_quality, maps[best_quality]


def analyze_image(file_path):
    findings = []
    image = Image.open(file_path)

    software = ""
    try:
        software = str(image.getexif().get(305, "") or "")  # 305 = Software
    except Exception:
        pass

    editor_hit = any(k in software.lower() for k in EDITOR_KEYWORDS)
    if editor_hit:
        findings.append(f"Image was saved with editing software: {software}")

    rgb = image.convert("RGB")
    rgb.thumbnail((1600, 1600))

    inconsistency, ghost_quality, ela = jpeg_ghost_analysis(rgb)

    if inconsistency >= 0.5:
        findings.append(
            "Error Level Analysis found text regions with a different compression "
            f"history from the rest of the page (JPEG ghost at quality {ghost_quality}) "
            "- typical of pasted or edited text. Bright areas in the heatmap show where."
        )

    risk = max(inconsistency, 0.8 if editor_hit else 0.0)

    return {
        "method": "Error Level Analysis (JPEG ghost) + EXIF",
        "risk": round(risk, 3),
        "ela_inconsistency": round(inconsistency, 3),
        "findings": findings,
        "heatmap": _ela_heatmap(ela, rgb),
    }


# -------------------------------
# PDF FORENSICS
# -------------------------------

def _pdf_date(value):
    match = re.search(r"(\d{14})", str(value or ""))
    return match.group(1) if match else None


def analyze_pdf(file_path):
    findings = []
    risk = 0.0

    raw = Path(file_path).read_bytes()
    eof_count = raw.count(b"%%EOF")

    metadata = {}
    try:
        from pypdf import PdfReader
        info = PdfReader(str(file_path)).metadata or {}
        metadata = {
            "creator": str(info.get("/Creator", "") or ""),
            "producer": str(info.get("/Producer", "") or ""),
            "created": _pdf_date(info.get("/CreationDate")),
            "modified": _pdf_date(info.get("/ModDate")),
        }
    except Exception:
        findings.append("PDF metadata could not be read.")

    tools = f"{metadata.get('creator', '')} {metadata.get('producer', '')}".lower()
    editor = next((k for k in EDITOR_KEYWORDS if k in tools), None)
    if editor:
        findings.append(f"PDF was produced or modified with an editing tool ({editor}).")
        risk = max(risk, 0.7)

    if metadata.get("created") and metadata.get("modified"):
        if metadata["modified"][:12] > metadata["created"][:12]:
            findings.append("PDF was modified after it was originally created.")
            risk = max(risk, 0.45)

    if eof_count > 1:
        findings.append(
            f"PDF contains {eof_count - 1} incremental update(s) - content was "
            "changed and re-saved after the original was produced."
        )
        risk = max(risk, 0.6)

    return {
        "method": "PDF metadata + revision analysis",
        "risk": round(risk, 3),
        "metadata": metadata,
        "findings": findings,
        "heatmap": None,
    }


def analyze_file(file_path):
    if not file_path:
        return None

    file_path = Path(file_path)
    extension = file_path.suffix.lower()

    try:
        if extension == ".pdf":
            return analyze_pdf(file_path)
        if extension in (".png", ".jpg", ".jpeg"):
            return analyze_image(file_path)
    except Exception as error:
        return {
            "method": "Forensics",
            "risk": 0.0,
            "findings": [f"Forensic analysis failed: {error}"],
            "heatmap": None,
        }

    return None
