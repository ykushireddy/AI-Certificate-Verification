"""
Machine-learning text classifier for certificates.

Model:  TF-IDF (word 1-2 grams + character 3-5 grams)
        -> Logistic Regression
Output: probability that the OCR text belongs to a forged / template /
        edited certificate, plus the words that pushed the decision.

The model trains itself the first time it is used (takes ~2 seconds) and is
saved to ai_engine/models/text_classifier.joblib. Re-train it with
`python train_model.py` - that script also adds the OCR text of every
certificate already issued in the database as extra "genuine" examples,
so the model gets better as the college issues more certificates.
"""

import random
import re

import joblib
import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline

import config


GENUINE = 0
FORGED = 1

_model = None


# -------------------------------
# TRAINING DATA GENERATION
# -------------------------------

FIRST_NAMES = [
    "Aarav", "Ananya", "Rohit", "Priya", "Taqia", "Kiran", "Meera", "Arjun",
    "Sneha", "Vikram", "Zohra", "Rahul", "Divya", "Farhan", "Lakshmi",
    "Nikhil", "Pooja", "Sameer", "Ayesha", "Karthik", "Saniya", "Harsha"
]
LAST_NAMES = [
    "Sharma", "Rao", "Khan", "Iyer", "Reddy", "Patel", "Nair", "Gowda",
    "Bakhtiar", "Shetty", "Menon", "Kulkarni", "Hegde", "Joshi", "Das"
]
COURSES = [
    "Bachelor of Engineering in Computer Science and Engineering",
    "Bachelor of Engineering in Electronics and Communication",
    "Master of Business Administration", "Bachelor of Science in Physics",
    "Machine Learning Certification Program", "Data Structures and Algorithms",
    "Cloud Computing Fundamentals", "Bachelor of Commerce",
    "Master of Computer Applications", "Python Programming Workshop",
    "Cyber Security Essentials", "Digital Signal Processing"
]
INSTITUTIONS = [
    "Nitte Meenakshi Institute of Technology", "Visvesvaraya Technological University",
    "Bangalore University", "Indian Institute of Science",
    "National Institute of Technology Karnataka", "Christ University",
    "Jyoti Nivas College", "RV College of Engineering", "Anna University"
]
GRADES = ["First Class with Distinction", "First Class", "Second Class",
          "Grade A", "Grade O", "CGPA 8.05", "CGPA 9.12", "Grade B+"]

GENUINE_TEMPLATES = [
    "{inst}\nThis is to certify that {name} bearing USN {usn} has successfully "
    "completed the {course} during the academic year {year1}-{year2} and has been "
    "awarded {grade}.\nCertificate No: {cno}\nDate of Issue: {day}/{month}/{year2}\n"
    "Principal  Registrar  Controller of Examinations",

    "{inst}\nCERTIFICATE OF COMPLETION\nPresented to: {name}\nCourse: {course}\n"
    "Year: {year2}\nRegister Number: {usn}\nIn recognition of successful completion "
    "of all requirements.\nAuthorised Signatory  Head of Department\nSerial No. {cno}",

    "{inst}\n(Affiliated to Visvesvaraya Technological University, Belagavi)\n"
    "Provisional Degree Certificate\nName: {name}\nUSN: {usn}\nDegree: {course}\n"
    "Class: {grade}\nMonth and Year of Passing: {mon} {year2}\nRegistrar (Evaluation)",

    "Certificate of Achievement\nThis certificate is awarded to {name} for successfully "
    "completing {course} conducted by {inst} from {day}/{month}/{year1} to "
    "{day}/{month}/{year2}.\nCertificate ID: {cno}\nCoordinator  Director",

    "CERTIFICATE OF COMPLETION\nStudent Name: {name}\nCourse: {course}\nYear: {year2}",

    "Certificate\nName: {name}\nProgramme: {course}\nRegister Number: {usn}\n"
    "Year: {year2}\n{inst}",

    "CERTIFICATE OF PARTICIPATION\nThis is to certify that {name} participated in "
    "{course} held on {day}/{month}/{year2}.",

    "{inst}\nMARKS CARD CUM CERTIFICATE\nStudent Name: {name}\nProgramme: {course}\n"
    "Register No: {usn}\nResult: PASS  {grade}\nIssued on: {day}-{month}-{year2}\n"
    "Seal of the Institution  Controller of Examinations",
]

# Things that commonly appear on fake, purchased, template or edited certificates
FORGERY_MARKERS = [
    "SAMPLE", "SPECIMEN", "TEMPLATE", "Your Name Here", "[Student Name]",
    "Lorem ipsum dolor sit amet", "Edit this text", "Insert Logo Here",
    "Created with Canva", "Made with free certificate maker",
    "www.fakedegree.com", "Novelty certificate for entertainment purposes only",
    "Buy verified degree online", "No exam required", "Instant degree",
    "Life experience degree", "Customize this certificate", "Watermark preview",
    "Photoshop", "Template by Freepik", "Not valid for official use",
    "Certificate generator", "Replace with your text", "Duplicate copy",
    "Signature Here", "Date Here", "Name of Institution", "XXXXXXXX",
]

# Typical forger misspellings of official words
MISSPELLINGS = {
    "Certificate": ["Certifcate", "Certficate", "Certiflcate", "Cerificate"],
    "University": ["Universty", "Univercity", "Unversity"],
    "Registrar": ["Registar", "Regestrar"],
    "successfully": ["sucessfully", "successfuly", "succesfully"],
    "Examinations": ["Examnations", "Exarninations"],
    "Institute": ["Institue", "Instutite"],
    "awarded": ["awared", "awardd"],
    "Technology": ["Technolgy", "Tecnology"],
}

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def _ocr_noise(text, rng, rate=0.02):
    """Simulate OCR errors (swapped / dropped characters)."""
    confusions = {"o": "0", "l": "1", "i": "l", "e": "c", "S": "5", "B": "8", "a": "o"}
    out = []
    for ch in text:
        roll = rng.random()
        if roll < rate and ch in confusions:
            out.append(confusions[ch])
        elif roll < rate * 1.3:
            continue
        else:
            out.append(ch)
    return "".join(out)


def _fill(template, rng, year_range=(2005, 2026)):
    year2 = rng.randint(*year_range)
    return template.format(
        inst=rng.choice(INSTITUTIONS),
        name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
        usn=f"1NT{rng.randint(15, 25)}CS{rng.randint(1, 300):03d}",
        course=rng.choice(COURSES),
        grade=rng.choice(GRADES),
        year1=year2 - rng.randint(0, 4),
        year2=year2,
        cno=f"{rng.choice(['NMIT', 'VTU', 'CERT', 'BU'])}-{rng.randint(10000, 99999)}",
        day=f"{rng.randint(1, 28):02d}",
        month=f"{rng.randint(1, 12):02d}",
        mon=rng.choice(MONTHS),
    )


def _make_forged(rng):
    text = _fill(rng.choice(GENUINE_TEMPLATES), rng)
    tricks = rng.sample(
        ["marker", "marker", "misspell", "placeholder", "strip"],
        k=rng.randint(1, 3)
    )

    for trick in tricks:
        if trick == "marker":
            lines = text.split("\n")
            lines.insert(rng.randint(0, len(lines)), rng.choice(FORGERY_MARKERS))
            text = "\n".join(lines)

        elif trick == "misspell":
            for word, wrong in MISSPELLINGS.items():
                if word in text and rng.random() < 0.7:
                    text = text.replace(word, rng.choice(wrong), 1)

        elif trick == "placeholder":
            text = text.replace(
                text.split("\n")[0], rng.choice(["Name of Institution", "INSTITUTE NAME", "Your College"])
            )

        elif trick == "strip":
            # Forged documents often lack the official sign-off lines
            for word in ["Registrar", "Principal", "Controller of Examinations",
                         "Seal of the Institution", "Authorised Signatory"]:
                text = text.replace(word, "")
            text += "\n" + rng.choice(["Signature Here", "Signed", "Director Sign"])

    return text


def build_dataset(samples_per_class=1500, seed=42, extra_genuine=None):
    rng = random.Random(seed)
    texts, labels = [], []

    for _ in range(samples_per_class):
        texts.append(_ocr_noise(_fill(rng.choice(GENUINE_TEMPLATES), rng), rng))
        labels.append(GENUINE)

        texts.append(_ocr_noise(_make_forged(rng), rng))
        labels.append(FORGED)

    for text in extra_genuine or []:
        if text and text.strip():
            texts.append(text)
            labels.append(GENUINE)

    return texts, labels


# -------------------------------
# MODEL
# -------------------------------

def normalize_text(text):
    """Lower-case and mask digits so years / roll numbers are not memorised.
    (Date sanity checks are done separately in analyzer.py.)"""
    return re.sub(r"\d", "#", text.lower())


def _build_pipeline():
    features = FeatureUnion([
        ("words", TfidfVectorizer(
            preprocessor=normalize_text, ngram_range=(1, 2), min_df=2, sublinear_tf=True
        )),
        ("chars", TfidfVectorizer(
            preprocessor=normalize_text, analyzer="char_wb", ngram_range=(3, 5),
            min_df=3, sublinear_tf=True, max_features=40000
        )),
    ])

    return Pipeline([
        ("features", features),
        ("classifier", LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")),
    ])


def train_model(extra_genuine=None, save=True, verbose=False):
    texts, labels = build_dataset(extra_genuine=extra_genuine)

    x_train, x_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=7, stratify=labels
    )

    model = _build_pipeline()
    model.fit(x_train, y_train)
    accuracy = model.score(x_test, y_test)

    # Final model uses all data
    model.fit(texts, labels)

    if save:
        config.MODEL_FOLDER.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, config.TEXT_MODEL_PATH)

    if verbose:
        print(f"Training samples: {len(texts)}")
        print(f"Held-out accuracy: {accuracy:.3f}")
        print(f"Model saved to: {config.TEXT_MODEL_PATH}")

    return model, accuracy


def load_model():
    global _model

    if _model is not None:
        return _model

    try:
        _model = joblib.load(config.TEXT_MODEL_PATH)
    except Exception:
        # Missing or created with a different scikit-learn version
        _model, _ = train_model()

    return _model


def _top_signals(model, text, limit=5):
    """Words/phrases in this text that pushed most towards 'forged'."""
    word_vectorizer = model.named_steps["features"].transformer_list[0][1]
    classifier = model.named_steps["classifier"]

    word_vector = word_vectorizer.transform([text])
    names = word_vectorizer.get_feature_names_out()
    word_coefs = classifier.coef_[0][: len(names)]

    contributions = word_vector.multiply(word_coefs).toarray()[0]
    order = np.argsort(contributions)[::-1]

    signals = []
    for i in order:
        if contributions[i] <= 0.05 or len(signals) == limit:
            break
        if names[i] not in ENGLISH_STOP_WORDS:
            signals.append(names[i])

    return signals


def predict(text):
    if not text or not text.strip():
        return {
            "forgery_probability": None,
            "label": "NO TEXT",
            "signals": [],
        }

    model = load_model()
    probability = float(model.predict_proba([text])[0][FORGED])

    return {
        "forgery_probability": round(probability, 3),
        "label": "LIKELY FORGED" if probability >= 0.5 else "LIKELY GENUINE",
        "signals": _top_signals(model, text) if probability >= 0.3 else [],
    }
