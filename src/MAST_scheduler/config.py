from __future__ import annotations

from pathlib import Path

import tomlkit
from pydantic import BaseModel


class SchedulerConfig(BaseModel):
    autofocus_time: float = 180.0
    readout_time: float = 30.0
    lamp_warmup_time: float = 60.0
    lamp_cooldown_time: float = 60.0
    too_operator_timeout: float = 30.0
    poll_interval: float = 30.0
    twilight_type: str = "astronomical"  # astronomical | nautical | civil

    @classmethod
    def load(cls, path: Path | None = None) -> SchedulerConfig:
        if path is None:
            return cls()
        raw = tomlkit.loads(path.read_text())
        return cls(**raw.get("scheduler", raw))
