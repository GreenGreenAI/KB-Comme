"""Bank-neutral, user-recorded consultation lifecycle rules."""

from __future__ import annotations

from typing import Final

READY: Final = "ready_for_manual_handoff"
SHARED: Final = "shared_manually"
IN_PROGRESS: Final = "consultation_in_progress"
MORE_INFORMATION: Final = "additional_information_requested"
OUTCOME_RECORDED: Final = "outcome_recorded"

CONSULTATION_STATUSES: Final = frozenset(
    {READY, SHARED, IN_PROGRESS, MORE_INFORMATION, OUTCOME_RECORDED}
)

ALLOWED_TRANSITIONS: Final = {
    READY: frozenset({SHARED}),
    SHARED: frozenset({IN_PROGRESS, MORE_INFORMATION, OUTCOME_RECORDED}),
    IN_PROGRESS: frozenset({MORE_INFORMATION, OUTCOME_RECORDED}),
    MORE_INFORMATION: frozenset({SHARED, IN_PROGRESS, OUTCOME_RECORDED}),
    OUTCOME_RECORDED: frozenset(),
}


def validate_transition(previous: str | None, next_status: str) -> None:
    """Reject invented or out-of-order bank states."""
    if next_status not in CONSULTATION_STATUSES:
        raise ValueError(f"unsupported consultation status: {next_status}")
    if previous is None:
        if next_status != READY:
            raise ValueError("consultation must start ready for manual handoff")
        return
    if next_status not in ALLOWED_TRANSITIONS[previous]:
        raise ValueError(
            f"consultation cannot transition from {previous} to {next_status}"
        )


def validate_event_details(
    status: str,
    note: str,
    requested_items: tuple[str, ...],
) -> None:
    if status == MORE_INFORMATION and not requested_items:
        raise ValueError("additional information requests need at least one item")
    if status == OUTCOME_RECORDED and not note.strip():
        raise ValueError("a user-recorded consultation outcome needs a note")
