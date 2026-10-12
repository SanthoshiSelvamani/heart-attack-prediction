"""Heart-disease model: trains a Logistic Regression ONCE and serves predictions.

Same algorithm, same split and same random_state as the original backend.py.
Educational project only - NOT a medical diagnostic tool.
"""
import logging
import os
import threading

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "heart.csv")
TARGET_COLUMN = "target"

# The 13 inputs the original Tkinter app collected. The REAL training order is
# taken from heart.csv and every value is matched to the model BY COLUMN NAME.
EXPECTED_FEATURES = [
    "age", "sex", "cp", "trestbps", "chol", "fbs", "restecg",
    "thalach", "exang", "oldpeak", "slope", "ca", "thal",
]

CATEGORICAL_FEATURES = ["sex", "cp", "fbs", "restecg", "exang", "slope", "ca", "thal"]

# Set to True ONLY after you confirm from your dataset's documentation that
# target 0 = no heart disease and target 1 = heart disease.
# While False, the website shows "Model Class 0 / Model Class 1".
CLASS_MEANING_VERIFIED = False


class ModelError(Exception):
    """Raised for any problem loading the dataset or training/using the model."""


_lock = threading.Lock()
_state = None


def _clean_number(value):
    value = float(value)
    return int(value) if value.is_integer() else value


def _train():
    if not os.path.isfile(CSV_PATH):
        raise ModelError("heart.csv was not found. Put it in the same folder as backend.py.")

    try:
        heart_data = pd.read_csv(CSV_PATH)
    except Exception as exc:  # noqa: BLE001
        raise ModelError("heart.csv could not be read as a CSV file.") from exc

    if TARGET_COLUMN not in heart_data.columns:
        raise ModelError(f"heart.csv has no '{TARGET_COLUMN}' column. Found: {list(heart_data.columns)}")

    feature_columns = [c for c in heart_data.columns if c != TARGET_COLUMN]
    missing = [c for c in EXPECTED_FEATURES if c not in feature_columns]
    extra = [c for c in feature_columns if c not in EXPECTED_FEATURES]
    if missing or extra:
        raise ModelError(
            "heart.csv columns do not match the 13 expected inputs. "
            f"Missing: {missing}. Unexpected: {extra}."
        )

    non_numeric = [c for c in heart_data.columns if not pd.api.types.is_numeric_dtype(heart_data[c])]
    if non_numeric:
        raise ModelError(f"heart.csv has non-numeric columns: {non_numeric}")

    if heart_data.isnull().any().any():
        raise ModelError("heart.csv contains missing values. Clean the dataset first.")

    X = heart_data.drop(columns=TARGET_COLUMN)
    Y = heart_data[TARGET_COLUMN]

    # Held-out test set; the model never sees it while training (no leakage).
    X_train, X_test, Y_train, Y_test = train_test_split(
        X, Y, test_size=0.2, stratify=Y, random_state=2
    )

    model = LogisticRegression()
    model.fit(X_train, Y_train)

    training_accuracy = accuracy_score(Y_train, model.predict(X_train))
    test_accuracy = accuracy_score(Y_test, model.predict(X_test))

    numeric_features = [c for c in feature_columns if c not in CATEGORICAL_FEATURES]
    profile = {
        "numeric_ranges": {
            c: {"min": _clean_number(heart_data[c].min()), "max": _clean_number(heart_data[c].max())}
            for c in numeric_features
        },
        "category_values": {
            c: sorted(_clean_number(v) for v in heart_data[c].unique())
            for c in CATEGORICAL_FEATURES
        },
        "target_counts": {str(k): int(v) for k, v in Y.value_counts().items()},
    }

    logger.info("Model trained on %d rows. Train accuracy %.4f, held-out test accuracy %.4f",
                len(heart_data), training_accuracy, test_accuracy)

    return {
        "model": model,
        "feature_columns": feature_columns,
        "classes": [int(c) for c in model.classes_],
        "training_accuracy": float(training_accuracy),
        "test_accuracy": float(test_accuracy),
        "rows": int(len(heart_data)),
        "profile": profile,
    }


def get_state():
    """Train once (thread-safe) and reuse. Never retrains per request."""
    global _state
    if _state is None:
        with _lock:
            if _state is None:
                _state = _train()
    return _state


def is_ready():
    return _state is not None


def predict_one(values):
    """values: dict of the 13 feature names -> numbers. Returns the model class (int)."""
    state = get_state()
    cols = state["feature_columns"]
    missing = [c for c in cols if c not in values]
    if missing:
        raise ModelError(f"Missing model inputs: {missing}")

    row = pd.DataFrame([[float(values[c]) for c in cols]], columns=cols)
    try:
        return int(state["model"].predict(row)[0])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Prediction failed")
        raise ModelError("The model could not produce a prediction.") from exc


def model_info():
    """Safe, non-sensitive facts about the model for the API/UI."""
    s = get_state()
    return {
        "algorithm": "Logistic Regression (scikit-learn)",
        "feature_order": s["feature_columns"],
        "classes": s["classes"],
        "rows_in_dataset": s["rows"],
        "test_accuracy": round(s["test_accuracy"], 4),
        "test_accuracy_note": "Accuracy on a held-out 20% test split of heart.csv. This is not clinical validation.",
        "class_meaning_verified": CLASS_MEANING_VERIFIED,
        "profile": s["profile"],
    }
