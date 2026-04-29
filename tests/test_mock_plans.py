from __future__ import annotations

from common.models.plans import Plan

from MAST_scheduler.mock_plans import generate_mock_plans
from MAST_scheduler.models import MockPlanGenerateRequest


class TestMockPlanGenerator:
    def test_generation_is_deterministic_with_seed(self):
        req = MockPlanGenerateRequest(count=8, seed=123, preset="balanced")
        first = generate_mock_plans(req)
        second = generate_mock_plans(req)
        assert first.model_dump() == second.model_dump()

    def test_generated_plans_validate_as_common_plan(self):
        req = MockPlanGenerateRequest(
            count=6,
            seed=9,
            preset="constraints-heavy",
            include_constraints=True,
        )
        response = generate_mock_plans(req)
        validated = [Plan.model_validate(item) for item in response.plans]
        assert len(validated) == 6

    def test_long_exposure_preset_stays_within_plan_limits(self):
        req = MockPlanGenerateRequest(
            count=50,
            seed=12,
            preset="long-exposure",
            include_constraints=True,
        )
        response = generate_mock_plans(req)
        validated = [Plan.model_validate(item) for item in response.plans]
        assert len(validated) == 50

    def test_rejects_invalid_count(self):
        req = MockPlanGenerateRequest(count=1)
        req.count = 0
        try:
            generate_mock_plans(req)
        except ValueError as exc:
            assert "count" in str(exc)
        else:
            raise AssertionError("Expected ValueError for invalid count")

    def test_too_plans_have_no_time_window(self):
        # Generate a large batch with a high ToO fraction to ensure we get ToO plans.
        req = MockPlanGenerateRequest(
            count=100,
            seed=42,
            preset="balanced",
            too_fraction=0.5,
            include_constraints=True,
            include_time_windows=True,
        )
        response = generate_mock_plans(req)
        too_plans = [p for p in response.plans if p.get("too")]
        assert too_plans, "Expected at least some ToO plans"
        for plan in too_plans:
            constraints = plan.get("constraints", {})
            assert "time_window" not in constraints, (
                f"ToO plan {plan['ulid']} should not have a time_window"
            )

    def test_non_too_plans_may_have_time_window(self):
        # Non-ToO plans with constraints enabled should still get time windows.
        req = MockPlanGenerateRequest(
            count=100,
            seed=42,
            preset="constraints-heavy",
            too_fraction=0.0,
            include_constraints=True,
            include_time_windows=True,
        )
        response = generate_mock_plans(req)
        plans_with_window = [p for p in response.plans if "time_window" in p.get("constraints", {})]
        assert plans_with_window, "Expected some non-ToO plans to have a time_window"

    def test_all_plans_are_marked_mockup(self):
        response = generate_mock_plans(MockPlanGenerateRequest(count=10, seed=1))
        assert all(p.get("mockup") is True for p in response.plans)

    def test_num_exposures_varies(self):
        req = MockPlanGenerateRequest(count=50, seed=3, num_exposures_range=(2, 8))
        response = generate_mock_plans(req)
        values = {p["target"]["requested_number_of_exposures"] for p in response.plans}
        assert values != {1}, "Expected num_exposures to vary beyond the default 1"
        assert all(2 <= p["target"]["requested_number_of_exposures"] <= 8 for p in response.plans)

    def test_timeout_to_guiding_varies(self):
        req = MockPlanGenerateRequest(count=50, seed=4, timeout_to_guiding_range=(60.0, 300.0))
        response = generate_mock_plans(req)
        values = {p["timeout_to_guiding"] for p in response.plans}
        assert len(values) > 1, "Expected timeout_to_guiding to vary across plans"
        assert all(60.0 <= p["timeout_to_guiding"] <= 300.0 for p in response.plans)

    def test_seeing_constraint_generated(self):
        req = MockPlanGenerateRequest(
            count=50, seed=5, include_constraints=True, include_seeing_constraints=True
        )
        response = generate_mock_plans(req)
        plans_with_seeing = [p for p in response.plans if "seeing" in p.get("constraints", {})]
        assert plans_with_seeing, "Expected some plans to have a seeing constraint"
        for plan in plans_with_seeing:
            assert 1.0 <= plan["constraints"]["seeing"]["max"] <= 4.0

    def test_seeing_constraint_omitted_when_disabled(self):
        req = MockPlanGenerateRequest(
            count=20, seed=5, include_constraints=True, include_seeing_constraints=False
        )
        response = generate_mock_plans(req)
        assert all("seeing" not in p.get("constraints", {}) for p in response.plans)

    def test_autofocus_fraction_respected(self):
        req = MockPlanGenerateRequest(count=100, seed=7, autofocus_fraction=1.0)
        response = generate_mock_plans(req)
        assert all(p.get("autofocus") is True for p in response.plans)

        req_none = MockPlanGenerateRequest(count=50, seed=7, autofocus_fraction=0.0)
        response_none = generate_mock_plans(req_none)
        assert all(not p.get("autofocus") for p in response_none.plans)

    def test_default_generation_omits_calibration(self):
        response = generate_mock_plans(MockPlanGenerateRequest(count=30, seed=7))
        for plan in response.plans:
            spec_assignment = plan.get("spec_assignment", {})
            assert "calibration" not in spec_assignment
