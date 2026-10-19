from dataclasses import dataclass

import pytest

from tech_amharic.domain import (
    Decision,
    Role,
    RuleViolation,
    TermStatus,
    allowed_decisions,
    check_domain,
    check_resubmit,
    decide,
)


@dataclass
class T:
    id: int
    lang: str
    status: str


REVIEWER, PROPOSER = 1, 2


def run(term: T, decision: Decision, siblings: list[T] | None = None, **kw: object) -> object:
    args: dict[str, object] = {
        "actor_id": REVIEWER,
        "actor_role": Role.REVIEWER,
        "proposer_id": PROPOSER,
        "term": term,
        "siblings": siblings or [],
        "decision": decision,
        "comment": None,
    }
    args.update(kw)
    return decide(**args)  # type: ignore[arg-type]


def test_reviewer_approves_proposed_term() -> None:
    out = run(T(10, "am", "proposed"), Decision.APPROVE_PREFERRED)
    assert out.new_status is TermStatus.PREFERRED  # type: ignore[attr-defined]


def test_contributor_cannot_review() -> None:
    with pytest.raises(RuleViolation) as exc:
        run(T(10, "am", "proposed"), Decision.APPROVE_ADMITTED, actor_role=Role.CONTRIBUTOR)
    assert exc.value.code == "not_reviewer"


def test_nobody_reviews_their_own_proposal_not_even_admin() -> None:
    with pytest.raises(RuleViolation) as exc:
        run(
            T(10, "am", "proposed"),
            Decision.APPROVE_ADMITTED,
            actor_id=PROPOSER,
            actor_role=Role.ADMIN,
        )
    assert exc.value.code == "self_review"


def test_new_preferred_demotes_old_preferred_same_language_only() -> None:
    siblings = [
        T(1, "am", "preferred"),  # demoted
        T(2, "en", "preferred"),  # other language: untouched
        T(3, "am", "admitted"),  # not preferred: untouched
    ]
    out = run(T(10, "am", "proposed"), Decision.APPROVE_PREFERRED, siblings)
    assert out.demote_ids == (1,)  # type: ignore[attr-defined]


def test_reject_needs_a_comment() -> None:
    with pytest.raises(RuleViolation) as exc:
        run(T(10, "am", "proposed"), Decision.REJECT, comment="  ")
    assert exc.value.code == "comment_required"
    out = run(T(10, "am", "proposed"), Decision.REJECT, comment="Already covered by ምስጠራ")
    assert out.new_status is TermStatus.REJECTED  # type: ignore[attr-defined]


def test_rejected_is_terminal() -> None:
    assert allowed_decisions(TermStatus.REJECTED) == []
    with pytest.raises(RuleViolation) as exc:
        run(T(10, "am", "rejected"), Decision.APPROVE_ADMITTED)
    assert exc.value.code == "invalid_transition"


def test_published_terms_can_be_promoted_demoted_and_deprecated() -> None:
    promoted = run(T(10, "am", "admitted"), Decision.APPROVE_PREFERRED)
    assert promoted.new_status is TermStatus.PREFERRED  # type: ignore[attr-defined]
    stepped_down = run(T(10, "am", "preferred"), Decision.APPROVE_ADMITTED)
    assert stepped_down.new_status is TermStatus.ADMITTED  # type: ignore[attr-defined]
    out = run(T(10, "am", "preferred"), Decision.DEPRECATE, comment="Coinage never caught on")
    assert out.new_status is TermStatus.DEPRECATED  # type: ignore[attr-defined]


def test_resubmit_only_by_proposer_after_changes_requested() -> None:
    assert (
        check_resubmit(actor_id=PROPOSER, proposer_id=PROPOSER, status=TermStatus.CHANGES_REQUESTED)
        is TermStatus.PROPOSED
    )
    with pytest.raises(RuleViolation):
        check_resubmit(actor_id=REVIEWER, proposer_id=PROPOSER, status=TermStatus.CHANGES_REQUESTED)
    with pytest.raises(RuleViolation):
        check_resubmit(actor_id=PROPOSER, proposer_id=PROPOSER, status=TermStatus.PROPOSED)


def test_unknown_domain_rejected() -> None:
    assert check_domain("security") == "security"
    with pytest.raises(RuleViolation):
        check_domain("blockchain")
