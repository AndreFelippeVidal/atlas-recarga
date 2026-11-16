"""Máquina de estados da revisão (task P8.6). O IO em Spark é conferido no workspace."""

from __future__ import annotations

import pytest

from commission import review
from commission.review import BatchState, Request, ReviewError, decide

AN = frozenset({review.ANALYSTS_GROUP})
DI = frozenset({review.DIRECTORS_GROUP})


def _state(status: str, recon: str | None = "passed", analyst: str | None = None) -> BatchState:
    return BatchState(status=status, reconciliation_status=recon, analyst_actor=analyst)


def _req(decision: str, actor: str, groups: frozenset[str], **kw: object) -> Request:
    return Request(decision=decision, actor=actor, groups=groups, **kw)  # type: ignore[arg-type]


def test_submit_needs_passed_reconciliation() -> None:
    t = decide(_state("draft"), _req("submit", "ana@x", frozenset()))
    assert (t.from_status, t.to_status, t.role) == ("draft", "under_review", "system")
    for recon in ("failed", None):
        with pytest.raises(ReviewError) as e:
            decide(_state("draft", recon), _req("submit", "ana@x", frozenset()))
        assert e.value.code == review.RECONCILIATION_NOT_PASSED


def test_full_happy_path_with_distinct_actors() -> None:
    t1 = decide(_state("under_review"), _req("approve", "ana@x", AN))
    assert (t1.to_status, t1.role) == ("analyst_approved", "analyst")
    t2 = decide(_state("analyst_approved", analyst="ana@x"), _req("approve", "diretora@x", DI))
    assert (t2.to_status, t2.role, t2.demo_override) == ("approved", "director", False)


def test_same_person_as_analyst_and_director_is_denied_and_audited() -> None:
    both = AN | DI
    with pytest.raises(ReviewError) as e:
        decide(_state("analyst_approved", analyst="Ana@X"), _req("approve", "ana@x", both))
    assert e.value.code == review.SEGREGATION_OF_DUTIES_VIOLATION
    assert e.value.audit is not None
    assert e.value.audit.to_status == review.DENIED  # não conta como aprovação
    assert e.value.audit.from_status == "analyst_approved"


def test_demo_override_allows_same_actor_and_is_marked() -> None:
    t = decide(
        _state("analyst_approved", analyst="ana@x"),
        _req("approve", "ana@x", AN | DI, allow_same_approver_demo=True),
    )
    assert (t.to_status, t.role, t.demo_override) == ("approved", "demo_override", True)


def test_demo_override_still_needs_the_director_group() -> None:
    with pytest.raises(ReviewError) as e:
        decide(
            _state("analyst_approved", analyst="ana@x"),
            _req("approve", "ana@x", AN, allow_same_approver_demo=True),
        )
    assert e.value.code == review.ROLE_NOT_ALLOWED


@pytest.mark.parametrize("status", ["under_review", "analyst_approved"])
@pytest.mark.parametrize("text", ["", "   ", "curto demais", "x" * 19, " " * 30])
def test_reject_without_enough_justification_fails(status: str, text: str) -> None:
    groups = AN if status == "under_review" else DI
    with pytest.raises(ReviewError) as e:
        decide(_state(status, analyst="a@x"), _req("reject", "b@x", groups, justification=text))
    assert e.value.code == review.JUSTIFICATION_REQUIRED


@pytest.mark.parametrize(("status", "groups"), [("under_review", AN), ("analyst_approved", DI)])
def test_reject_with_justification_from_either_stage(status: str, groups: frozenset[str]) -> None:
    text = "  números do PDV 123 não conferem com a base  "
    t = decide(_state(status, analyst="a@x"), _req("reject", "b@x", groups, justification=text))
    assert (t.from_status, t.to_status) == (status, "rejected")
    assert t.justification == text.strip()


def test_exactly_20_characters_is_enough() -> None:
    t = decide(_state("under_review"), _req("reject", "a@x", AN, justification="x" * 20))
    assert t.to_status == "rejected"


@pytest.mark.parametrize(
    ("status", "decision"),
    [
        ("draft", "approve"),
        ("draft", "reject"),
        ("under_review", "submit"),
        ("approved", "reject"),
        ("rejected", "approve"),
        ("locked", "reject"),
    ],
)
def test_invalid_transitions(status: str, decision: str) -> None:
    with pytest.raises(ReviewError) as e:
        decide(_state(status), _req(decision, "a@x", AN | DI, justification="x" * 30))
    assert e.value.code == review.INVALID_TRANSITION


def test_wrong_group_cannot_decide() -> None:
    with pytest.raises(ReviewError) as e:
        decide(_state("under_review"), _req("approve", "d@x", DI))
    assert e.value.code == review.ROLE_NOT_ALLOWED
    with pytest.raises(ReviewError) as e:
        decide(_state("analyst_approved", analyst="a@x"), _req("approve", "b@x", AN))
    assert e.value.code == review.ROLE_NOT_ALLOWED


def test_unknown_decision_is_rejected() -> None:
    with pytest.raises(ReviewError) as e:
        decide(_state("draft"), _req("lock", "a@x", AN))
    assert e.value.code == review.INVALID_REQUEST


class _Rows:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def first(self) -> dict[str, object] | None:
        return self._row


class _FakeSpark:
    """Responde às consultas de `load_state` e guarda as escritas."""

    def __init__(self, status: str, analyst: str | None) -> None:
        self.status, self.analyst = status, analyst
        self.writes: list[tuple[str, dict[str, object]]] = []

    def sql(self, query: str, args: dict[str, object]) -> _Rows:
        if query.startswith("INSERT") or query.startswith("UPDATE"):
            self.writes.append((query.split()[0], args))
            return _Rows({"num_affected_rows": 1})
        if "FROM atlas_dev.commission.batches" in query:
            return _Rows({"status": self.status})
        if "reconciliation" in query:
            return _Rows({"status": "passed"})
        return _Rows(None if self.analyst is None else {"actor": self.analyst})


def test_review_records_the_denied_attempt_then_raises() -> None:
    spark = _FakeSpark("analyst_approved", "ana@x")
    with pytest.raises(ReviewError) as e:
        review.review(spark, "atlas_dev", "COM-2026-10-v1", _req("approve", "ana@x", AN | DI))
    assert e.value.code == review.SEGREGATION_OF_DUTIES_VIOLATION
    assert [w[0] for w in spark.writes] == ["INSERT"]  # só o evento; o status não muda
    assert spark.writes[0][1]["t"] == review.DENIED


def test_review_applies_status_before_event() -> None:
    spark = _FakeSpark("under_review", None)
    review.review(spark, "atlas_dev", "COM-2026-10-v1", _req("approve", "ana@x", AN))
    assert [w[0] for w in spark.writes] == ["UPDATE", "INSERT"]


@pytest.mark.parametrize("affected", [0, 2, None])
def test_status_update_must_touch_exactly_one_row(affected: int | None) -> None:
    class Spark(_FakeSpark):
        def sql(self, query: str, args: dict[str, object]) -> _Rows:
            if query.startswith("UPDATE"):
                self.writes.append(("UPDATE", args))
                return _Rows(None if affected is None else {"num_affected_rows": affected})
            return super().sql(query, args)

    spark = Spark("under_review", None)
    with pytest.raises(RuntimeError, match="mudou de estado"):
        review.review(spark, "atlas_dev", "COM-2026-10-v1", _req("approve", "ana@x", AN))
    assert [w[0] for w in spark.writes] == ["UPDATE"]  # nenhum evento sem transição aplicada


def test_event_failure_after_status_is_reported() -> None:
    class Spark(_FakeSpark):
        def sql(self, query: str, args: dict[str, object]) -> _Rows:
            if query.startswith("INSERT"):
                raise OSError("boom")
            return super().sql(query, args)

    with pytest.raises(RuntimeError, match="evento NÃO foi gravado"):
        review.review(
            Spark("under_review", None), "atlas_dev", "COM-2026-10-v1", _req("approve", "a@x", AN)
        )


@pytest.mark.parametrize("status", ["under_review", "analyst_approved"])
@pytest.mark.parametrize("groups", [AN, DI])
def test_either_group_can_reject_at_any_review_stage(status: str, groups: frozenset[str]) -> None:
    t = decide(_state(status, analyst="a@x"), _req("reject", "b@x", groups, justification="x" * 25))
    assert t.to_status == "rejected"
    assert t.role == ("analyst" if groups == AN else "director")


def test_reject_needs_one_of_the_two_groups() -> None:
    with pytest.raises(ReviewError) as e:
        decide(
            _state("under_review"),
            _req("reject", "b@x", frozenset({"users"}), justification="x" * 25),
        )
    assert e.value.code == review.ROLE_NOT_ALLOWED


class _Group:
    def __init__(self, display: str) -> None:
        self.display = display


class _User:
    def __init__(self, groups: list[str], active: bool | None = True) -> None:
        self.groups = [_Group(g) for g in groups]
        self.active = active


def _patch_sdk(
    monkeypatch: pytest.MonkeyPatch, creator: str | None, users: list[_User]
) -> list[str]:
    import sys
    import types

    filters: list[str] = []

    class Jobs:
        def get_run(self, run_id: int) -> object:
            return types.SimpleNamespace(creator_user_name=creator)

    class Users:
        def list(self, filter: str, attributes: str) -> list[_User]:
            filters.append(filter)
            return users

    class Client:
        jobs = Jobs()
        users = Users()

    module = types.ModuleType("databricks.sdk")
    module.WorkspaceClient = Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "databricks.sdk", module)
    return filters


def test_actor_and_groups_come_from_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    filters = _patch_sdk(monkeypatch, "ana@x.com", [_User([review.ANALYSTS_GROUP, "users"])])
    actor, groups = review.lookup_actor_and_groups(1)
    assert actor == "ana@x.com"
    assert groups == {review.ANALYSTS_GROUP, "users"}
    assert filters == ['userName eq "ana@x.com"']


@pytest.mark.parametrize(
    ("creator", "users"),
    [
        (None, [_User([])]),
        ("", [_User([])]),
        ('x" or userName ne "', [_User([])]),  # injeção no filtro SCIM
        ("ana@x.com", []),
        ("ana@x.com", [_User([review.ANALYSTS_GROUP], active=False)]),
    ],
)
def test_actor_lookup_refuses_unknown_or_unsafe_users(
    monkeypatch: pytest.MonkeyPatch, creator: str | None, users: list[_User]
) -> None:
    _patch_sdk(monkeypatch, creator, users)
    with pytest.raises(ReviewError):
        review.lookup_actor_and_groups(1)


def test_review_rejects_bad_batch_id_and_catalog() -> None:
    spark = _FakeSpark("draft", None)
    with pytest.raises(ReviewError):
        review.review(spark, "atlas_dev", "COM-2026-10-v1; DROP", _req("submit", "a@x", AN))
    with pytest.raises(ValueError, match="catalog"):
        review.review(spark, "x; DROP", "COM-2026-10-v1", _req("submit", "a@x", AN))
