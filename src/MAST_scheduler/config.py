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
    spectrograph_switch_time: float = 120.0
    grating_stage_move_time: float = 30.0
    no_batch_advance_seconds: float = 900.0  # clock skip when no batch is emitted
    # Reject targets below this altitude when no explicit airmass constraint is set.
    # Checked at start, mid-point, and end of the planned observation window.
    min_observable_altitude_deg: float = 10.0

    # Unit-side acquisition + guiding estimate inputs (seconds).
    #
    # These defaults intentionally mirror the current operational settings in the unit
    # configuration DB backups (see `MAST_common/config/backup/mast-config-db.json`) and
    # the fixed sleeps in `MAST_unit`:
    # - `MAST_unit/src/acquirer.py`: `time.sleep(10)` (mount/stage settle) and
    #   `time.sleep(5)` (stage settle)
    # - `MAST_unit/src/solving.py`: `time.sleep(2)` after writing solver results
    unit_acquire_settle_seconds: float = 10.0
    unit_spec_settle_seconds: float = 5.0
    unit_acquisition_exposure_seconds: float = 3.0
    unit_guiding_exposure_seconds: float = 5.0
    unit_guiding_cadence_seconds: float = 30.0
    unit_solver_postprocess_seconds: float = 2.0

    @property
    def acquire_and_guide_seconds(self) -> float:
        """Estimated time for the unit to reach 'guiding' from idle for a new target."""

        return float(
            self.unit_acquire_settle_seconds
            + self.unit_acquisition_exposure_seconds
            + self.unit_solver_postprocess_seconds
            + self.unit_spec_settle_seconds
            + self.unit_guiding_exposure_seconds
            + self.unit_solver_postprocess_seconds
            + self.unit_guiding_cadence_seconds
        )

    @classmethod
    def load(cls, path: Path | None = None) -> SchedulerConfig:
        if path is None:
            return cls()
        raw = tomlkit.loads(path.read_text())
        return cls(**raw.get("scheduler", raw))
