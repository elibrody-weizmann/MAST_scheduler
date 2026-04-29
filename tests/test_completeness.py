from __future__ import annotations

from MAST_scheduler.filters import ALL_CONSTRAINT_STAGES

from .test_filters import COVERED_CONSTRAINTS


def test_all_constraints_have_suites() -> None:
    missing = ALL_CONSTRAINT_STAGES - COVERED_CONSTRAINTS
    assert not missing, (
        f"Constraints with no test suite: {missing}. "
        "Add a @pytest.mark.constraint_suite class in test_filters.py "
        "and add the stage ID to COVERED_CONSTRAINTS."
    )
