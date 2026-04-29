from __future__ import annotations

import pytest
from common.models.batches import BatchData
from common.models.calibration import CalibrationSettings
from common.models.highspec import HighspecSettings
from common.models.spectrographs import SpectrographModel
from ulid import ULID

from MAST_scheduler.builder import _compute_setup_overhead, _compute_teardown
from MAST_scheduler.config import SchedulerConfig

from .conftest import load_plan


def _spec(
    instrument: str, disperser: str | None = None, lamp_on: bool = False
) -> SpectrographModel:
    calibration = CalibrationSettings.model_construct(
        lamp_on=lamp_on, filter="ND4000" if lamp_on else None
    )
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
        overhead, _ = _compute_setup_overhead(prev, nxt, config)
        assert overhead ==0.0

    def test_no_overhead_same_highspec_disperser(self, config):
        prev = _batch("highspec", disperser="Ca")
        nxt = _batch("highspec", disperser="Ca")
        overhead, _ = _compute_setup_overhead(prev, nxt, config)
        assert overhead ==0.0

    def test_spectrograph_switch_deepspec_to_highspec(self, config):
        prev = _batch("deepspec")
        nxt = _batch("highspec", disperser="Ca")
        overhead, _ = _compute_setup_overhead(prev, nxt, config)
        assert overhead ==config.spectrograph_switch_time

    def test_spectrograph_switch_highspec_to_deepspec(self, config):
        prev = _batch("highspec", disperser="Ca")
        nxt = _batch("deepspec")
        overhead, _ = _compute_setup_overhead(prev, nxt, config)
        assert overhead ==config.spectrograph_switch_time

    def test_grating_stage_move_different_disperser(self, config):
        prev = _batch("highspec", disperser="Ca")
        nxt = _batch("highspec", disperser="Mg")
        overhead, _ = _compute_setup_overhead(prev, nxt, config)
        assert overhead ==config.grating_stage_move_time

    def test_lamp_warmup(self, config):
        prev = _batch("deepspec", lamp_on=False)
        nxt = _batch("deepspec", lamp_on=True)
        overhead, _ = _compute_setup_overhead(prev, nxt, config)
        assert overhead ==config.lamp_warmup_time

    def test_lamp_cooldown(self, config):
        prev = _batch("deepspec", lamp_on=True)
        nxt = _batch("deepspec", lamp_on=False)
        overhead, _ = _compute_setup_overhead(prev, nxt, config)
        assert overhead ==config.lamp_cooldown_time

    def test_combined_switch_and_lamp_warmup(self, config):
        prev = _batch("deepspec", lamp_on=False)
        nxt = _batch("highspec", disperser="Ca", lamp_on=True)
        expected = config.spectrograph_switch_time + config.lamp_warmup_time
        overhead, _ = _compute_setup_overhead(prev, nxt, config)
        assert overhead ==expected

    def test_no_lamp_change_when_both_on(self, config):
        prev = _batch("deepspec", lamp_on=True)
        nxt = _batch("deepspec", lamp_on=True)
        overhead, _ = _compute_setup_overhead(prev, nxt, config)
        assert overhead == 0.0

    def test_setup_breakdown_fields(self, config):
        prev = _batch("deepspec", lamp_on=False)
        nxt = _batch("highspec", disperser="Ca", lamp_on=True)
        overhead, bd = _compute_setup_overhead(prev, nxt, config)
        assert bd.spectrograph_switch_seconds == config.spectrograph_switch_time
        assert bd.lamp_warmup_seconds == config.lamp_warmup_time
        assert bd.grating_move_seconds == 0.0
        assert bd.autofocus_seconds == 0.0
        assert bd.total_seconds == overhead

    def test_setup_breakdown_grating_move(self, config):
        prev = _batch("highspec", disperser="Ca")
        nxt = _batch("highspec", disperser="Mg")
        overhead, bd = _compute_setup_overhead(prev, nxt, config)
        assert bd.grating_move_seconds == config.grating_stage_move_time
        assert bd.total_seconds == overhead


class TestComputeTeardown:
    def test_teardown_includes_readout(self, config):
        batch = _batch("deepspec")
        overhead, bd = _compute_teardown(batch, config)
        assert bd.readout_seconds == config.readout_time
        assert bd.total_seconds == config.readout_time
        assert overhead == config.readout_time
