"""Read-only checks: heart.csv columns + your existing MySQL tables. Changes nothing."""
import os

import pandas as pd

print("=== 1. heart.csv ===")
try:
    df = pd.read_csv("heart.csv")
    print("Shape (rows, columns):", df.shape)
    print("Columns in order:", list(df.columns))
    print("\nMissing values per column:\n", df.isnull().sum().to_string())
    print("\nTarget counts:\n", df["target"].value_counts().to_string())
    for c in ["sex", "cp", "fbs", "restecg", "exang", "slope", "ca", "thal"]:
        if c in df.columns:
            print(f"Unique values of {c}:", sorted(df[c].unique().tolist()))
except Exception as e:
    print("Could not read heart.csv:", e)

print("\n=== 2. MySQL (read-only) ===")
try:
    import mysql.connector
    from dotenv import load_dotenv

    load_dotenv()
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "Heart_Data"),
    )
    cur = conn.cursor()
    for table in ("data", "patient_records", "users"):
        print(f"\n-- DESCRIBE {table}")
        try:
            cur.execute(f"DESCRIBE {table}")
            for row in cur.fetchall():
                print(row)
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print("Record count:", cur.fetchone()[0])
        except Exception as e:
            print("Not available:", e)
    cur.close()
    conn.close()
except Exception as e:
    print("Could not inspect MySQL:", e)
