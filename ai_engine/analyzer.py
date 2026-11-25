"""
AI certificate analysis.

Combines four independent checks into one risk score (0-100):

  1. Text classifier (machine learning)  - does the wording look like a
     real certificate or a template / fake?            -> text_classifier.py
  2. Document forensics                  - was the file edited?
     (Error Level Analysis for images, metadata/revisions for PDFs)
                                                      -> forensics.py
  3. Field matching                      - do the name, USN, course... read
     off the document match the record?                -> field_matcher.py
  4. Rules                               - required fields present, no
     impossible dates, no obvious "sample"/"fake" words.
"""

import re
from datetime import date

from ai_engine import field_matcher, forensics, text_classifier


REQUIRED_FIELDS = [
    "student_name",
    "course",
    "year"
]

SUSPICIOUS_KEYWORDS = [
    "fake",
    "sample",
    "specimen",
    "demo certificate",
    "invalid certificate",
    "duplicate",
    "template",
]

# How much each check counts towards the final score
WEIGHTS = {
    "text_model": 0.35,
    "forensics": 0.30,
    "field_match": 0.25,
    "rules": 0.10,
}



def extract_fields(text):
    """
    Extract student name, course and year from certificate text.
    Uses labelled fields and certificate line structure.
    """

    fields = {
        "student_name": None,
        "course": None,
        "year": None
    }

    # Clean OCR text into individual lines
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
    ]

    lines = [
        line for line in lines
        if line and not re.match(r"---\s*Page\s+\d+", line, re.I)
    ]

    # 1. Extract student name using explicit labels
    for line in lines:
        match = re.search(
            r"^(?:student\s*name|name)\s*[:\-]\s*(.+)$",
            line,
            re.I
        )
        if match:
            fields["student_name"] = match.group(1).strip()
            break

    # 2. Extract course using explicit labels
    for line in lines:
        match = re.search(
            r"^(?:course|program|programme|degree)\s*[:\-]\s*(.+)$",
            line,
            re.I
        )
        if match:
            fields["course"] = match.group(1).strip()
            break

    # 3. Identify name and course from certificate layout
    # Example:
    # Student Name
    # Course Name
    # The certificate is awarded...

    anchor_index = next(
        (
            i for i, line in enumerate(lines)
            if re.search(
                r"certificate\s+is\s+awarded|"
                r"this\s+certificate\s+is\s+presented|"
                r"has\s+successfully\s+completed",
                line,
                re.I
            )
        ),
        None
    )

    if anchor_index is not None:
        preceding = lines[:anchor_index]

        if len(preceding) >= 2:

            if not fields["student_name"]:
                fields["student_name"] = preceding[-2]

            if not fields["course"]:
                fields["course"] = preceding[-1]

    # 4. Extract year
    year_match = re.search(
        r"(?:issued\s*on|date|year).*?\b((?:19|20)\d{2})\b",
        text,
        re.I
    )

    if not year_match:
        year_match = re.search(
            r"\b((?:19|20)\d{2})\b",
            text
        )

    if year_match:
        fields["year"] = year_match.group(1)

    return fields



def rule_checks(text, fields):
    warnings = []

    missing_fields = [
        field for field in REQUIRED_FIELDS
        if not fields.get(field)
    ]

    if missing_fields:
        warnings.append(
            "Missing required fields: "
            + ", ".join(missing_fields)
        )

    lowered = text.lower()
    keyword_hits = [k for k in SUSPICIOUS_KEYWORDS if k in lowered]

    for keyword in keyword_hits:
        warnings.append(f"Suspicious keyword detected: {keyword}")

    year_problem = False
    if fields.get("year"):
        year = int(fields["year"])
        # Allow one year ahead for certificates issued for the coming batch
        if year > date.today().year + 1 or year < 1950:
            warnings.append(f"Unusual certificate year: {year}")
            year_problem = True

    risk = min(1.0, 0.25 * len(missing_fields) + 0.4 * len(keyword_hits) + (0.5 if year_problem else 0))

    return risk, missing_fields, warnings


def _verdict(score):
    if score >= 60:
        return "HIGH RISK", "Likely forged or altered"
    if score >= 35:
        return "SUSPICIOUS", "Needs manual review"
    return "PASSED", "Looks genuine"


def analyze_certificate(text, file_path=None, expected=None):
    """
    Analyze a certificate.

    text      - OCR text of the certificate
    file_path - the certificate file (enables forensic checks)
    expected  - dict of details on record, e.g. {"student_name": ..., "course": ...,
                "year": ..., "register_number": ..., "college": ...}
    """

    text = text or ""
    has_text = bool(text.strip())

    fields = extract_fields(text) if has_text else {}
    components = {}
    scores = {}
    warnings = []

    # 1. Machine-learning text classifier
    if has_text:
        prediction = text_classifier.predict(text)
        components["text_model"] = prediction
        scores["text_model"] = prediction["forgery_probability"]
        if prediction["forgery_probability"] >= 0.5:
            hint = ", ".join(f"'{s}'" for s in prediction["signals"][:3])
            warnings.append(
                "AI text model rates the wording as typical of forged/template "
                f"certificates ({prediction['forgery_probability']:.0%})"
                + (f" - signals: {hint}." if hint else ".")
            )
    else:
        warnings.append("No readable certificate text found.")

    # 2. File forensics
    forensic = forensics.analyze_file(file_path)
    if forensic:
        components["forensics"] = forensic
        scores["forensics"] = forensic["risk"]
        warnings.extend(forensic["findings"])

    # 3. Field matching against the record
    if expected and has_text:
        matching = field_matcher.match_fields(text, expected, extracted=fields)
        components["field_match"] = matching
        if matching["overall_score"] is not None:
            scores["field_match"] = 1 - matching["overall_score"] / 100
        warnings.extend(matching["warnings"])

    # 4. Rules
    if has_text:
        rule_risk, missing_fields, rule_warnings = rule_checks(text, fields)
    else:
        rule_risk, missing_fields, rule_warnings = 1.0, list(REQUIRED_FIELDS), []
    scores["rules"] = rule_risk
    warnings.extend(rule_warnings)

    # Weighted risk score, using only the checks that could run
    used = {name: WEIGHTS[name] for name in scores}
    total = sum(used.values())
    risk_score = round(100 * sum(scores[n] * w for n, w in used.items()) / total)

    # Strong evidence of file editing or impossible content should not be
    # averaged away by the other checks
    strongest = max(scores.get("forensics", 0), scores.get("rules", 0))
    if strongest >= 0.9:
        risk_score = max(risk_score, 60)

    # A wrong name / register number means the document is not the one on
    # record; a wrong course, year or college needs at least a manual review
    matched_fields = components.get("field_match", {}).get("fields", {})
    mismatched = {name for name, item in matched_fields.items() if not item["matched"]}
    if mismatched & {"student_name", "register_number"}:
        risk_score = max(risk_score, 60)
    elif mismatched:
        risk_score = max(risk_score, 40)

    status, verdict = _verdict(risk_score)

    return {
        "status": status,
        "verdict": verdict,
        "risk_score": risk_score,
        "check_scores": {name: round(value * 100) for name, value in scores.items()},
        "fields": fields,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "components": components,
        "analysis_type": "AI analysis (ML text model + document forensics + field matching)",
    }
