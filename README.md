# VeriCred AI - AI + Blockchain Certificate Verification

A college admin issues digital certificates; each file's SHA-256 hash is stored on an
Ethereum smart contract. Anyone can verify a certificate by ID, QR code or by uploading
the file. An AI layer checks every certificate for signs of forgery or editing.

## How it works

**Issuing (admin)**: upload file + details -> OCR -> AI analysis -> SHA-256 hash ->
certificate ID + QR code -> saved in SQLite -> hash registered on the blockchain.

**Verifying (public)**
- By ID / QR: blockchain hash is compared with the database record.
- By file upload: the file's hash is looked up. If it isn't registered, the AI finds which
  registered certificate it most resembles and shows exactly which fields were changed.

## The AI engine (`ai_engine/`)

| Module | What it does |
|---|---|
| `ocr.py` | Reads text from images (Tesseract) and PDFs (embedded text layer, or OCR for scanned PDFs) |
| `text_classifier.py` | **Machine learning**: TF-IDF (word + character n-grams) -> Logistic Regression. Predicts how likely the wording is from a forged/template certificate and explains which words drove the decision |
| `forensics.py` | **Image forensics**: JPEG-ghost Error Level Analysis finds regions with a different compression history (pasted/edited text) and draws a heatmap. EXIF editor check. **PDF forensics**: editing-tool metadata, modified-after-creation, incremental re-saves |
| `field_matcher.py` | Fuzzy-matches the OCR text against the details on record (name, USN, course, year, college); finds the closest registered certificate for unregistered files |
| `analyzer.py` | Combines everything into a 0-100 risk score: **PASSED** (<35), **SUSPICIOUS** (35-59), **HIGH RISK** (60+) |

Weights: text model 35%, forensics 30%, field match 25%, rules 10%. Strong forensic evidence,
or a wrong name / register number, always pushes the result to HIGH RISK.

The text model trains itself on first use (~2 s). Retrain at any time with
`python train_model.py` - this also adds every certificate already issued as a genuine example.

## Setup

Requirements: Python 3.10+, Node.js 18+, [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki),
and [Poppler](https://github.com/oschwartz10612/poppler-windows/releases) (only for scanned PDFs).

```bash
python -m venv venv
venv\Scripts\activate          # Windows  (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
npm install
copy .env.example .env         # then edit SECRET_KEY
```

Run (three terminals):

```bash
npm run node                   # 1. local blockchain
npm run deploy                 # 2. deploy the smart contract
python app.py                  # 3. web app -> http://127.0.0.1:5000
```

Default logins: admin / admin123, student / student123.

Run the tests: `python -m pytest tests`

## Limitations (worth stating in a viva)

- The text classifier's starting dataset is **synthetic** (generated genuine and forged
  certificate texts). It improves as real issued certificates are added via `train_model.py`.
- Error Level Analysis needs the original to have been a JPEG at some point; a forger who
  re-saves the whole edited image at the same quality can hide the traces. That is why the
  blockchain hash, not the AI, is the final proof of authenticity - the AI explains *what*
  is wrong and catches problems at issue time.
- The smart contract lets any account register certificates; for production add an
  `onlyOwner` / issuer whitelist.
