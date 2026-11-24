"""Lógica pura de `scripts/apps_start.py` e do `make apps-start` (P13.1). Sem workspace."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import apps_start as a  # noqa: E402


class FakeClock:
    """Relógio manual: `sleep` avança o tempo, então os testes não esperam de verdade."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_apps_are_the_three_of_the_bundle() -> None:
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    declared = {app["name"] for app in bundle["resources"]["apps"].values()}
    assert {spec.name for spec in a.APPS} == declared
    assert len(a.APPS) == 3


def test_wait_returns_as_soon_as_all_are_running() -> None:
    fake = FakeClock()
    seen = {"agent-atlas": ["STARTING", "RUNNING"], "atlas-web": ["RUNNING"]}

    def get_state(name: str) -> str | None:
        return seen[name].pop(0)

    states = a.wait_until_running(
        ["agent-atlas", "atlas-web"],
        get_state,
        timeout_s=100,
        interval_s=10,
        sleep=fake.sleep,
        clock=fake.clock,
    )
    assert states == {"agent-atlas": "RUNNING", "atlas-web": "RUNNING"}
    assert fake.sleeps == [10]


def test_wait_does_not_requery_apps_already_running() -> None:
    fake = FakeClock()
    calls: list[str] = []

    def get_state(name: str) -> str | None:
        calls.append(name)
        return "RUNNING" if name == "atlas-web" else "STARTING"

    a.wait_until_running(
        ["atlas-web", "atlas-mcp"],
        get_state,
        timeout_s=25,
        interval_s=10,
        sleep=fake.sleep,
        clock=fake.clock,
    )
    assert calls.count("atlas-web") == 1


def test_wait_gives_up_at_the_deadline_with_the_last_state() -> None:
    fake = FakeClock()
    states = a.wait_until_running(
        ["atlas-mcp"],
        lambda _name: "STOPPED",
        timeout_s=30,
        interval_s=10,
        sleep=fake.sleep,
        clock=fake.clock,
    )
    assert states == {"atlas-mcp": "STOPPED"}
    assert fake.now >= 30


def test_retry_stops_at_the_first_clean_attempt() -> None:
    fake = FakeClock()
    attempts = [["down"], ["down"], []]
    problems = a.retry_check(
        lambda: attempts.pop(0), timeout_s=100, interval_s=5, sleep=fake.sleep, clock=fake.clock
    )
    assert problems == []
    assert fake.sleeps == [5, 5]


def test_retry_returns_the_last_problems_at_the_deadline() -> None:
    fake = FakeClock()
    problems = a.retry_check(
        lambda: ["ainda fora"], timeout_s=20, interval_s=10, sleep=fake.sleep, clock=fake.clock
    )
    assert problems == ["ainda fora"]


def test_web_health() -> None:
    assert a.check_web_health(lambda _p: (200, {"status": "healthy"})) == []
    assert "HTTP 503" in a.check_web_health(lambda _p: (503, None))[0]
    assert "'degraded'" in a.check_web_health(lambda _p: (200, {"status": "degraded"}))[0]
    assert a.check_web_health(lambda _p: (200, ["lista"])) != []


def test_agent_health_accepts_either_path() -> None:
    assert a.check_agent_health(lambda p: 200 if p == "/" else 404) == []
    assert a.check_agent_health(lambda p: 200 if p == "/health" else 502) == []
    problems = a.check_agent_health(lambda _p: 502)
    assert len(problems) == 1
    assert "/health = HTTP 502" in problems[0]
    assert "/ = HTTP 502" in problems[0]


def test_mcp_health_uses_the_same_rules_as_check_mcp_health() -> None:
    ok = {"status": "healthy", "warehouse": "STOPPED", "version": "0.1.0"}
    assert a.check_mcp_health(lambda: ok) == []
    assert a.check_mcp_health(lambda: {"status": "down"}) != []


def test_probe_turns_an_exception_into_a_problem() -> None:
    def boom() -> list[str]:
        raise ConnectionError("recusou")

    assert a._probe("atlas-mcp", boom) == ["atlas-mcp: ConnectionError: recusou"]


def test_build_check_web_and_agent_hit_the_right_paths() -> None:
    class Resp:
        def __init__(self, status_code: int, body: Any = None) -> None:
            self.status_code = status_code
            self._body = body

        def json(self) -> Any:
            return self._body

    paths: list[tuple[str, str]] = []

    def get_response(base: str, path: str) -> Resp:
        paths.append((base, path))
        return Resp(200, {"status": "healthy"})

    assert a.build_check("web", "https://w", get_response, dict)() == []
    assert a.build_check("agent", "https://g", get_response, dict)() == []
    assert paths == [("https://w", "/api/health"), ("https://g", "/health")]
    with pytest.raises(ValueError, match="desconhecido"):
        a.build_check("outro", "https://x", get_response, dict)


@pytest.mark.skipif(shutil.which("make") is None, reason="make não está instalado")
def test_make_apps_start_requires_a_profile() -> None:
    result = subprocess.run(  # noqa: S603
        ["make", "-C", str(ROOT), "apps-start"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "PROFILE" in result.stderr


@pytest.mark.skipif(shutil.which("make") is None, reason="make não está instalado")
def test_make_apps_start_passes_the_profile_to_the_script() -> None:
    result = subprocess.run(  # noqa: S603
        ["make", "-C", str(ROOT), "-n", "apps-start", "PROFILE=meu-perfil"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    assert "scripts/apps_start.py --profile" in result.stdout
    assert "meu-perfil" in result.stdout


def test_combined_state_needs_app_running_and_compute_active() -> None:
    assert a.combined_state("RUNNING", "ACTIVE") == "RUNNING"
    assert a.combined_state("RUNNING", None) == "RUNNING"
    assert a.combined_state("RUNNING", "STOPPED") == "RUNNING/STOPPED"
    assert a.combined_state("UNAVAILABLE", "STOPPED") == "UNAVAILABLE/STOPPED"
    assert a.combined_state(None, None) == "None/None"


def test_wait_survives_a_transient_error_in_get_state() -> None:
    fake = FakeClock()
    answers: list[str | Exception] = [ConnectionError("rede"), "RUNNING"]

    def get_state(_name: str) -> str | None:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    states = a.wait_until_running(
        ["atlas-web"], get_state, timeout_s=100, interval_s=1, sleep=fake.sleep, clock=fake.clock
    )
    assert states == {"atlas-web": "RUNNING"}


def test_build_check_mcp_sends_the_bearer_token_and_never_prints_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, str] = {}

    async def fake_call(url: str, token: str) -> dict[str, Any]:
        seen.update(url=url, token=token)
        return {"status": "healthy", "warehouse": "STOPPED", "version": "0.1.0"}

    monkeypatch.setattr(a, "_call_mcp_health", fake_call)
    check = a.build_check(
        "mcp", "https://mcp", lambda _b, _p: None, lambda: {"Authorization": "Bearer segredo"}
    )
    assert check() == []
    assert seen == {"url": "https://mcp/mcp", "token": "segredo"}

    def boom(_url: str, _token: str) -> dict[str, Any]:
        raise ConnectionError("recusou")

    async def failing(url: str, token: str) -> dict[str, Any]:
        return boom(url, token)

    monkeypatch.setattr(a, "_call_mcp_health", failing)
    problems = a._probe("atlas-mcp", check)
    assert problems == ["atlas-mcp: ConnectionError: recusou"]
    assert "segredo" not in " ".join(problems)
