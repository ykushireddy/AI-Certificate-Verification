
from pathlib import Path

import pytesseract
from PIL import Image
from pdf2image import convert_from_path

import config


# Configure Tesseract executable
if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD


def _pdf_text_layer(file_path):
    try:
        from pypdf import PdfReader
        pages = [
            page.extract_text() or ""
            for page in PdfReader(str(file_path)).pages
        ]
    except Exception:
        return None

    if sum(len(page.strip()) for page in pages) < 40:
        return None

    return "\n\n".join(
        f"--- Page {number} ---\n{text}"
        for number, text in enumerate(pages, start=1)
    )


def extract_text(file_path):
    """
    Extract text from a PDF or image certificate.

    Supported formats:
    PDF, PNG, JPG, JPEG
    """

    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"Certificate not found: {file_path}"
        )

    extension = file_path.suffix.lower()

    # Digital PDFs already contain text - read it directly (faster and
    # exact). Scanned PDFs have no text layer, so fall back to OCR.
    if extension == ".pdf":
        embedded = _pdf_text_layer(file_path)
        if embedded:
            return embedded

        images = convert_from_path(
            str(file_path),
            dpi=300,
            poppler_path=config.POPPLER_PATH
        )

    # Open image certificates
    elif extension in [".png", ".jpg", ".jpeg"]:

        image = Image.open(file_path).convert("RGB")
        images = [image]

    else:
        raise ValueError(
            "Unsupported file format"
        )

    extracted_text = []

    # Perform OCR on every page
    for page_number, image in enumerate(images, start=1):

        text = pytesseract.image_to_string(
            image,
            lang="eng",
            config="--oem 3 --psm 6"
        )

        extracted_text.append(
            f"--- Page {page_number} ---\n{text}"
        )

    return "\n\n".join(extracted_text)
