"""MySQL access for the Heart Attack Prediction System.

- Nothing runs when this file is imported; functions are called by app.py.
- Credentials come from environment variables (.env), never from the code.
- Every query is parameterized; every write is one transaction.
- A UNIQUE idempotency key makes retries safe (no duplicate rows).
- Your OLD table `data` is never touched.
  Tables used here: `users` (patients and doctors) and `patient_records`.
"""

import logging
import os
from dotenv import load_dotenv

load_dotenv()

import re

import mysql.connector
from mysql.connector import Error as MySQLError

logger = logging.getLogger(__name__)

RECORDS_TABLE = "patient_records"
USERS_TABLE = "users"
_schema_ready = False


class DatabaseUnavailable(Exception):
    """MySQL cannot be reached (not running, wrong password, wrong host...)."""


class DatabaseError(Exception):
    """Any other database problem. The message is safe to show to users."""


class DuplicateUser(Exception):
    """A user with this phone number or username already exists."""


CREATE_USERS_SQL = f"""
CREATE TABLE IF NOT EXISTS {USERS_TABLE} (
    id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
    role          ENUM('patient','doctor') NOT NULL,
    full_name     VARCHAR(100) NOT NULL,
    phone         VARCHAR(16)  NULL,
    username      VARCHAR(50)  NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_{USERS_TABLE}_phone (phone),
    UNIQUE KEY uq_{USERS_TABLE}_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

CREATE_RECORDS_SQL = f"""
CREATE TABLE IF NOT EXISTS {RECORDS_TABLE} (
    id                INT UNSIGNED NOT NULL AUTO_INCREMENT,
    idempotency_key   CHAR(36)     NOT NULL,
    patient_user_id   INT UNSIGNED NULL,
    patient_name      VARCHAR(100) NOT NULL,
    phone             VARCHAR(16)  NULL,
    registration_date DATE         NOT NULL,
    birth_year        SMALLINT UNSIGNED NOT NULL,
    age               TINYINT UNSIGNED  NOT NULL,
    sex               TINYINT UNSIGNED  NOT NULL,
    cp                TINYINT UNSIGNED  NOT NULL,
    trestbps          SMALLINT UNSIGNED NOT NULL,
    chol              SMALLINT UNSIGNED NOT NULL,
    fbs               TINYINT UNSIGNED  NOT NULL,
    restecg           TINYINT UNSIGNED  NOT NULL,
    thalach           SMALLINT UNSIGNED NOT NULL,
    exang             TINYINT UNSIGNED  NOT NULL,
    oldpeak           DECIMAL(4,2)      NOT NULL,
    slope             TINYINT UNSIGNED  NOT NULL,
    ca                TINYINT UNSIGNED  NOT NULL,
    thal              TINYINT UNSIGNED  NOT NULL,
    smoking           TINYINT UNSIGNED  NULL,
    alcohol           TINYINT UNSIGNED  NULL,
    prediction        TINYINT UNSIGNED  NOT NULL,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_{RECORDS_TABLE}_idempotency (idempotency_key),
    KEY idx_{RECORDS_TABLE}_user (patient_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

INSERT_SQL = f"""
INSERT INTO {RECORDS_TABLE}
    (idempotency_key, patient_user_id, patient_name, phone, registration_date,
     birth_year, age, sex, cp, trestbps, chol, fbs, restecg, thalach, exang,
     oldpeak, slope, ca, thal, smoking, alcohol, prediction)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

RECORD_COLUMNS = ("id, patient_name, phone, registration_date, birth_year, age, sex, cp, "
                  "trestbps, chol, fbs, restecg, thalach, exang, oldpeak, slope, ca, thal, "
                  "smoking, alcohol, prediction, created_at")

_UNAVAILABLE_MSG = ("The database is not reachable. Check that MySQL is running and that "
                    "the settings in your .env file are correct.")


def _db_name():
    name = os.getenv("DB_NAME", "Heart_Data")
    # Database names cannot be sent as query parameters, so only allow safe characters.
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", name):
        raise DatabaseError("DB_NAME in .env may only contain letters, digits and underscores.")
    return name


def _connect(with_database=True):
    try:
        config = {
            "host": os.getenv("DB_HOST", "localhost"),
            "port": int(os.getenv("DB_PORT", "3306")),
            "user": os.getenv("DB_USER", "root"),
            "password": os.getenv("DB_PASSWORD", ""),
            "connection_timeout": 5,
            "charset": "utf8mb4",
        }
        if with_database:
            config["database"] = _db_name()
        return mysql.connector.connect(**config)
    except ValueError as exc:
        raise DatabaseError("DB_PORT in .env must be a number.") from exc
    except MySQLError as exc:
        logger.error("MySQL connection failed: %s", exc)
        raise DatabaseUnavailable(_UNAVAILABLE_MSG) from exc


def ping():
    """True if MySQL accepts a connection. Never raises."""
    try:
        conn = _connect(with_database=False)
    except (DatabaseUnavailable, DatabaseError):
        return False
    conn.close()
    return True


def _column_exists(cur, database, table, column):
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
        (database, table, column),
    )
    return cur.fetchone()[0] > 0


def init_db():
    """Create the database and tables if missing, and add new columns to an older
    patient_records table. Safe to run many times. Never deletes anything."""
    global _schema_ready
    name = _db_name()
    conn = _connect(with_database=False)
    try:
        cur = conn.cursor()
        try:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4")
            cur.execute(f"USE `{name}`")
            cur.execute(CREATE_USERS_SQL)
            cur.execute(CREATE_RECORDS_SQL)
            # Upgrade a table created by the first version of this project.
            if not _column_exists(cur, name, RECORDS_TABLE, "phone"):
                cur.execute(f"ALTER TABLE {RECORDS_TABLE} ADD COLUMN phone VARCHAR(16) NULL AFTER patient_name")
            if not _column_exists(cur, name, RECORDS_TABLE, "patient_user_id"):
                cur.execute(f"ALTER TABLE {RECORDS_TABLE} ADD COLUMN patient_user_id INT UNSIGNED NULL AFTER idempotency_key")
                cur.execute(f"ALTER TABLE {RECORDS_TABLE} ADD INDEX idx_{RECORDS_TABLE}_user (patient_user_id)")
            if not _column_exists(cur, name, RECORDS_TABLE, "alcohol"):
                cur.execute(f"ALTER TABLE {RECORDS_TABLE} ADD COLUMN alcohol TINYINT UNSIGNED NULL AFTER smoking")
            conn.commit()
        finally:
            cur.close()
    except MySQLError as exc:
        logger.error("Could not prepare database: %s", exc)
        raise DatabaseError("The database could not be prepared. Check the MySQL user's permissions.") from exc
    finally:
        conn.close()
    _schema_ready = True


# ------------------------------------------------------------------ users
def create_user(role, full_name, phone, username, password_hash):
    """Insert a patient or doctor. Returns the new user id."""
    if role not in ("patient", "doctor"):
        raise DatabaseError("Unknown role.")
    if not _schema_ready:
        init_db()
    conn = _connect()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                f"INSERT INTO {USERS_TABLE} (role, full_name, phone, username, password_hash) "
                "VALUES (%s, %s, %s, %s, %s)",
                (role, full_name, phone, username, password_hash),
            )
            new_id = cur.lastrowid
            conn.commit()
            return new_id
        except MySQLError as exc:
            conn.rollback()
            if getattr(exc, "errno", None) == 1062:
                raise DuplicateUser() from exc
            logger.error("Could not create user: %s", exc)
            raise DatabaseError("The account could not be created because of a database error.") from exc
        finally:
            cur.close()
    finally:
        conn.close()


def get_user(role, field, value):
    """Find one user by phone (patients) or username (doctors). Returns a dict or None."""
    if field not in ("phone", "username"):
        raise DatabaseError("Unsupported lookup.")
    if not _schema_ready:
        init_db()
    conn = _connect()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                f"SELECT id, role, full_name, phone, username, password_hash FROM {USERS_TABLE} "
                f"WHERE role = %s AND {field} = %s",
                (role, value),
            )
            return cur.fetchone()
        except MySQLError as exc:
            logger.error("User lookup failed: %s", exc)
            raise DatabaseError("The account could not be checked because of a database error.") from exc
        finally:
            cur.close()
    finally:
        conn.close()


# ---------------------------------------------------------------- records
def save_patient_record(record, idempotency_key):
    """Insert one record in a single transaction.

    Returns (record_id, already_saved).
    A repeated request with the same idempotency_key never creates a second row.
    """
    if not _schema_ready:
        init_db()

    values = (
        idempotency_key, record.get("patient_user_id"), record["patient_name"], record.get("phone"),
        record["registration_date"], record["birth_year"], record["age"], record["sex"], record["cp"],
        record["trestbps"], record["chol"], record["fbs"], record["restecg"], record["thalach"],
        record["exang"], record["oldpeak"], record["slope"], record["ca"], record["thal"],
        record.get("smoking"), record.get("alcohol"), record["prediction"],
    )

    conn = _connect()
    try:
        cur = conn.cursor()
        try:
            cur.execute(INSERT_SQL, values)
            new_id = cur.lastrowid
            conn.commit()
            return new_id, False
        except MySQLError as exc:
            conn.rollback()
            if getattr(exc, "errno", None) == 1062:  # duplicate idempotency key
                cur.execute(f"SELECT id FROM {RECORDS_TABLE} WHERE idempotency_key = %s", (idempotency_key,))
                row = cur.fetchone()
                if row:
                    return row[0], True
            logger.error("Insert failed: %s", exc)
            raise DatabaseError("The record could not be saved because of a database error.") from exc
        finally:
            cur.close()
    finally:
        conn.close()


def list_records(search, page, page_size):
    """Doctor view: newest first, optional name/phone search, paged.

    Returns {"records": [...], "total": matching rows, "class_counts": {0: n, 1: n}}.
    """
    if not _schema_ready:
        init_db()
    where, params = "", []
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        where = "WHERE patient_name LIKE %s OR phone LIKE %s"
        params = [like, like]

    conn = _connect()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(f"SELECT COUNT(*) AS n FROM {RECORDS_TABLE} {where}", params)
            total = cur.fetchone()["n"]
            cur.execute(
                f"SELECT {RECORD_COLUMNS} FROM {RECORDS_TABLE} {where} "
                "ORDER BY id DESC LIMIT %s OFFSET %s",
                params + [int(page_size), int((page - 1) * page_size)],
            )
            records = cur.fetchall()
            cur.execute(f"SELECT prediction, COUNT(*) AS n FROM {RECORDS_TABLE} GROUP BY prediction")
            counts = {int(row["prediction"]): int(row["n"]) for row in cur.fetchall()}
            return {"records": records, "total": int(total), "class_counts": counts}
        except MySQLError as exc:
            logger.error("Listing records failed: %s", exc)
            raise DatabaseError("The records could not be loaded because of a database error.") from exc
        finally:
            cur.close()
    finally:
        conn.close()
