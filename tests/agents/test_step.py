"""Step base class + value types."""

import pytest

from agents.daily_brief.step import StepOutcome, StepOutput, StepStatus


@pytest.mark.unit
def test_step_status_members():
    assert {s.name for s in StepStatus} == {"RAN", "LOADED", "SKIPPED", "FAILED"}


@pytest.mark.unit
def test_step_output_holds_persist_and_value():
    out = StepOutput(persist={"on": "disk"}, value=[1, 2, 3])
    assert out.persist == {"on": "disk"}
    assert out.value == [1, 2, 3]


@pytest.mark.unit
def test_step_outcome_holds_status_and_value():
    oc = StepOutcome(status=StepStatus.RAN, value={"k": 1})
    assert oc.status is StepStatus.RAN
    assert oc.value == {"k": 1}
