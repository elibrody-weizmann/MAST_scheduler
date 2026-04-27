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

    def test_rejects_invalid_count(self):
        req = MockPlanGenerateRequest(count=1)
        req.count = 0
        try:
            generate_mock_plans(req)
        except ValueError as exc:
            assert "count" in str(exc)
        else:
            raise AssertionError("Expected ValueError for invalid count")

    def test_default_generation_omits_calibration(self):
        response = generate_mock_plans(MockPlanGenerateRequest(count=30, seed=7))
        for plan in response.plans:
            spec_assignment = plan.get("spec_assignment", {})
            assert "calibration" not in spec_assignment
