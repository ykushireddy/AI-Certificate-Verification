
import os
from pathlib import Path
from dotenv import load_dotenv

# Main project directory
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")

import shutil


def _find_tool(env_name, windows_default, command):
    """
    Locate an external tool in this order:
    1. Path given in the .env file
    2. Default Windows install location (if it exists)
    3. Whatever is on the system PATH (Linux / macOS / Windows)
    """
    env_value = os.getenv(env_name)
    if env_value:
        return env_value

    if Path(windows_default).exists():
        return windows_default

    found = shutil.which(command)
    if found:
        return found if env_name == "TESSERACT_CMD" else str(Path(found).parent)

    return None


# Tesseract OCR executable
TESSERACT_CMD = _find_tool(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "tesseract"
)

# Poppler executable directory (used to convert PDFs to images)
POPPLER_PATH = _find_tool(
    "POPPLER_PATH",
    r"C:\poppler\poppler-26.09.0\Library\bin",
    "pdfinfo"
)

# Trained AI model location
MODEL_FOLDER = BASE_DIR / "ai_engine" / "models"
TEXT_MODEL_PATH = MODEL_FOLDER / "text_classifier.joblib"

# Application secret key
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "development-secret-key-change-later"
)

# Database configuration
INSTANCE_FOLDER = BASE_DIR / "instance"
DATABASE_PATH = INSTANCE_FOLDER / "certificates.db"

# Upload directories
UPLOAD_FOLDER = BASE_DIR / "uploads" / "certificates"
QR_FOLDER = BASE_DIR / "uploads" / "qrcodes"

# Maximum upload size: 10 MB
MAX_CONTENT_LENGTH = 10 * 1024 * 1024

# Allowed certificate formats
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

# Create required directories automatically
for folder in [
    INSTANCE_FOLDER,
    UPLOAD_FOLDER,
    QR_FOLDER
]:
    folder.mkdir(parents=True, exist_ok=True)
