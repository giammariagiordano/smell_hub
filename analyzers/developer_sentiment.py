from __future__ import annotations

import os
import json
import hashlib
from typing import Dict, List, Optional

import pandas as pd

from models.schemas import Commit, Developer


class DeveloperSentimentAnalyzer:
    LABELS = ["Anger", "Fear", "Sadness", "Love", "Joy", "Surprise"]
    NEGATIVE = ["Anger", "Fear", "Sadness"]
    POSITIVE = ["Love", "Joy"]

    def __init__(self, emotion_root: str):
        self.emotion_root = emotion_root
        self.model_dir = os.path.join(emotion_root, "models", "bert_multilabel")
        self.train_file = os.path.join(emotion_root, "datasets", "github-train.csv")
        self.test_file = os.path.join(emotion_root, "datasets", "github-test.csv")
        self.meta_file = os.path.join(self.model_dir, "training_meta.json")
        self.last_status = "Not started"
        self.last_error: Optional[str] = None
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._sentiment_cache: Dict[str, Dict[str, float]] = {}  # h(text) -> emotions dict

    @staticmethod
    def emotions_to_sentiment(emotions: Dict[str, float]) -> float:
        pos = sum(float(emotions.get(k, 0.0)) for k in DeveloperSentimentAnalyzer.POSITIVE) / max(
            len(DeveloperSentimentAnalyzer.POSITIVE), 1
        )
        neg = sum(float(emotions.get(k, 0.0)) for k in DeveloperSentimentAnalyzer.NEGATIVE) / max(
            len(DeveloperSentimentAnalyzer.NEGATIVE), 1
        )
        return pos - neg

    @staticmethod
    def sentiment_label(score: float) -> str:
        if score > 0.15:
            return "Positive"
        if score < -0.15:
            return "Negative"
        return "Neutral"

    def _load_runtime(self) -> bool:
        try:
            import torch  # type: ignore
            from transformers import AutoModelForSequenceClassification, AutoTokenizer  # type: ignore

            self._torch = torch
            self._AutoTokenizer = AutoTokenizer
            self._AutoModelForSequenceClassification = AutoModelForSequenceClassification
            return True
        except Exception as e:
            self.last_error = f"Missing sentiment dependencies (torch/transformers): {e}"
            self.last_status = "Unavailable"
            return False

    def _model_exists(self) -> bool:
        return (
            os.path.isdir(self.model_dir)
            and os.path.exists(os.path.join(self.model_dir, "config.json"))
            and os.path.exists(os.path.join(self.model_dir, "tokenizer_config.json"))
        )

    def ensure_model_trained(self) -> bool:
        target_rows = int(os.environ.get("DEV_SENTIMENT_TRAIN_LIMIT", "1200"))
        if self._model_exists():
            trained_rows = 0
            if os.path.exists(self.meta_file):
                try:
                    with open(self.meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    trained_rows = int(meta.get("trained_rows", 0))
                except Exception:
                    trained_rows = 0

            if trained_rows >= target_rows:
                self.last_status = "Sentiment model ready"
                return True

        if not self._load_runtime():
            return False
        if not os.path.exists(self.train_file) or not os.path.exists(self.test_file):
            self.last_status = "Unavailable"
            self.last_error = "Sentiment training datasets not found."
            return False

        self.last_status = "Training sentiment BERT (first run)"

        torch = self._torch
        tokenizer = self._AutoTokenizer.from_pretrained("bert-base-uncased")
        model = self._AutoModelForSequenceClassification.from_pretrained(
            "bert-base-uncased",
            num_labels=len(self.LABELS),
            problem_type="multi_label_classification",
        )

        train_df = pd.read_csv(self.train_file, encoding='utf-8')
        test_df = pd.read_csv(self.test_file, encoding='utf-8')

        # Keep training bounded to avoid stalling analysis on first run.
        max_train = target_rows
        if len(train_df) > max_train:
            train_df = train_df.sample(n=max_train, random_state=42)

        class EmotionDataset(torch.utils.data.Dataset):
            def __init__(self, frame):
                self.frame = frame.reset_index(drop=True)

            def __len__(self):
                return len(self.frame)

            def __getitem__(self, idx):
                row = self.frame.iloc[idx]
                text = str(row.get("Text", ""))
                encoded = tokenizer(
                    text,
                    truncation=True,
                    padding="max_length",
                    max_length=128,
                    return_tensors="pt",
                )
                labels = torch.tensor(
                    [float(row.get(col, 0)) for col in DeveloperSentimentAnalyzer.LABELS],
                    dtype=torch.float,
                )
                return {
                    "input_ids": encoded["input_ids"].squeeze(0),
                    "attention_mask": encoded["attention_mask"].squeeze(0),
                    "labels": labels,
                }

        train_ds = EmotionDataset(train_df)
        test_ds = EmotionDataset(test_df)

        batch_size = int(os.environ.get("DEV_SENTIMENT_BATCH_SIZE", "16"))
        epochs = int(os.environ.get("DEV_SENTIMENT_EPOCHS", "1"))
        lr = float(os.environ.get("DEV_SENTIMENT_LR", "2e-5"))

        train_loader = torch.utils.data.DataLoader(train_ds, batch_size=batch_size, shuffle=True)
        eval_loader = torch.utils.data.DataLoader(test_ds, batch_size=batch_size, shuffle=False)

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr)

        for _ in range(epochs):
            model.train()
            for batch in train_loader:
                optimizer.zero_grad()
                input_ids = batch["input_ids"].to(device)
                attention_mask = batch["attention_mask"].to(device)
                labels = batch["labels"].to(device)
                out = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
                out.loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()

            # Lightweight eval pass for sanity.
            model.eval()
            with torch.no_grad():
                for batch in eval_loader:
                    input_ids = batch["input_ids"].to(device)
                    attention_mask = batch["attention_mask"].to(device)
                    labels = batch["labels"].to(device)
                    _ = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
                    break

        os.makedirs(self.model_dir, exist_ok=True)
        model.save_pretrained(self.model_dir)
        tokenizer.save_pretrained(self.model_dir)
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump({
                "trained_rows": int(len(train_df)),
                "epochs": int(epochs),
                "batch_size": int(batch_size),
                "labels": list(self.LABELS),
            }, f, indent=2)
        self.last_status = "Sentiment model trained"
        self.last_error = None
        return True

    def _ensure_loaded(self) -> bool:
        if not self._load_runtime():
            return False
        if self._model is not None and self._tokenizer is not None:
            return True
        if not self._model_exists():
            return False
        self._tokenizer = self._AutoTokenizer.from_pretrained(self.model_dir)
        self._model = self._AutoModelForSequenceClassification.from_pretrained(self.model_dir)
        return True

    def analyze_developers(self, developers: List[Developer], commits: List[Commit]) -> None:
        for dev in developers:
            dev.sentiment_score = 0.0
            dev.sentiment_label = "Unknown"
            dev.sentiment_messages_count = 0
            dev.sentiment_emotions = {}

        if not commits:
            self.last_status = "No commits in window"
            return

        if not self.ensure_model_trained():
            return
        if not self._ensure_loaded():
            self.last_status = "Sentiment model not available"
            return

        torch = self._torch
        tokenizer = self._tokenizer
        model = self._model
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)
        model.eval()

        by_dev: Dict[str, List[str]] = {}
        max_msgs = int(os.environ.get("DEV_SENTIMENT_MAX_MSG_PER_DEV", "120"))
        for c in sorted(commits, key=lambda x: x.date):
            if not c.author_id:
                continue
            msg = (c.message or "").strip()
            if not msg:
                continue
            rows = by_dev.setdefault(c.author_id, [])
            if len(rows) < max_msgs:
                rows.append(msg[:600])

        dev_map = {d.id: d for d in developers}
        uncached_messages: List[str] = []
        uncached_hashes: List[str] = []
        seen_uncached = set()
        for messages in by_dev.values():
            for msg in messages:
                msg_hash = hashlib.sha256(msg.encode("utf-8")).hexdigest()
                if msg_hash in self._sentiment_cache or msg_hash in seen_uncached:
                    continue
                seen_uncached.add(msg_hash)
                uncached_messages.append(msg)
                uncached_hashes.append(msg_hash)

        if uncached_messages:
            batch_size = int(os.environ.get("DEV_SENTIMENT_INFER_BATCH_SIZE", "64"))
            with torch.no_grad():
                for i in range(0, len(uncached_messages), batch_size):
                    chunk = uncached_messages[i : i + batch_size]
                    chunk_hashes = uncached_hashes[i : i + batch_size]
                    enc = tokenizer(
                        chunk,
                        truncation=True,
                        padding=True,
                        max_length=128,
                        return_tensors="pt",
                    )
                    out = model(
                        input_ids=enc["input_ids"].to(device),
                        attention_mask=enc["attention_mask"].to(device),
                    )
                    probs = torch.sigmoid(out.logits).cpu().numpy()
                    for msg_hash, score_row in zip(chunk_hashes, probs.tolist()):
                        self._sentiment_cache[msg_hash] = {
                            label: float(score_row[idx]) for idx, label in enumerate(self.LABELS)
                        }

        for dev_id, messages in by_dev.items():
            dev = dev_map.get(dev_id)
            if not dev or not messages:
                continue

            all_scores = []
            for msg in messages:
                msg_hash = hashlib.sha256(msg.encode("utf-8")).hexdigest()
                emotions = self._sentiment_cache.get(msg_hash)
                if not emotions:
                    continue
                all_scores.append([float(emotions[label]) for label in self.LABELS])

            if not all_scores:
                continue

            means = [sum(col) / len(col) for col in zip(*all_scores)]
            emotions = {label: float(round(means[idx], 4)) for idx, label in enumerate(self.LABELS)}
            score = float(round(self.emotions_to_sentiment(emotions), 4))

            dev.sentiment_emotions = emotions
            dev.sentiment_score = score
            dev.sentiment_label = self.sentiment_label(score)
            dev.sentiment_messages_count = len(messages)

        self.last_status = "Sentiment computed"
