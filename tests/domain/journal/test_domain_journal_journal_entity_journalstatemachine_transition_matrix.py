"""
Tests for domain/journal/journal_entity.py state machine transitions.
Explicit assertions for all transition pairs and self-transition prohibition.
"""


from domain.journal.journal_entity import JournalStateMachine, JournalStatus

_ALL_STATUSES = list(JournalStatus)

# Expected transition matrix (derived from the actual business rules)
# True = allowed, False = not allowed.
_EXPECTED_MATRIX: dict[tuple[JournalStatus, JournalStatus], bool] = {
    (JournalStatus.DRAFT, JournalStatus.DRAFT): False,
    (JournalStatus.DRAFT, JournalStatus.SUBMITTED): True,
    (JournalStatus.DRAFT, JournalStatus.APPROVED): False,
    (JournalStatus.DRAFT, JournalStatus.REJECTED): False,
    (JournalStatus.DRAFT, JournalStatus.POSTED): False,
    (JournalStatus.DRAFT, JournalStatus.REVERSED): False,
    (JournalStatus.DRAFT, JournalStatus.ARCHIVED): True,
    (JournalStatus.DRAFT, JournalStatus.CANCELLED): True,
    (JournalStatus.SUBMITTED, JournalStatus.DRAFT): True,
    (JournalStatus.SUBMITTED, JournalStatus.SUBMITTED): False,
    (JournalStatus.SUBMITTED, JournalStatus.APPROVED): True,
    (JournalStatus.SUBMITTED, JournalStatus.REJECTED): True,
    (JournalStatus.SUBMITTED, JournalStatus.POSTED): False,
    (JournalStatus.SUBMITTED, JournalStatus.REVERSED): False,
    (JournalStatus.SUBMITTED, JournalStatus.ARCHIVED): False,
    (JournalStatus.SUBMITTED, JournalStatus.CANCELLED): True,
    (JournalStatus.APPROVED, JournalStatus.DRAFT): True,
    (JournalStatus.APPROVED, JournalStatus.SUBMITTED): False,
    (JournalStatus.APPROVED, JournalStatus.APPROVED): False,
    (JournalStatus.APPROVED, JournalStatus.REJECTED): True,
    (JournalStatus.APPROVED, JournalStatus.POSTED): True,
    (JournalStatus.APPROVED, JournalStatus.REVERSED): False,
    (JournalStatus.APPROVED, JournalStatus.ARCHIVED): False,
    (JournalStatus.APPROVED, JournalStatus.CANCELLED): False,
    (JournalStatus.REJECTED, JournalStatus.DRAFT): True,
    (JournalStatus.REJECTED, JournalStatus.SUBMITTED): False,
    (JournalStatus.REJECTED, JournalStatus.APPROVED): False,
    (JournalStatus.REJECTED, JournalStatus.REJECTED): False,
    (JournalStatus.REJECTED, JournalStatus.POSTED): False,
    (JournalStatus.REJECTED, JournalStatus.REVERSED): False,
    (JournalStatus.REJECTED, JournalStatus.ARCHIVED): True,
    (JournalStatus.REJECTED, JournalStatus.CANCELLED): False,
    (JournalStatus.POSTED, JournalStatus.DRAFT): False,
    (JournalStatus.POSTED, JournalStatus.SUBMITTED): False,
    (JournalStatus.POSTED, JournalStatus.APPROVED): False,
    (JournalStatus.POSTED, JournalStatus.REJECTED): False,
    (JournalStatus.POSTED, JournalStatus.POSTED): False,
    (JournalStatus.POSTED, JournalStatus.REVERSED): True,
    (JournalStatus.POSTED, JournalStatus.ARCHIVED): True,
    (JournalStatus.POSTED, JournalStatus.CANCELLED): False,
    (JournalStatus.REVERSED, JournalStatus.DRAFT): False,
    (JournalStatus.REVERSED, JournalStatus.SUBMITTED): False,
    (JournalStatus.REVERSED, JournalStatus.APPROVED): False,
    (JournalStatus.REVERSED, JournalStatus.REJECTED): False,
    (JournalStatus.REVERSED, JournalStatus.POSTED): False,
    (JournalStatus.REVERSED, JournalStatus.REVERSED): False,
    (JournalStatus.REVERSED, JournalStatus.ARCHIVED): True,
    (JournalStatus.REVERSED, JournalStatus.CANCELLED): False,
    (JournalStatus.ARCHIVED, JournalStatus.DRAFT): False,
    (JournalStatus.ARCHIVED, JournalStatus.SUBMITTED): False,
    (JournalStatus.ARCHIVED, JournalStatus.APPROVED): False,
    (JournalStatus.ARCHIVED, JournalStatus.REJECTED): True,
    (JournalStatus.ARCHIVED, JournalStatus.POSTED): True,
    (JournalStatus.ARCHIVED, JournalStatus.REVERSED): False,
    (JournalStatus.ARCHIVED, JournalStatus.ARCHIVED): False,
    (JournalStatus.ARCHIVED, JournalStatus.CANCELLED): False,
    (JournalStatus.CANCELLED, JournalStatus.DRAFT): False,
    (JournalStatus.CANCELLED, JournalStatus.SUBMITTED): False,
    (JournalStatus.CANCELLED, JournalStatus.APPROVED): False,
    (JournalStatus.CANCELLED, JournalStatus.REJECTED): False,
    (JournalStatus.CANCELLED, JournalStatus.POSTED): False,
    (JournalStatus.CANCELLED, JournalStatus.REVERSED): False,
    (JournalStatus.CANCELLED, JournalStatus.ARCHIVED): False,
    (JournalStatus.CANCELLED, JournalStatus.CANCELLED): False,
}


def test_full_transition_matrix():
    """
    Test every possible (from, to) pair against the expected transition matrix.
    This provides full coverage for positive and negative transition paths.
    """
    for from_status in _ALL_STATUSES:
        for to_status in _ALL_STATUSES:
            expected = _EXPECTED_MATRIX.get((from_status, to_status), False)
            actual = JournalStateMachine.can_transition(from_status, to_status)
            assert actual == expected, (
                f"Transition from {from_status.name} to {to_status.name} "
                f"expected {expected} but got {actual}"
            )


def test_no_self_transition():
    """
    Self-transitions (e.g., DRAFT -> DRAFT) should always be disallowed.
    This is a general invariant unless explicitly allowed by business rules.
    """
    # Explicitly allowed self-transitions (if any) – currently none.
    allowed_self_transitions: set[JournalStatus] = set()
    for status in _ALL_STATUSES:
        if status in allowed_self_transitions:
            continue
        assert JournalStateMachine.can_transition(status, status) is False, (
            f"Self-transition on {status.name} should be disallowed but is allowed"
        )
