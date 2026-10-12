"""Create a doctor account. Run this yourself; doctors cannot sign themselves up.

    python create_doctor.py
"""
import getpass
import sys

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

import MySQL as db  # noqa: E402
import input_rules as rules  # noqa: E402


def ask(prompt, cleaner, message):
    while True:
        value = cleaner(input(prompt))
        if value is not None:
            return value
        print("  ->", message)


def main():
    print("Create a doctor account (the password is not shown while you type)\n")
    name = ask("Full name (e.g. Priya Raman): ", rules.clean_name, rules.NAME_MESSAGE)
    username = ask("Username (e.g. dr.priya): ", rules.clean_username, rules.USERNAME_MESSAGE)
    while True:
        password = getpass.getpass("Password: ")
        problem = rules.password_error(password)
        if problem:
            print("  ->", problem)
            continue
        if password != getpass.getpass("Repeat password: "):
            print("  -> The two passwords do not match.")
            continue
        break
    try:
        db.init_db()
        db.create_user("doctor", name, None, username, generate_password_hash(password))
    except db.DuplicateUser:
        print("\nThat username is already taken. Run the script again with another one.")
        sys.exit(1)
    except (db.DatabaseUnavailable, db.DatabaseError) as exc:
        print("\nCould not create the account:", exc)
        sys.exit(1)
    print(f"\nDone. {name} can sign in at http://127.0.0.1:5000/doctor/login with username '{username}'.")


if __name__ == "__main__":
    main()
