# Heart Attack Prediction System (Flask website)

Educational project. Predictions are NOT a medical diagnosis.

## Who can do what
| Account | How it is created | Pages | Can do |
|---|---|---|---|
| Patient | Signs up at `/register` with name, phone number and password | `/login`, `/register`, `/` | ONLY run and save a heart assessment |
| Doctor | Created by you with `python create_doctor.py` (no public sign-up) | `/doctor/login`, `/doctor` | ONLY view saved patient records (search by name or phone) |

A patient cannot open the doctor pages or the doctor API, and a doctor cannot run or save assessments.
The patient's name and phone number always come from their account (the browser cannot change them).

## How it fits together
- Browser: `templates/*.html`, `static/css/style.css`, `static/js/app.js` (assessment), `auth.js` (sign-in pages), `doctor.js` (dashboard). It talks only to Flask with `fetch()`.
- `app.py`: pages, sign-in, role checks, validation, prediction API, records API, CSRF protection.
- `backend.py`: your Logistic Regression, trained ONCE from `heart.csv` at startup.
- `MySQL.py`: users + records, parameterized queries, one transaction per write, no duplicate on retry.
- `input_rules.py`: shared rules for names, phone numbers, usernames and passwords.

## Folder
```
heart-attack-prediction/
├── app.py  backend.py  MySQL.py  input_rules.py  create_doctor.py  check_setup.py
├── heart.csv            <- YOU copy your own file here
├── requirements.txt  .env.example  .gitignore
├── templates/  index.html  auth.html  doctor.html
└── static/  css/style.css   js/app.js  js/auth.js  js/doctor.js   img/heart-bg.svg
```

## Setup on Windows (VS Code terminal, inside the project folder)
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
1. Copy your `heart.csv` into the project folder.
2. Open `.env` and fill in MySQL user, password and SECRET_KEY
   (make one with: `python -c "import secrets; print(secrets.token_hex(32))"`).
3. If PowerShell blocks `activate`, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
4. Optional read-only check: `python check_setup.py`
5. Create your first doctor account: `python create_doctor.py` (it asks for name, username, password)
6. Start the site: `python app.py` then open http://127.0.0.1:5000

## Database
- Your old table `Heart_Data.data` is never touched.
- New tables are created automatically on first start: `users` and `patient_records`.
- If you ran the earlier version, `patient_records` is upgraded in place (new `phone` and
  `patient_user_id` and `alcohol` columns are added; no rows are deleted). Older records show "Not recorded" for phone.
- Smoker and Alcohol are optional extra information saved with each record; they are NOT model inputs.
- Passwords are stored only as salted hashes, never as plain text.

## Security notes
- Wrong password 5 times for the same account on the same computer: locked for 10 minutes.
- Signed out automatically after 2 idle hours. Pages are not cached, so Back does not show private data after logout.
- Before putting this on the internet: use HTTPS and set `COOKIE_SECURE=1` in `.env`.
  Real patient data also needs proper legal/privacy review. This is an educational project.
- Every doctor can see every record. Add per-doctor restrictions or an access log if you need them.

## Assumptions to confirm
1. Sex coding: Male = 1, Female = 0.
2. `ca` and `thal` choices are read from YOUR heart.csv.
3. Result shows "Model Class 0/1" until you set `CLASS_MEANING_VERIFIED = True` in `backend.py`.
4. Phone numbers: 10 to 15 digits, optional leading +; spaces/dashes are removed. `09876543210`
   and `9876543210` are treated as different numbers.
5. Age = this year minus birth year.
6. Charts load Chart.js from the internet.

## Test checklist
1. Open http://127.0.0.1:5000 : you land on Patient sign in.
2. Sign up with a name, phone and password; you arrive at the assessment page with name and phone filled in.
3. Predict, check the charts, Save, then Log out.
4. Sign in again with the phone number and password.
5. While signed in as a patient, open http://127.0.0.1:5000/doctor : you are sent back to the assessment page.
6. Open `/doctor/login`, sign in with the doctor account: you see the saved record; try the search box and View.
7. As doctor, open `/` : you are sent to the dashboard.
8. Enter a wrong password 5 times: the 6th attempt says to wait 10 minutes.
9. In MySQL: `SELECT id, role, full_name, phone, username FROM Heart_Data.users;`

## Troubleshooting
- `ModuleNotFoundError`: activate the venv (`venv\Scripts\activate`) and run `pip install -r requirements.txt`.
- `Access denied for user` / `Can't connect`: check `.env` and that the MySQL service is running.
- Sign-in says the database is not reachable: MySQL is stopped or `.env` is wrong.
- "Security check failed": refresh the page.
- Forgot a doctor password: run `python create_doctor.py` with a new username, or ask me for a password-reset script.
- A ConvergenceWarning in the terminal is normal for this model setup.
