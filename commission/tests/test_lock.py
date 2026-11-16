"""Lock e remessa simulada (task P8.7). O IO em Spark é conferido no workspace."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest

from commission import lock, review
from commission.review import BatchState, Request, ReviewError, decide

ROWS = [
    ("pos", "P2", Decimal("150.00")),
    ("distributor", "D1", Decimal("30.50")),
    ("pos", "P1", Decimal("100")),
]


def test_render_is_sorted_two_decimals_and_deterministic() -> None:
    text = lock.render_remittance(ROWS).decode()
    assert text == (
        "beneficiary_type,beneficiary_id,commission_brl\n"
        "distributor,D1,30.50\npos,P1,100.00\npos,P2,150.00\n"
    )
    assert lock.render_remittance(reversed(ROWS)) == lock.render_remittance(ROWS)


def test_write_remittance_hash_matches_the_file(tmp_path: Path) -> None:
    content = lock.render_remittance(ROWS)
    digest = lock.write_remittance(tmp_path / "vol", "COM-2026-10-v1", content)
    csv_bytes = (tmp_path / "vol" / "COM-2026-10-v1.csv").read_bytes()
    assert digest == hashlib.sha256(csv_bytes).hexdigest()
    sha_text = (tmp_path / "vol" / "COM-2026-10-v1.sha256").read_text()
    assert sha_text == f"{digest}  COM-2026-10-v1.csv\n"


def test_write_remittance_is_idempotent(tmp_path: Path) -> None:
    content = lock.render_remittance(ROWS)
    first = lock.write_remittance(tmp_path, "COM-2026-10-v1", content)
    assert lock.write_remittance(tmp_path, "COM-2026-10-v1", content) == first


def test_check_totals_accepts_matching_sums() -> None:
    lock.check_totals(ROWS, Decimal("250.00"), Decimal("30.50"))


@pytest.mark.parametrize(
    ("rows", "pos", "dist"),
    [
        (ROWS, Decimal("250.01"), Decimal("30.50")),
        (ROWS, Decimal("250.00"), Decimal("0")),
        ([], Decimal("0"), Decimal("0")),
        ([("other", "X", Decimal("1"))], Decimal("1"), Decimal("0")),
    ],
)
def test_check_totals_refuses_mismatch(
    rows: list[tuple[str, str, Decimal]], pos: Decimal, dist: Decimal
) -> None:
    with pytest.raises(RuntimeError):
        lock.check_totals(rows, pos, dist)


def test_remittance_dir_is_the_catalog_volume() -> None:
    assert lock.remittance_dir("atlas_dev") == Path("/Volumes/atlas_dev/commission/remittance")


DI = frozenset({review.DIRECTORS_GROUP})


def _state(status: str) -> BatchState:
    return BatchState(status=status, reconciliation_status="passed", analyst_actor="ana@x")


def test_resume_lock_from_approved_is_a_system_transition() -> None:
    t = decide(_state("approved"), Request("approve", "diretora@x", DI))
    assert (t.from_status, t.to_status, t.role) == ("approved", "locked", "system")


def test_resume_lock_needs_the_director_group() -> None:
    with pytest.raises(ReviewError) as e:
        decide(_state("approved"), Request("approve", "ana@x", frozenset()))
    assert e.value.code == review.ROLE_NOT_ALLOWED


def test_locked_batch_cannot_be_decided_again() -> None:
    for decision in ("approve", "reject", "submit"):
        with pytest.raises(ReviewError) as e:
            decide(_state("locked"), Request(decision, "d@x", DI, "x" * 30))
        assert e.value.code == review.INVALID_TRANSITION


class _Row(dict):  # type: ignore[type-arg]
    pass


class _Result:
    def __init__(self, rows: list[_Row]) -> None:
        self._rows = rows

    def first(self) -> _Row | None:
        return self._rows[0] if self._rows else None

    def collect(self) -> list[_Row]:
        return self._rows


class FakeSpark:
    """Responde por trecho do SQL e guarda a ordem das escritas."""

    def __init__(self, status: str = "approved", locked_rows: int = 0) -> None:
        self.status = status
        self.locked_rows = locked_rows
        self.calls: list[str] = []
        self.events: list[tuple[str, ...]] = []
        self.sha: str | None = None
        self.diverged = 0

    def sql(self, text: str, args: dict[str, object] | None = None) -> _Result:
        args = args or {}
        if "SELECT status FROM" in text and "batches" in text:
            return _Result([_Row(status=self.status)])
        if "FROM" in text and "reconciliation" in text:
            return _Result([_Row(status="passed")])
        if "to_status = 'analyst_approved'" in text:
            return _Result([_Row(actor="ana@x")])
        if "total_pos_brl" in text:
            return _Result(
                [_Row(total_pos_brl=Decimal("250.00"), total_distributor_brl=Decimal("30.50"))]
            )
        if text.startswith("SELECT beneficiary_type, beneficiary_id, commission_brl"):
            return _Result(
                [_Row(beneficiary_type=k, beneficiary_id=i, commission_brl=v) for k, i, v in ROWS]
            )
        if text.startswith("INSERT INTO") and "locked_lines" in text:
            self.calls.append("insert_locked")
            self.locked_rows = self.locked_rows or len(ROWS)
            return _Result([])
        if "COUNT(*) AS n FROM" in text and "EXCEPT" in text:
            return _Result([_Row(n=self.diverged)])
        if "COUNT(*) AS n FROM" in text and "locked_lines" in text:
            return _Result([_Row(n=self.locked_rows)])
        if "SET remittance_sha256" in text:
            self.calls.append("set_sha")
            self.sha = str(args["h"])
            return _Result([])
        if text.startswith("UPDATE") and "SET status" in text:
            assert self.status == args["f"]
            self.status = str(args["t"])
            self.calls.append(f"status:{self.status}")
            return _Result([_Row(num_affected_rows=1)])
        if text.startswith("INSERT INTO") and "batch_events" in text:
            self.events.append((str(args["f"]), str(args["t"]), str(args["a"]), str(args["r"])))
            self.calls.append(f"event:{args['t']}")
            return _Result([])
        raise AssertionError(f"SQL inesperado: {text}")


@pytest.fixture
def volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(lock, "remittance_dir", lambda catalog: tmp_path)
    return tmp_path


def _director() -> Request:
    return Request("approve", "diretora@x", DI)


def test_final_approval_locks_in_order_with_a_system_event(volume: Path) -> None:
    spark = FakeSpark(status="analyst_approved")
    review.review(spark, "atlas_dev", "COM-2026-10-v1", _director())
    assert spark.calls == [
        "status:approved",
        "event:approved",
        "insert_locked",
        "set_sha",
        "status:locked",
        "event:locked",
    ]
    assert spark.events == [
        ("analyst_approved", "approved", "diretora@x", "director"),
        ("approved", "locked", "system", "system"),
    ]
    csv_bytes = (volume / "COM-2026-10-v1.csv").read_bytes()
    assert spark.sha == hashlib.sha256(csv_bytes).hexdigest()  # critério 7


def test_resume_from_approved_locks_without_a_new_approval(volume: Path) -> None:
    spark = FakeSpark(status="approved", locked_rows=len(ROWS))  # insert já aconteceu antes
    t = review.review(spark, "atlas_dev", "COM-2026-10-v1", _director())
    assert t.to_status == "locked"
    assert spark.events == [("approved", "locked", "system", "system")]
    assert "event:approved" not in spark.calls
    assert spark.status == "locked"


def test_lock_refuses_diverged_locked_lines(volume: Path) -> None:
    spark = FakeSpark(status="approved", locked_rows=len(ROWS))
    spark.diverged = 1
    with pytest.raises(RuntimeError, match="diverge"):
        review.review(spark, "atlas_dev", "COM-2026-10-v1", _director())
    assert spark.status == "approved"  # não travou
    assert spark.sha is None
