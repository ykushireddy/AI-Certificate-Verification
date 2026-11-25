"""
Tests for the AI engine.   Run with:  python -m pytest tests
"""

import io
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai_engine import field_matcher, forensics, text_classifier  # noqa: E402
from ai_engine.analyzer import analyze_certificate  # noqa: E402

GENUINE_TEXT = (
    "Nitte Meenakshi Institute of Technology\n"
    "This is to certify that Rohit Sharma bearing USN 1NT23CS100 has successfully "
    "completed the Cloud Computing Fundamentals during the academic year 2024-2025.\n"
    "Principal  Registrar  Controller of Examinations"
)
FAKE_TEXT = (
    "CERTIFICATE OF EXCELLENCE\nThis Certifcate is awarded to Your Name Here "
    "for completing Python course. Created with Canva. Signature Here"
)
EXPECTED = {
    "student_name": "Rohit Sharma",
    "course": "Cloud Computing Fundamentals",
    "register_number": "1NT23CS100",
}


def _font():
    try:
        return ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        try:
            return ImageFont.truetype("arial.ttf", 34)
        except OSError:
            return ImageFont.load_default()


def _certificate_image(tmp_path):
    image = Image.new("RGB", (1400, 1000), (250, 246, 235))
    draw = ImageDraw.Draw(image)
    lines = ["Nitte Meenakshi Institute of Technology", "CERTIFICATE OF COMPLETION",
             "Name: Rohit Sharma", "Course: Cloud Computing Fundamentals",
             "Year: 2025", "Register Number: 1NT23CS100", "Principal      Registrar"]
    for i, line in enumerate(lines):
        draw.text((120, 100 + i * 110), line, fill=(30, 30, 30), font=_font())
    path = tmp_path / "genuine.jpg"
    image.save(path, quality=80)
    return path


def test_text_model_separates_genuine_and_fake():
    assert text_classifier.predict(GENUINE_TEXT)["forgery_probability"] < 0.5
    fake = text_classifier.predict(FAKE_TEXT)
    assert fake["forgery_probability"] > 0.8
    assert fake["signals"]


def test_field_matching_tolerates_ocr_errors():
    ocr_text = GENUINE_TEXT.replace("Rohit", "Roh1t")
    result = field_matcher.match_fields(ocr_text, EXPECTED)
    assert result["fields"]["student_name"]["matched"]


def test_field_matching_detects_changed_name():
    result = field_matcher.match_fields(GENUINE_TEXT.replace("Rohit Sharma", "Taqia Bakhtiar"), EXPECTED)
    assert not result["fields"]["student_name"]["matched"]


def test_forensics_flags_edited_image(tmp_path):
    original = _certificate_image(tmp_path)
    assert forensics.analyze_file(original)["risk"] < 0.5

    edited = Image.open(original)
    draw = ImageDraw.Draw(edited)
    draw.rectangle([115, 315, 900, 365], fill=(250, 246, 235))
    draw.text((120, 320), "Name: Taqia Bakhtiar", fill=(30, 30, 30), font=_font())
    edited_path = tmp_path / "edited.png"
    edited.save(edited_path)

    result = forensics.analyze_file(edited_path)
    assert result["risk"] >= 0.5
    assert result["heatmap"]


def test_analyzer_verdicts():
    assert analyze_certificate(GENUINE_TEXT, expected=EXPECTED)["status"] == "PASSED"
    assert analyze_certificate(FAKE_TEXT)["status"] in ("SUSPICIOUS", "HIGH RISK")

    changed = analyze_certificate(GENUINE_TEXT.replace("Rohit Sharma", "Taqia Bakhtiar"), expected=EXPECTED)
    assert changed["status"] == "HIGH RISK"


def test_future_year_is_flagged():
    result = analyze_certificate(GENUINE_TEXT.replace("2024-2025", "2098-2099"))
    assert any("Unusual certificate year" in w for w in result["warnings"])
