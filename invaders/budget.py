"""A hard spending limit for the whole experiment, kept in cost-ledger.json across runs and threads."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    def __init__(self, path: str = "cost-ledger.json", stop_at_usd: float = 1.90, limit_usd: float = 2.0) -> None:
        self.path, self.stop_at, self.limit = path, stop_at_usd, limit_usd
        self._lock = threading.Lock()
        self.session = uuid.uuid4().hex[:8]            # several processes may share the file
        self.data = {"budget_usd": limit_usd, "stop_at_usd": stop_at_usd, "calls": []}
        self.mine: list[dict] = []

    def _others(self, max_age_s: float = 5.0) -> list[dict]:
        """Calls recorded by other processes (re-read from disk at most every few seconds)."""
        now = time.monotonic()
        if now - getattr(self, "_read_at", -1e9) > max_age_s:
            try:
                with open(self.path) as f:
                    calls = json.load(f).get("calls", [])
            except (OSError, ValueError):
                calls = []
            self._cache, self._read_at = [c for c in calls if c.get("session") != self.session], now
        return self._cache

    @property
    def spent(self) -> float:
        """Everything recorded by every process so far, plus this process's unsaved calls."""
        return sum(c.get("cost", 0.0) for c in self._others() + self.mine)

    def check(self) -> None:
        """Call before every paid request."""
        if self.spent >= self.stop_at:
            raise BudgetExceeded(f"spent ${self.spent:.4f}, stopping at ${self.stop_at:.2f} (limit ${self.limit:.2f})")

    def record(self, model: str, cost: float, seconds: float, note: str = "") -> None:
        with self._lock:
            self.mine.append({"model": model, "cost": cost, "s": round(seconds, 3), "note": note, "session": self.session})
            n = len(self.mine)
        if n % 25 == 0:
            self.save()

    def save(self) -> None:
        with self._lock:
            self.data["calls"] = self._others(max_age_s=0) + self.mine
            tmp = f"{self.path}.{self.session}.tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)

    def by_model(self) -> dict:
        out: dict = {}
        for c in self._others() + self.mine:
            m = out.setdefault(c["model"], {"calls": 0, "cost": 0.0})
            m["calls"] += 1
            m["cost"] += c.get("cost", 0.0)
        return out
