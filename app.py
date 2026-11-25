
import os
import uuid
import hashlib
import sqlite3
from functools import wraps

import qrcode

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, send_file
)
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

import config
import database

from ai_engine.ocr import extract_text
from ai_engine.analyzer import analyze_certificate
from ai_engine.field_matcher import find_closest_certificate

from blockchain.blockchain_service import (
    register_certificate,
    verify_certificate
)


app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}


# -------------------------------
# DATABASE INITIALIZATION
# -------------------------------

database.init_db()


# -------------------------------
# HELPER FUNCTIONS
# -------------------------------

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def calculate_file_hash(file_path):
    sha256 = hashlib.sha256()

    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(4096), b""):
            sha256.update(chunk)

    return sha256.hexdigest()


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper


def role_required(role):
    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            if session.get("role") != role:
                flash("You are not authorized to access this page.", "danger")
                return redirect(url_for("index"))

            return function(*args, **kwargs)

        return wrapper

    return decorator


def expected_details(certificate):
    """Details on record that the AI cross-checks against the document."""
    return {
        "student_name": certificate["student_name"],
        "course": certificate["course"],
        "college": certificate["college"],
        "year": certificate["year"],
        "register_number": certificate["register_number"],
    }


def generate_qr(certificate_id):
    verification_url = url_for(
        "verify_by_id",
        certificate_id=certificate_id,
        _external=True
    )

    qr = qrcode.make(verification_url)

    filename = f"{certificate_id}.png"
    qr_path = config.QR_FOLDER / filename

    qr.save(qr_path)

    return str(qr_path)


# -------------------------------
# HOME PAGE
# -------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# -------------------------------
# LOGIN AND LOGOUT
# -------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = database.get_user_by_username(username)

        if user and check_password_hash(
            user["password_hash"], password
        ):

            session.clear()

            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["full_name"] = user["full_name"]
            session["role"] = user["role"]

            if user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))

            return redirect(url_for("student_dashboard"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/student/register", methods=["GET", "POST"])
def student_register():

    if request.method == "POST":

        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not full_name or not username or not password:
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for("student_register"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "danger")
            return redirect(url_for("student_register"))

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("student_register"))

        if database.get_user_by_username(username):
            flash("Username already exists. Please choose another.", "danger")
            return redirect(url_for("student_register"))

        try:
            database.create_student(username, password, full_name)
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("Username already exists. Please choose another.", "danger")
            return redirect(url_for("student_register"))

    return render_template("student_register.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


# -------------------------------
# ADMIN DASHBOARD
# -------------------------------

@app.route("/admin/dashboard")
@login_required
@role_required("admin")
def admin_dashboard():

    certificates = database.get_all_certificates()

    return render_template(
        "admin_dashboard.html",
        certificates=certificates,
        total_certificates=len(certificates)
    )


# -------------------------------
# UPLOAD CERTIFICATE
# -------------------------------

@app.route("/admin/upload", methods=["GET", "POST"])
@login_required
@role_required("admin")
def upload_certificate():

    if request.method == "POST":

        uploaded_file = request.files.get("certificate")

        student_name = request.form.get("student_name", "").strip()
        course = request.form.get("course", "").strip()
        college = request.form.get("college", "").strip()
        year = request.form.get("year", "").strip()
        register_number = request.form.get("register_number", "").strip()
        student_username = request.form.get("student_username", "").strip()
        student = database.get_user_by_username(student_username)

        if not student_username:
            flash("Please enter the student's registered username.", "danger")
            return redirect(url_for("upload_certificate"))

        if not student or student["role"] != "student":
            flash("Invalid student username. Please enter an existing student account.", "danger")
            return redirect(url_for("upload_certificate"))

        if student_name.casefold() != student["full_name"].strip().casefold():
            flash("Student name does not match the registered account.", "danger")
            return redirect(url_for("upload_certificate"))

        if not uploaded_file or uploaded_file.filename == "":
            flash("Please select a certificate file.", "danger")
            return redirect(url_for("upload_certificate"))

        if not allowed_file(uploaded_file.filename):
            flash("Only PDF, PNG, JPG and JPEG files are allowed.", "danger")
            return redirect(url_for("upload_certificate"))

        if not all([student_name, course, college, year]):
            flash("Please fill in all required certificate details.", "danger")
            return redirect(url_for("upload_certificate"))

        filename = secure_filename(uploaded_file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        file_path = config.UPLOAD_FOLDER / unique_filename

        uploaded_file.save(file_path)
        database_saved = False

        try:
            # STEP 1: OCR
            extracted_text = extract_text(file_path)

            # STEP 2: AI ANALYSIS
            analysis = analyze_certificate(
                extracted_text,
                file_path=file_path,
                expected={
                    "student_name": student_name,
                    "course": course,
                    "college": college,
                    "year": year,
                    "register_number": register_number,
                }
            )

            # STEP 3: GENERATE SHA-256 HASH
            certificate_hash = calculate_file_hash(file_path)

            # STEP 4: GENERATE CERTIFICATE ID
            certificate_id = "CERT-" + uuid.uuid4().hex[:10].upper()

            # STEP 5: GENERATE QR CODE
            qr_path = generate_qr(certificate_id)

            # STEP 6: SAVE RECORD IN SQLITE
            database.save_certificate({
                "certificate_id": certificate_id,
                "student_id": student["id"] if student else None,
                "student_name": student_name,
                "course": course,
                "college": college,
                "year": year,
                "register_number": register_number,
                "file_path": str(file_path),
                "file_hash": certificate_hash,
                "qr_path": qr_path,
                "blockchain_tx": None,
                "blockchain_block": None,
                "issued_by": session["user_id"],
                "ai_status": analysis["status"],
                "ai_risk_score": analysis["risk_score"]
            })

            database_saved = True

            # STEP 7: REGISTER ON BLOCKCHAIN
            blockchain_result = register_certificate(
                certificate_id,
                certificate_hash
            )

            # STEP 8: UPDATE BLOCKCHAIN TRANSACTION DETAILS
            database.update_certificate_blockchain(
                certificate_id,
                blockchain_result["transaction_hash"],
                blockchain_result["block_number"]
            )

            return render_template(
                "verification_result.html",
                result="REGISTERED",
                certificate_id=certificate_id,
                certificate_hash=certificate_hash,
                blockchain=blockchain_result,
                analysis=analysis,
                extracted_text=extracted_text
            )

        except Exception as error:

            if "blockchain_result" not in locals():

                if database_saved:
                    database.delete_certificate(certificate_id)

                if "qr_path" in locals() and os.path.exists(qr_path):
                    os.remove(qr_path)

                if file_path.exists():
                    file_path.unlink()

            flash(f"Certificate registration failed: {error}", "danger")
            return redirect(url_for("upload_certificate"))

    return render_template("upload_certificate.html")


# -------------------------------
# STUDENT DASHBOARD
# -------------------------------

@app.route("/student/dashboard")
@login_required
@role_required("student")
def student_dashboard():

    connection = database.get_connection()

    certificates = connection.execute("""
        SELECT * FROM certificates
        WHERE student_id = ?
        ORDER BY created_at DESC
    """, (session["user_id"],)).fetchall()

    submissions = connection.execute("""
        SELECT * FROM certificate_submissions
        WHERE student_id = ?
        ORDER BY submitted_at DESC
    """, (session["user_id"],)).fetchall()

    connection.close()

    return render_template(
        "student_dashboard.html",
        certificates=certificates,
        submissions=submissions
    )


@app.route("/student/submit-certificate", methods=["GET", "POST"])
@login_required
@role_required("student")
def student_submit_certificate():

    if request.method == "POST":

        uploaded_file = request.files.get("certificate")

        course = request.form.get("course", "").strip()
        college = request.form.get("college", "").strip()
        year = request.form.get("year", "").strip()
        register_number = request.form.get("register_number", "").strip()

        if not all([course, college, year]):
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for("student_submit_certificate"))

        if not uploaded_file or not uploaded_file.filename:
            flash("Please upload your certificate.", "danger")
            return redirect(url_for("student_submit_certificate"))

        if not allowed_file(uploaded_file.filename):
            flash("Invalid file format.", "danger")
            return redirect(url_for("student_submit_certificate"))

        try:
            filename = secure_filename(uploaded_file.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            file_path = config.UPLOAD_FOLDER / unique_filename

            uploaded_file.save(file_path)

            extracted_text = extract_text(file_path)

            analysis = analyze_certificate(
                extracted_text,
                file_path=file_path,
                expected={
                    "student_name": session["full_name"],
                    "course": course,
                    "college": college,
                    "year": year,
                    "register_number": register_number
                }
            )

            certificate_hash = calculate_file_hash(file_path)

            connection = database.get_connection()

            connection.execute("""
                INSERT INTO certificate_submissions (
                    student_id, student_name, course, college,
                    year, register_number, file_path, file_hash,
                    ai_status, ai_risk_score
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session["user_id"],
                session["full_name"],
                course,
                college,
                year,
                register_number,
                str(file_path),
                certificate_hash,
                analysis["status"],
                analysis["risk_score"]
            ))

            connection.commit()
            connection.close()

            flash("Certificate submitted successfully for admin review!", "success")

            return redirect(url_for("student_dashboard"))

        except Exception as error:
            if "file_path" in locals() and file_path.exists():
                file_path.unlink()

            flash(f"Submission failed: {error}", "danger")
            return redirect(url_for("student_submit_certificate"))

    return render_template("student_submit_certificate.html")


# -------------------------------
# ADMIN: STUDENT SUBMISSIONS
# -------------------------------

@app.route("/admin/submissions")
@login_required
@role_required("admin")
def admin_submissions():

    submissions = database.get_all_submissions()

    return render_template(
        "admin_submissions.html",
        submissions=submissions
    )


@app.route("/admin/submission/<int:submission_id>/file")
@login_required
@role_required("admin")
def admin_view_submission_file(submission_id):

    submission = database.get_submission_by_id(submission_id)

    if not submission:
        flash("Submission not found.", "danger")
        return redirect(url_for("admin_submissions"))

    if not os.path.exists(submission["file_path"]):
        flash("Uploaded certificate file is missing.", "danger")
        return redirect(url_for("admin_submissions"))

    return send_file(submission["file_path"], as_attachment=False)


@app.route("/admin/submission/<int:submission_id>/review", methods=["POST"])
@login_required
@role_required("admin")
def admin_review_submission(submission_id):

    submission = database.get_submission_by_id(submission_id)

    if not submission:
        flash("Submission not found.", "danger")
        return redirect(url_for("admin_submissions"))

    if submission["status"] != "Pending":
        flash("This submission has already been reviewed.", "warning")
        return redirect(url_for("admin_submissions"))

    action = request.form.get("action")
    admin_note = request.form.get("admin_note", "").strip()

    if action == "reject":
        database.update_submission_status(
            submission_id,
            "Rejected",
            admin_note
        )
        flash("Certificate submission rejected.", "success")
        return redirect(url_for("admin_submissions"))

    if action != "approve":
        flash("Invalid review action.", "danger")
        return redirect(url_for("admin_submissions"))

    certificate_id = "CERT-" + uuid.uuid4().hex[:10].upper()
    qr_path = None
    certificate_saved = False

    try:
        if not os.path.exists(submission["file_path"]):
            raise FileNotFoundError("The uploaded certificate file is missing.")

        # Generate QR code for the approved certificate
        qr_path = generate_qr(certificate_id)

        # Save the approved certificate in the main certificates table
        database.save_certificate({
            "certificate_id": certificate_id,
            "student_id": submission["student_id"],
            "student_name": submission["student_name"],
            "course": submission["course"],
            "college": submission["college"],
            "year": submission["year"],
            "register_number": submission["register_number"],
            "file_path": submission["file_path"],
            "file_hash": submission["file_hash"],
            "qr_path": qr_path,
            "blockchain_tx": None,
            "blockchain_block": None,
            "issued_by": session["user_id"],
            "ai_status": submission["ai_status"],
            "ai_risk_score": submission["ai_risk_score"]
        })

        certificate_saved = True

        # Register only after admin approval
        blockchain_result = register_certificate(
            certificate_id,
            submission["file_hash"]
        )

        database.update_certificate_blockchain(
            certificate_id,
            blockchain_result["transaction_hash"],
            blockchain_result["block_number"]
        )

        database.update_submission_status(
            submission_id,
            "Approved",
            admin_note
        )

        flash(
            f"Certificate approved and registered! ID: {certificate_id}",
            "success"
        )

    except Exception as error:

        # Keep the student's submission pending if approval fails
        if certificate_saved:
            database.delete_certificate(certificate_id)

        if qr_path and os.path.exists(qr_path):
            os.remove(qr_path)

        flash(f"Approval failed: {error}", "danger")

    return redirect(url_for("admin_submissions"))


# -------------------------------
# DOWNLOAD CERTIFICATE
# -------------------------------

@app.route("/download/<certificate_id>")
@login_required
def download_certificate(certificate_id):

    certificate = database.get_certificate_by_id(certificate_id)

    if not certificate:
        flash("Certificate not found.", "danger")
        return redirect(url_for("index"))

    if session.get("role") == "student":
        if certificate["student_id"] != session["user_id"]:
            flash("You cannot download this certificate.", "danger")
            return redirect(url_for("student_dashboard"))

    elif session.get("role") != "admin":
        flash("Please log in first.", "warning")
        return redirect(url_for("login"))

    return send_file(
        certificate["file_path"],
        as_attachment=True
    )


# -------------------------------
# DOWNLOAD QR CODE
# -------------------------------

@app.route("/qr/<certificate_id>")
@login_required
def download_qr(certificate_id):

    certificate = database.get_certificate_by_id(certificate_id)

    if not certificate:
        flash("Certificate not found.", "danger")
        return redirect(url_for("index"))

    if session.get("role") == "student":
        if certificate["student_id"] != session["user_id"]:
            flash("Unauthorized access.", "danger")
            return redirect(url_for("student_dashboard"))

    elif session.get("role") != "admin":
        return redirect(url_for("login"))

    return send_file(
        certificate["qr_path"],
        as_attachment=True
    )


# -------------------------------
# PUBLIC VERIFICATION BY ID / QR
# -------------------------------

@app.route("/verify/<certificate_id>")
def verify_by_id(certificate_id):

    certificate = database.get_certificate_by_id(certificate_id)

    if not certificate:
        return render_template(
            "verification_result.html",
            result="NOT FOUND",
            certificate_id=certificate_id
        )

    blockchain_data = verify_certificate(certificate_id)

    if not blockchain_data["exists"]:
        result = "NOT FOUND"

    elif blockchain_data["certificate_hash"] != certificate["file_hash"]:
        result = "TAMPERED-MISMATCH"

    else:
        result = "VERIFIED"

    return render_template(
        "verification_result.html",
        result=result,
        certificate=certificate,
        certificate_id=certificate_id,
        blockchain=blockchain_data
    )


# -------------------------------
# PUBLIC VERIFICATION PAGE
# -------------------------------

@app.route("/verify", methods=["GET", "POST"])
def verify():

    if request.method == "POST":

        certificate_id = request.form.get(
            "certificate_id", ""
        ).strip()

        uploaded_file = request.files.get("certificate")

        # Verification using certificate ID
        if certificate_id:
            return redirect(
                url_for(
                    "verify_by_id",
                    certificate_id=certificate_id
                )
            )

        # Verification using uploaded file
        if uploaded_file and uploaded_file.filename:

            if not allowed_file(uploaded_file.filename):
                flash("Unsupported file format.", "danger")
                return redirect(url_for("verify"))

            filename = secure_filename(uploaded_file.filename)
            temp_filename = f"verify_{uuid.uuid4().hex}_{filename}"

            temp_path = config.UPLOAD_FOLDER / temp_filename

            uploaded_file.save(temp_path)

            try:
                uploaded_hash = calculate_file_hash(temp_path)

                connection = database.get_connection()

                certificate = connection.execute(
                    "SELECT * FROM certificates WHERE file_hash = ?",
                    (uploaded_hash,)
                ).fetchone()

                connection.close()

                extracted_text = extract_text(temp_path)

                if certificate:
                    # Exact file is registered - AI double-checks content
                    analysis = analyze_certificate(
                        extracted_text,
                        file_path=temp_path,
                        expected=expected_details(certificate)
                    )

                    return render_template(
                        "verification_result.html",
                        result="VERIFIED",
                        certificate=certificate,
                        certificate_id=certificate["certificate_id"],
                        blockchain=verify_certificate(
                            certificate["certificate_id"]
                        ),
                        analysis=analysis,
                        extracted_text=extracted_text
                    )

                # File is not registered.
                # Find a similar certificate only to provide an optional
                # content comparison. Similarity does not prove alteration.
                closest, closest_score = find_closest_certificate(
                    extracted_text,
                    database.get_all_certificates()
                )

                # Run AI analysis, but do not label the file as tampered
                # just because its hash is not registered.
                analysis = analyze_certificate(
                    extracted_text,
                    file_path=temp_path,
                    expected=expected_details(closest) if closest else None
                )

                return render_template(
                    "verification_result.html",
                    result="NOT REGISTERED",
                    certificate_id=None,
                    certificate=None,
                    blockchain=None,
                    closest_match=closest,
                    closest_score=closest_score,
                    analysis=analysis,
                    extracted_text=extracted_text
                )

            except Exception as error:
                flash(f"Verification failed: {error}", "danger")
                return redirect(url_for("verify"))

            finally:
                if temp_path.exists():
                    temp_path.unlink()

        flash("Enter a certificate ID or upload a certificate.", "warning")

    return render_template("verify.html")


# -------------------------------
# ERROR HANDLERS
# -------------------------------

@app.errorhandler(413)
def file_too_large(error):
    flash("File too large. Maximum allowed size is 10 MB.", "danger")
    return redirect(url_for("verify"))


# -------------------------------
# RUN APPLICATION
# -------------------------------

if __name__ == "__main__":
    app.run(debug=True)
