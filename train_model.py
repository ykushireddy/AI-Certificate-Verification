"""
Train (or re-train) the AI text classifier.

    python train_model.py

Uses the built-in training set plus the OCR text of every certificate
already issued in the database as extra "genuine" examples - so the more
certificates your college issues, the better the model knows what a real
one looks like.
"""

import database
from ai_engine import text_classifier
from ai_engine.ocr import extract_text


def issued_certificate_texts():
    texts = []
    for certificate in database.get_all_certificates():
        try:
            texts.append(extract_text(certificate["file_path"]))
        except Exception as error:
            print(f"Skipping {certificate['certificate_id']}: {error}")
    return texts


if __name__ == "__main__":
    database.init_db()
    extra = issued_certificate_texts()
    print(f"Issued certificates added as genuine examples: {len(extra)}")
    text_classifier.train_model(extra_genuine=extra, verbose=True)
