"""Shared input rules for names, phone numbers, usernames and passwords.

Used by the website (app.py) and by create_doctor.py so both follow the same rules.
"""
import re

_NAME_EXTRA = " .'’-"
_PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,49}$")

NAME_MESSAGE = "Enter a name of 2-60 letters. Spaces, hyphens, apostrophes and dots are allowed."
PHONE_MESSAGE = "Enter a valid phone number: 10 to 15 digits, with an optional + at the start."
USERNAME_MESSAGE = "Use 3-50 lowercase letters, digits, dots, dashes or underscores."


def clean_name(value):
    """Return the tidied name, or None if it is not acceptable."""
    if not isinstance(value, str):
        return None
    name = " ".join(value.split())
    if (not 2 <= len(name) <= 60 or not name[0].isalpha()
            or any(not (ch.isalpha() or ch in _NAME_EXTRA) for ch in name)):
        return None
    return name


def clean_phone(value):
    """Remove spaces, dashes, dots and brackets; return the number or None."""
    if not isinstance(value, str):
        return None
    phone = re.sub(r"[\s\-().]", "", value)
    return phone if _PHONE_RE.match(phone) else None


def clean_username(value):
    if not isinstance(value, str):
        return None
    username = value.strip().lower()
    return username if _USERNAME_RE.match(username) else None


def password_error(password, phone=None):
    """Return a message if the password is too weak, otherwise None."""
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        return "Use 8 to 128 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"[0-9]", password):
        return "Include at least one letter and one number."
    if phone and password.replace(" ", "") == phone:
        return "The password must not be your phone number."
    return None
