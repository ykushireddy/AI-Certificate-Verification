"""
Cross-checks the text that OCR read off the certificate against the details
that are on record (typed in by the admin, or stored in the database).

OCR is never perfect, so every comparison is fuzzy: we slide a window over
the OCR text and keep the best similarity score (0-100) for each field.
"""

import re
from difflib import SequenceMatcher

FIELD_WEIGHTS = {
    "student_name": 0.35,
    "register_number": 0.25,
    "course": 0.2,
    "year": 0.1,
    "college": 0.1,
}

FIELD_LABELS = {
    "student_name": "Student name",
    "register_number": "Register number",
    "course": "Course",
    "year": "Year",
    "college": "College",
}

MATCH_THRESHOLD = 80


def _clean(text):
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def best_match(expected, text):
    """Return (score 0-100, closest text found) for `expected` inside `text`."""
    expected = _clean(expected)
    words = _clean(text).split()

    if not expected or not words:
        return 0, ""

    if expected in " ".join(words):
        return 100, expected

    size = len(expected.split())
    best_score, best_window = 0.0, ""

    for window_size in {max(1, size - 1), size, size + 1}:
        for start in range(0, max(1, len(words) - window_size + 1)):
            window = " ".join(words[start:start + window_size])
            score = SequenceMatcher(None, expected, window).ratio()
            if score > best_score:
                best_score, best_window = score, window

    return round(best_score * 100), best_window


def match_fields(text, expected, extracted=None):
    """
    Compare OCR text with expected values.
    Returns overall match score (0-100), per-field results and warnings.
    """
    results = {}
    warnings = []
    total_weight = 0.0
    weighted_score = 0.0

    for field, weight in FIELD_WEIGHTS.items():
        value = (expected or {}).get(field)
        if not value:
            continue

        score, found = best_match(value, text)
        matched = score >= MATCH_THRESHOLD

        # When it doesn't match, show what the document actually says in that
        # field (read by the field extractor) rather than the nearest words
        if not matched and extracted and extracted.get(field):
            found = extracted[field]

        results[field] = {
            "label": FIELD_LABELS[field],
            "expected": value,
            "found": found,
            "score": score,
            "matched": matched,
        }

        total_weight += weight
        weighted_score += weight * score

        if not matched:
            warnings.append(
                f"{FIELD_LABELS[field]} on record is '{value}', but the document "
                f"shows '{found or 'nothing similar'}' ({score}% match)."
            )

    overall = round(weighted_score / total_weight) if total_weight else None

    return {
        "overall_score": overall,
        "fields": results,
        "warnings": warnings,
    }


def find_closest_certificate(text, certificates, minimum_score=70):
    """
    For a file that does NOT match any registered hash: find which
    registered certificate it most resembles (a probable altered copy).
    """
    best, best_score = None, 0

    for certificate in certificates:
        expected = {
            "student_name": certificate["student_name"],
            "course": certificate["course"],
            "register_number": certificate["register_number"],
            "college": certificate["college"],
        }
        score = match_fields(text, expected)["overall_score"] or 0
        if score > best_score:
            best, best_score = certificate, score

    if best is not None and best_score >= minimum_score:
        return best, best_score

    return None, best_score
