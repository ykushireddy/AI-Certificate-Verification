
import sqlite3
from werkzeug.security import generate_password_hash
from config import DATABASE_PATH


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'student')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            certificate_id TEXT UNIQUE NOT NULL,
            student_id INTEGER,
            student_name TEXT NOT NULL,
            course TEXT NOT NULL,
            college TEXT NOT NULL,
            year TEXT NOT NULL,
            register_number TEXT,
            file_path TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            qr_path TEXT,
            blockchain_tx TEXT,
            blockchain_block INTEGER,
            issued_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES users(id),
            FOREIGN KEY(issued_by) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS certificate_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            student_name TEXT NOT NULL,
            course TEXT NOT NULL,
            college TEXT NOT NULL,
            year TEXT NOT NULL,
            register_number TEXT,
            file_path TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            ai_status TEXT,
            ai_risk_score INTEGER,
            status TEXT NOT NULL DEFAULT 'Pending',
            admin_note TEXT,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TIMESTAMP,
            FOREIGN KEY(student_id) REFERENCES users(id)
        )
    """)


    # Add AI analysis columns to databases created before the AI update
    existing = {
        row["name"] for row in cursor.execute("PRAGMA table_info(certificates)")
    }
    for column, column_type in [("ai_status", "TEXT"), ("ai_risk_score", "INTEGER")]:
        if column not in existing:
            cursor.execute(f"ALTER TABLE certificates ADD COLUMN {column} {column_type}")

    # Create default admin account
    cursor.execute(
        "SELECT id FROM users WHERE username = ?",
        ("admin",)
    )

    if cursor.fetchone() is None:
        cursor.execute("""
            INSERT INTO users
            (username, password_hash, full_name, role)
            VALUES (?, ?, ?, ?)
        """, (
            "admin",
            generate_password_hash("admin123"),
            "College Administrator",
            "admin"
        ))

    # Create demo student account
    cursor.execute(
        "SELECT id FROM users WHERE username = ?",
        ("student",)
    )

    if cursor.fetchone() is None:
        cursor.execute("""
            INSERT INTO users
            (username, password_hash, full_name, role)
            VALUES (?, ?, ?, ?)
        """, (
            "student",
            generate_password_hash("student123"),
            "Rahul Kumar",
            "student"
        ))

    connection.commit()
    connection.close()


def get_user_by_username(username):
    connection = get_connection()

    user = connection.execute(
        "SELECT * FROM users WHERE username = ?",
        (username,)
    ).fetchone()

    connection.close()
    return user


def get_all_certificates():
    connection = get_connection()

    certificates = connection.execute(
        "SELECT * FROM certificates ORDER BY created_at DESC"
    ).fetchall()

    connection.close()
    return certificates


def get_certificate_by_id(certificate_id):
    connection = get_connection()

    certificate = connection.execute(
        "SELECT * FROM certificates WHERE certificate_id = ?",
        (certificate_id,)
    ).fetchone()

    connection.close()
    return certificate


def save_certificate(data):
    connection = get_connection()

    connection.execute("""
        INSERT INTO certificates (
            certificate_id,
            student_id,
            student_name,
            course,
            college,
            year,
            register_number,
            file_path,
            file_hash,
            qr_path,
            blockchain_tx,
            blockchain_block,
            issued_by,
            ai_status,
            ai_risk_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["certificate_id"],
        data.get("student_id"),
        data["student_name"],
        data["course"],
        data["college"],
        data["year"],
        data.get("register_number"),
        data["file_path"],
        data["file_hash"],
        data.get("qr_path"),
        data.get("blockchain_tx"),
        data.get("blockchain_block"),
        data.get("issued_by"),
        data.get("ai_status"),
        data.get("ai_risk_score")
    ))

    connection.commit()
    connection.close()


def update_certificate_blockchain(certificate_id, transaction_hash, block_number):
    connection = get_connection()
    connection.execute("""
        UPDATE certificates
        SET blockchain_tx = ?, blockchain_block = ?
        WHERE certificate_id = ?
    """, (transaction_hash, block_number, certificate_id))
    connection.commit()
    connection.close()


def delete_certificate(certificate_id):
    connection = get_connection()
    connection.execute(
        "DELETE FROM certificates WHERE certificate_id = ?",
        (certificate_id,)
    )
    connection.commit()
    connection.close()

def create_student(username, password, full_name):
    connection = get_connection()

    try:
        cursor = connection.execute("""
            INSERT INTO users (username, password_hash, full_name, role)
            VALUES (?, ?, ?, ?)
        """, (
            username,
            generate_password_hash(password),
            full_name,
            "student"
        ))

        connection.commit()
        return cursor.lastrowid

    finally:
        connection.close()

def save_submission(data):
    connection = get_connection()

    try:
        cursor = connection.execute("""
            INSERT INTO certificate_submissions (
                student_id, student_name, course, college,
                year, register_number, file_path, file_hash,
                ai_status, ai_risk_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["student_id"],
            data["student_name"],
            data["course"],
            data["college"],
            data["year"],
            data.get("register_number"),
            data["file_path"],
            data["file_hash"],
            data.get("ai_status"),
            data.get("ai_risk_score")
        ))

        connection.commit()
        return cursor.lastrowid

    finally:
        connection.close()


def get_student_submissions(student_id):
    connection = get_connection()

    submissions = connection.execute("""
        SELECT * FROM certificate_submissions
        WHERE student_id = ?
        ORDER BY submitted_at DESC
    """, (student_id,)).fetchall()

    connection.close()
    return submissions


def get_all_submissions():
    connection = get_connection()

    submissions = connection.execute("""
        SELECT s.*, u.username
        FROM certificate_submissions s
        JOIN users u ON s.student_id = u.id
        ORDER BY s.submitted_at DESC
    """).fetchall()

    connection.close()
    return submissions


def get_submission_by_id(submission_id):
    connection = get_connection()

    submission = connection.execute("""
        SELECT * FROM certificate_submissions
        WHERE id = ?
    """, (submission_id,)).fetchone()

    connection.close()
    return submission


def update_submission_status(submission_id, status, admin_note=None):
    connection = get_connection()

    connection.execute("""
        UPDATE certificate_submissions
        SET status = ?, admin_note = ?,
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, admin_note, submission_id))

    connection.commit()
    connection.close()
