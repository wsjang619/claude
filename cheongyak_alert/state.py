from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path


class State:
    """이미 알린 공고를 기억한다. {"seen": {key: {"title", "first_seen", "reminded"}}}"""

    def __init__(self, path: Path):
        self.path = path
        self.seen: dict[str, dict] = {}
        self.meta: dict[str, str] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.seen, self.meta = data.get("seen", {}), data.get("meta", {})

    def is_seen(self, key: str) -> bool:
        return key in self.seen

    def is_reminded(self, key: str) -> bool:
        return bool(self.seen.get(key, {}).get("reminded"))

    def mark_seen(self, key: str, title: str, today: date) -> None:
        self.seen.setdefault(key, {"title": title, "first_seen": today.isoformat(), "reminded": False})

    def mark_reminded(self, key: str) -> None:
        if key in self.seen:
            self.seen[key]["reminded"] = True

    def sent_today(self, name: str, today: date) -> bool:
        return self.meta.get(name) == today.isoformat()

    def mark_sent(self, name: str, today: date) -> None:
        self.meta[name] = today.isoformat()

    def save(self, today: date, keep_days: int = 400) -> None:
        cutoff = (today - timedelta(days=keep_days)).isoformat()
        self.seen = {k: v for k, v in self.seen.items() if v.get("first_seen", "9999") >= cutoff}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"seen": self.seen, "meta": self.meta}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
