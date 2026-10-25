"""Authority rules R0-R9 (blueprint §8.3): code, not a model, decides what a new fact does to the old ones.

`decide(new, current)` is pure: it returns what should happen (which facts end, which become disputed,
which links to add, and the `rule_id` for the ledger). Persistence is done by `memory.reconcile`.

Rules are evaluated in order and the first match wins (per existing fact). The authority of the new
*document* decides the outcome; recency alone never does.
"""

from __future__ import annotations

from .types import (
    Action,
    Authority,
    ChangeType,
    CurrentFact,
    Decision,
    FactState,
    LinkType,
    NewFact,
    TargetEffect,
    opposing,
)

_CONTRACT_SUBJECTS = {"CONTRACT", "MILESTONE"}
_PARTY_DOCS = {Authority.PLEADING, Authority.SWORN, Authority.NOTICE}

# lower number = more significant, decides the headline rule for the new fact when several facts conflict
_PRIORITY = {"R9": 0, "R6": 1, "R2": 2, "R3": 2, "R4": 2, "R5": 2, "R7": 3, "R8": 4}


def _after(a, b) -> bool | None:  # noqa: ANN001
    """True if date a is after b; None if either is unknown or they are equal (cannot rank)."""
    if a is None or b is None or a == b:
        return None
    return a > b


def _pair(new: NewFact, c: CurrentFact) -> tuple[Decision, TargetEffect]:
    """Rules R2-R9 for one new fact against one conflicting current fact."""
    # ---- R2: signed bilateral document varies a contract / milestone term -----------------------
    if new.authority == Authority.BILATERAL and new.signed_by_all and c.subject_type in _CONTRACT_SUBJECTS:
        later = _after(new.doc_date, c.doc_date)
        if later is True:
            return _supersedes(
                new, c, "R2", "signed bilateral document dated after the term's source varies it"
            )
        if later is False:  # a late-arriving older document: it is already historical
            return _already_superseded(
                new, c, "R2", "an earlier signed document arrived after the later term"
            )
        return _review(new, c, "R9", "bilateral document and existing term carry the same or no date")

    # ---- R3: later court order on the same point ------------------------------------------------
    if new.authority == Authority.COURT and c.authority == Authority.COURT:
        later = _after(new.doc_date, c.doc_date)
        if later is True:
            return _supersedes(new, c, "R3", "a later court order on the same point replaces the earlier one")
        if later is False:
            return _already_superseded(new, c, "R3", "an earlier order arrived after the later order")
        return _review(new, c, "R9", "two orders on the same point carry the same or no date")

    # ---- R4: the same party's later formal position ---------------------------------------------
    if (
        new.authority == Authority.PLEADING
        and new.party_id is not None
        and new.party_id == c.party_id
        and c.authority in (Authority.PLEADING, Authority.NOTICE)
    ):
        amended = new.doc_type.value == "AMENDED_PLEADING"
        if (amended or c.authority == Authority.NOTICE) and _after(new.doc_date, c.doc_date) is True:
            return _supersedes(new, c, "R4", "the party's later formal position replaces its earlier one")
        return _review(new, c, "R9", "same party changes its pleaded position without an allowed amendment")

    # ---- R5: payment records narrow the outstanding amount (computed by code) -------------------
    if new.derived and new.slot == "amount_outstanding":
        eff = TargetEffect(c.assertion_id, Action.END, LinkType.SUPERSEDES, ChangeType.NARROWED, "R5",
                           "outstanding recomputed from invoice amount less recorded payments")  # fmt: skip
        return Decision("R5", ChangeType.NEW, FactState.ACTIVE, False, [eff]), eff

    # ---- R6: the opposing party's pleading / affidavit / notice disputes the allegation ----------
    if new.authority in _PARTY_DOCS and c.authority in _PARTY_DOCS and opposing(new.party_role, c.party_role):
        eff = TargetEffect(c.assertion_id, Action.MARK_DISPUTED, LinkType.CONTRADICTS, ChangeType.DISPUTED, "R6",
                           "the opposing party takes a different position; both versions are kept")  # fmt: skip
        return Decision("R6", ChangeType.NEW, FactState.DISPUTED, False, [eff]), eff

    # ---- R7: a record or correspondence conflicts with a pleaded / sworn position -----------------
    if new.authority in (Authority.RECORD, Authority.CORRESPONDENCE) and c.authority in (
        Authority.PLEADING,
        Authority.SWORN,
    ):
        eff = TargetEffect(c.assertion_id, Action.KEEP, LinkType.CONTRADICTS, ChangeType.CONTRADICTED_BY_EVIDENCE, "R7",
                           "the evidence conflicts with the pleaded position", reverse=True)  # fmt: skip
        return Decision("R7", ChangeType.CONTRADICTED_BY_EVIDENCE, FactState.ACTIVE, True, [eff]), eff
    if new.authority in (Authority.PLEADING, Authority.SWORN) and c.authority in (
        Authority.RECORD,
        Authority.CORRESPONDENCE,
    ):
        eff = TargetEffect(c.assertion_id, Action.MARK_EVIDENCE_ONLY, LinkType.CONTRADICTS,
                           ChangeType.CONTRADICTED_BY_EVIDENCE, "R7",
                           "the pleaded position conflicts with earlier evidence")  # fmt: skip
        return Decision("R7", ChangeType.NEW, FactState.ACTIVE, False, [eff]), eff

    # ---- R8: one-sided proposals and internal notes never change the current position -------------
    one_sided = (
        new.authority in (Authority.CORRESPONDENCE, Authority.INTERNAL)
        or (new.authority == Authority.BILATERAL and not new.signed_by_all)
        or (new.doc_type.value == "APPLICATION" and new.party_id is not None and new.party_id == c.party_id)
    )
    if one_sided:
        eff = TargetEffect(c.assertion_id, Action.KEEP, None, ChangeType.NEW, "R8",
                           "one-sided proposal or note: stored as evidence only")  # fmt: skip
        return Decision("R8", ChangeType.NEW, FactState.ACTIVE, True, [eff]), eff

    # ---- R9: nothing matched: dispute and flag for review, never overwrite silently ---------------
    return _review(new, c, "R9", "no rule covers this conflict")


def _supersedes(new: NewFact, c: CurrentFact, rule: str, why: str) -> tuple[Decision, TargetEffect]:
    eff = TargetEffect(c.assertion_id, Action.END, LinkType.SUPERSEDES, ChangeType.SUPERSEDED, rule, why)
    return Decision(rule, ChangeType.NEW, FactState.ACTIVE, False, [eff]), eff


def _already_superseded(new: NewFact, c: CurrentFact, rule: str, why: str) -> tuple[Decision, TargetEffect]:
    eff = TargetEffect(
        c.assertion_id, Action.KEEP, LinkType.SUPERSEDES, ChangeType.SUPERSEDED, rule, why, reverse=True
    )
    return Decision(rule, ChangeType.NEW, FactState.SUPERSEDED, False, [eff]), eff


def _review(new: NewFact, c: CurrentFact, rule: str, why: str) -> tuple[Decision, TargetEffect]:
    eff = TargetEffect(
        c.assertion_id, Action.MARK_DISPUTED, LinkType.CONTRADICTS, ChangeType.DISPUTED, rule, why
    )
    d = Decision(rule, ChangeType.NEW, FactState.DISPUTED, False, [eff], needs_review=True, review_reason=why)
    return d, eff


def decide(new: NewFact, current: list[CurrentFact]) -> Decision:
    """Reconcile one new fact against the facts that currently carry the same key."""
    position = [
        c for c in current if not c.evidence_only and c.state in (FactState.ACTIVE, FactState.DISPUTED)
    ]

    # R0: nothing to compare with
    if not position:
        return Decision("R0", ChangeType.NEW, FactState.ACTIVE, False, [], reason="first fact for this key")

    same = [c for c in position if c.value.same_as(new.value)]
    differing = [c for c in position if not c.value.same_as(new.value)]

    support = [
        TargetEffect(c.assertion_id, Action.KEEP, LinkType.SUPPORTS, ChangeType.CORROBORATED, "R1",
                     "same value stated again", reverse=True)
        for c in same
    ]  # fmt: skip
    # R1: the new statement agrees with everything that is current -> kept as supporting evidence
    if not differing:
        return Decision("R1", ChangeType.CORROBORATED, FactState.ACTIVE, True, support,
                        reason="agrees with the current fact(s)")  # fmt: skip

    results = [_pair(new, c) for c in differing]
    decisions = [d for d, _ in results]
    effects = [e for _, e in results] + support
    head = min(decisions, key=lambda d: _PRIORITY.get(d.rule_id, 9))

    state = head.new_state
    if any(d.new_state == FactState.DISPUTED for d in decisions):
        state = FactState.DISPUTED
    evidence_only = all(d.new_evidence_only for d in decisions)
    needs_review = any(d.needs_review for d in decisions)
    reasons = [d.review_reason for d in decisions if d.review_reason]
    return Decision(
        rule_id=head.rule_id,
        change_type=head.change_type,
        new_state=state,
        new_evidence_only=evidence_only,
        effects=effects,
        needs_review=needs_review,
        review_reason="; ".join(reasons) or None,
        reason=effects[0].reason if effects else "",
    )
