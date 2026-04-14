#!/usr/bin/env python3
import argparse
import csv
import json
import os
import pickle
import sys
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from analyzers.developer_classifier import DeveloperClassifier
from core.miner import RepositoryMiner
from models.schemas import Developer


def parse_dt(value: str) -> Optional[datetime]:
    v = (value or "").strip()
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def normalize_label(raw: str) -> Optional[str]:
    v = (raw or "").strip().lower()
    if not v:
        return None
    mapping = {
        "se": "Software Engineer",
        "software engineer": "Software Engineer",
        "se-engineer": "Software Engineer",
        "software_engineer": "Software Engineer",
        "ai": "AI-Engineer",
        "ai-engineer": "AI-Engineer",
        "ai_engineer": "AI-Engineer",
        "hybrid": "Hybrid",
        "unknown": "Unknown",
    }
    return mapping.get(v)


def filter_commits(commits, start: Optional[datetime], end: Optional[datetime]):
    if not start and not end:
        return list(commits)
    out = []
    for c in commits:
        if start and c.date < start:
            continue
        if end and c.date >= end:
            continue
        out.append(c)
    return out


def build_dataset(labels_csv: str) -> Tuple[List[List[float]], List[str], List[str], List[Dict[str, str]], List[str]]:
    clf = DeveloperClassifier(model_path="")
    feature_names = clf.get_feature_names()

    rows: List[Dict[str, str]] = []
    with open(labels_csv, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})

    if not rows:
        raise ValueError("No rows found in labels CSV.")

    required = {"repo_path", "developer_id", "label"}
    missing = [k for k in required if k not in rows[0]]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    repo_commits_cache: Dict[str, List] = {}
    feature_cache: Dict[Tuple[str, str, str], Dict[str, List[float]]] = {}

    X: List[List[float]] = []
    y: List[str] = []
    groups: List[str] = []
    accepted_rows: List[Dict[str, str]] = []
    skipped: List[str] = []

    for idx, r in enumerate(rows, start=2):
        repo_path = r.get("repo_path", "")
        dev_id = r.get("developer_id", "")
        label = normalize_label(r.get("label", ""))
        if not repo_path or not dev_id or not label:
            skipped.append(f"line {idx}: missing repo_path/developer_id/label")
            continue
        if not os.path.isdir(repo_path):
            skipped.append(f"line {idx}: repo_path not found ({repo_path})")
            continue

        start_raw = r.get("window_start", "") or r.get("start_date", "")
        end_raw = r.get("window_end", "") or r.get("end_date", "")
        start = parse_dt(start_raw)
        end = parse_dt(end_raw)
        cache_key = (repo_path, start_raw, end_raw)

        if cache_key not in feature_cache:
            if repo_path not in repo_commits_cache:
                miner = RepositoryMiner(repo_path)
                repo_commits_cache[repo_path] = miner.list_commits()

            commits = filter_commits(repo_commits_cache[repo_path], start, end)
            dev_ids = sorted({c.author_id for c in commits if c.author_id})
            devs = [Developer(id=d) for d in dev_ids]
            ids, matrix = clf.build_training_matrix(devs, commits, repo_root=repo_path, feature_names=feature_names)
            feature_cache[cache_key] = {d: vec for d, vec in zip(ids, matrix)}

        vec = feature_cache[cache_key].get(dev_id)
        if vec is None:
            skipped.append(f"line {idx}: developer_id not active in selected window ({dev_id})")
            continue

        X.append(vec)
        y.append(label)
        groups.append(repo_path)
        accepted_rows.append(r)

    if not X:
        raise ValueError("No usable training rows after validation/filtering.")

    if skipped:
        print(f"Skipped {len(skipped)} rows.")
        for s in skipped[:20]:
            print(f"  - {s}")
        if len(skipped) > 20:
            print(f"  ... and {len(skipped) - 20} more")

    return X, y, groups, accepted_rows, feature_names


def train_model(X, y, groups):
    try:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import classification_report, confusion_matrix
        from sklearn.model_selection import GroupShuffleSplit
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as e:
        raise RuntimeError(f"Missing training dependency scikit-learn: {e}")

    label_counts = Counter(y)
    if len(label_counts) < 2:
        raise ValueError("Need at least 2 label classes for training.")

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(splitter.split(X, y, groups=groups))
    X_train = [X[i] for i in train_idx]
    y_train = [y[i] for i in train_idx]
    X_test = [X[i] for i in test_idx]
    y_test = [y[i] for i in test_idx]

    pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(max_iter=1500, class_weight="balanced", n_jobs=None)),
        ]
    )
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)
    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_test, y_pred, labels=sorted(list(set(y))))

    # Refit on full dataset for final artifact.
    pipeline.fit(X, y)
    return pipeline, report, cm.tolist(), sorted(list(set(y))), dict(label_counts)


def main():
    ap = argparse.ArgumentParser(description="Train developer role classifier model (SE/AI/Hybrid/Unknown).")
    ap.add_argument("--labels-csv", required=True, help="CSV with columns: repo_path, developer_id, label, window_start(optional), window_end(optional)")
    ap.add_argument("--output-model", default="models/developer_role/model.pkl", help="Output pickle path")
    ap.add_argument("--report-json", default="models/developer_role/training_report.json", help="Evaluation report JSON path")
    ap.add_argument("--min-confidence", type=float, default=0.48, help="Default confidence threshold stored in model artifact")
    ap.add_argument("--hybrid-margin", type=float, default=0.12, help="Default AI/SE probability delta to classify as Hybrid")
    args = ap.parse_args()

    X, y, groups, accepted_rows, feature_names = build_dataset(args.labels_csv)
    model, report, cm, labels, label_counts = train_model(X, y, groups)

    model_dir = os.path.dirname(os.path.abspath(args.output_model))
    os.makedirs(model_dir, exist_ok=True)
    bundle = {
        "model": model,
        "feature_names": feature_names,
        "labels": labels,
        "label_counts": label_counts,
        "training_rows": len(accepted_rows),
        "min_confidence": float(args.min_confidence),
        "hybrid_margin": float(args.hybrid_margin),
        "created_at": datetime.now().isoformat(),
    }
    with open(args.output_model, "wb") as f:
        pickle.dump(bundle, f)

    report_payload = {
        "labels": labels,
        "label_counts": label_counts,
        "training_rows": len(accepted_rows),
        "classification_report": report,
        "confusion_matrix": cm,
    }
    report_dir = os.path.dirname(os.path.abspath(args.report_json))
    os.makedirs(report_dir, exist_ok=True)
    with open(args.report_json, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    print(f"Model saved to: {os.path.abspath(args.output_model)}")
    print(f"Report saved to: {os.path.abspath(args.report_json)}")
    print(f"Rows used: {len(accepted_rows)}")
    print(f"Label counts: {label_counts}")


if __name__ == "__main__":
    main()
