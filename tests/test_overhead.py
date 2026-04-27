from __future__ import annotations

import pytest
from ulid import ULID

from common.models.batches import BatchData
from common.models.calibration import CalibrationSettings
from common.models.highspec import HighspecSettings
from common.models.spectrographs import SpectrographModel

from MAST_scheduler.builder import _compute_setup_overhead
from MAST_scheduler.config import SchedulerConfig

from .conftest import load_plan


def _spec(instrument: str, disperser: str | None = None, lamp_on: bool = False) -> SpectrographModel:
    calibration = CalibrationSettings.model_construct(lamp_on=lamp_on, filter="ND4000" if lamp_on else None)
    settings = HighspecSettings.model_construct(disperser=disperser) if disperser else None
    return SpectrographModel.model_construct(
        instrument=instrument,
        calibration=calibration,
        settings=settings,
    )


def _batch(instrument: str, disperser: str | None = None, lamp_on: bool = False) -> BatchData:
    plan = load_plan("highspec" if instrument == "highspec" else "minimal")
    spec = _spec(instrument, disperser, lamp_on)
    return BatchData.model_construct(
        ulid=ULID(),
        immediate=True,
        plans=[plan],
        spec_assignment=spec,
        exposure_duration=900.0,
        number_of_exposures=1,
        predicted_duration=900.0,
    )


@pytest.fixture
def config() -> SchedulerConfig:
    return SchedulerConfig()


class TestComputeSetupOverhead:
    def test_no_overhead_same_instrument_no_lamp_change(self, config):
        prev = _batch("deepspec")
        nxt = _batch("deepspec")
        assert _compute_setup_overhead(prev, nxt, config) == 0.0

    def test_no_overhead_same_highspec_disperser(self, config):
        prev = _batch("highspec", disperser="Ca")
        nxt = _batch("highspec", disperser="Ca")
        assert _compute_setup_overhead(prev, nxt, config) == 0.0

    def test_spectrograph_switch_deepspec_to_highspec(self, config):
        prev = _batch("deepspec")
        nxt = _batch("highspec", disperser="Ca")
        assert _compute_setup_overhead(prev, nxt, config) == config.spectrograph_switch_time

    def test_spectrograph_switch_highspec_to_deepspec(self, config):
        prev = _batch("highspec", disperser="Ca")
        nxt = _batch("deepspec")
        assert _compute_setup_overhead(prev, nxt, config) == config.spectrograph_switch_time

    def test_grating_stage_move_different_disperser(self, config):
        prev = _batch("highspec", disperser="Ca")
        nxt = _batch("highspec", disperser="Mg")
        assert _compute_setup_overhead(prev, nxt, config) == config.grating_stage_move_time

    def test_lamp_warmup(self, config):
        prev = _batch("deepspec", lamp_on=False)
        nxt = _batch("deepspec", lamp_on=True)
        assert _compute_setup_overhead(prev, nxt, config) == config.lamp_warmup_time

    def test_lamp_cooldown(self, config):
        prev = _batch("deepspec", lamp_on=True)
        nxt = _batch("deepspec", lamp_on=False)
        assert _compute_setup_overhead(prev, nxt, config) == config.lamp_cooldown_time

    def test_combined_switch_and_lamp_warmup(self, config):
        prev = _batch("deepspec", lamp_on=False)
        nxt = _batch("highspec", disperser="Ca", lamp_on=True)
        expected = config.spectrograph_switch_time + config.lamp_warmup_time
        assert _compute_setup_overhead(prev, nxt, config) == expected

    def test_no_lamp_change_when_both_on(self, config):
        prev = _batch("deepspec", lamp_on=True)
        nxt = _batch("deepspec", lamp_on=True)
        assert _compute_setup_overhead(prev, nxt, config) == 0.0
