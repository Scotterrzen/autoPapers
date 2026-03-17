from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class StateStore:
    state_dir: Path
    payload: dict = field(default_factory=dict)

    @property
    def state_path(self) -> Path:
        return self.state_dir / "state.json"

    @classmethod
    def load(cls, state_dir: Path) -> "StateStore":
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / "state.json"
        if state_path.exists():
            with state_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        else:
            payload = {
                "last_success_at": None,
                "processed": {},
                "failures": [],
                "runs": [],
            }
        return cls(state_dir=state_dir, payload=payload)

    def last_success_at(self) -> datetime | None:
        value = self.payload.get("last_success_at")
        if not value:
            return None
        return datetime.fromisoformat(value).astimezone(UTC)

    def has_processed(self, key: str) -> bool:
        return key in self.payload.setdefault("processed", {})

    def mark_processed(self, key: str, metadata: dict) -> None:
        self.payload.setdefault("processed", {})[key] = metadata

    def record_failure(self, key: str, error: str) -> None:
        failures = self.payload.setdefault("failures", [])
        failures.append(
            {
                "key": key,
                "error": error,
                "at": datetime.now(tz=UTC).isoformat(),
            }
        )
        del failures[:-50]

    def record_run(self, summary: dict) -> None:
        runs = self.payload.setdefault("runs", [])
        runs.append(summary)
        del runs[:-30]

    def set_last_success_at(self, value: datetime) -> None:
        self.payload["last_success_at"] = value.astimezone(UTC).isoformat()

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(self.payload, handle, ensure_ascii=False, indent=2)
        temp_path.replace(self.state_path)

