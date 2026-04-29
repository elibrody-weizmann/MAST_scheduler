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


def _batch(
    instrument: str,
    disperser: str | None = None,
    lamp_on: bool = False,
    autofocus: bool = False,
) -> BatchData:
    plan = load_plan("highspec" if instrument == "highspec" else "minimal")
    plan.autofocus = autofocus
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
    """Every batch in a prediction pays full cold-start setup; prior state is never trusted."""

    def test_deepspec_no_lamp(self, config):
        nxt = _batch("deepspec")
        overhead, bd = _compute_setup_overhead(nxt, config)
        expected = config.spectrograph_switch_time + config.acquire_and_guide_seconds
        assert overhead == expected
        assert bd.spectrograph_switch_seconds == config.spectrograph_switch_time
        assert bd.grating_move_seconds == 0.0
        assert bd.lamp_warmup_seconds == 0.0
        assert bd.lamp_cooldown_seconds == 0.0
        assert bd.autofocus_seconds == 0.0
        assert bd.acquire_and_guide_seconds == config.acquire_and_guide_seconds
        assert bd.total_seconds == overhead

    def test_highspec_no_lamp(self, config):
        nxt = _batch("highspec", disperser="Ca")
        overhead, bd = _compute_setup_overhead(nxt, config)
        expected = (
            config.spectrograph_switch_time
            + config.grating_stage_move_time
            + config.acquire_and_guide_seconds
        )
        assert overhead == expected
        assert bd.spectrograph_switch_seconds == config.spectrograph_switch_time
        assert bd.grating_move_seconds == config.grating_stage_move_time
        assert bd.lamp_warmup_seconds == 0.0
        assert bd.lamp_cooldown_seconds == 0.0
        assert bd.acquire_and_guide_seconds == config.acquire_and_guide_seconds
        assert bd.total_seconds == overhead

    def test_deepspec_lamp_on(self, config):
        nxt = _batch("deepspec", lamp_on=True)
        overhead, bd = _compute_setup_overhead(nxt, config)
        expected = (
            config.spectrograph_switch_time
            + config.lamp_warmup_time
            + config.acquire_and_guide_seconds
        )
        assert overhead == expected
        assert bd.spectrograph_switch_seconds == config.spectrograph_switch_time
        assert bd.grating_move_seconds == 0.0
        assert bd.lamp_warmup_seconds == config.lamp_warmup_time
        assert bd.lamp_cooldown_seconds == 0.0
        assert bd.acquire_and_guide_seconds == config.acquire_and_guide_seconds
        assert bd.total_seconds == overhead

    def test_highspec_lamp_on(self, config):
        nxt = _batch("highspec", disperser="Ca", lamp_on=True)
        overhead, bd = _compute_setup_overhead(nxt, config)
        expected = (
            config.spectrograph_switch_time
            + config.grating_stage_move_time
            + config.lamp_warmup_time
            + config.acquire_and_guide_seconds
        )
        assert overhead == expected
        assert bd.spectrograph_switch_seconds == config.spectrograph_switch_time
        assert bd.grating_move_seconds == config.grating_stage_move_time
        assert bd.lamp_warmup_seconds == config.lamp_warmup_time
        assert bd.lamp_cooldown_seconds == 0.0
        assert bd.acquire_and_guide_seconds == config.acquire_and_guide_seconds
        assert bd.total_seconds == overhead

    def test_autofocus_added(self, config):
        nxt = _batch("deepspec", autofocus=True)
        overhead, bd = _compute_setup_overhead(nxt, config)
        expected = (
            config.spectrograph_switch_time
            + config.autofocus_time
            + config.acquire_and_guide_seconds
        )
        assert overhead == expected
        assert bd.autofocus_seconds == config.autofocus_time
        assert bd.lamp_cooldown_seconds == 0.0
        assert bd.total_seconds == overhead

    def test_lamp_cooldown_never_charged_when_lamp_off(self, config):
        nxt = _batch("deepspec", lamp_on=False)
        _, bd = _compute_setup_overhead(nxt, config)
        assert bd.lamp_cooldown_seconds == 0.0


class TestComputeTeardown:
    def test_teardown_includes_readout(self, config):
        batch = _batch("deepspec")
        overhead, bd = _compute_teardown(batch, config)
        assert bd.readout_seconds == config.readout_time
        assert bd.total_seconds == config.readout_time
        assert overhead == config.readout_time
