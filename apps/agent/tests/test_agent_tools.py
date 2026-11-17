import json

import pytest
from agent_server.config import ConfigError, load_config
from agent_server.tools import (
    GenieUnavailableError,
    ask_with_polling,
    genie_mcp_url,
    pick_tool,
    short_tool_name,
    status_of,
)

NAMES = ["query_space_abc", "poll_response_abc"]
RUNNING = json.dumps({"status": "EXECUTING_QUERY", "conversationId": "c", "messageId": "m"})


def test_uc_function_names_are_the_closed_list() -> None:
    cfg = load_config({"ATLAS_CATALOG": "atlas_dev"})
    assert cfg.uc_function_names() == [
        "atlas_dev.semantic.fn_list_metrics",
        "atlas_dev.semantic.fn_metric_by_region",
        "atlas_dev.semantic.fn_compare_months",
    ]


def test_catalog_must_be_simple_identifier() -> None:
    with pytest.raises(ConfigError, match="ATLAS_CATALOG"):
        load_config({"ATLAS_CATALOG": "atlas.semantic; DROP"})


def test_genie_space_id_must_be_hex32() -> None:
    assert load_config({"ATLAS_GENIE_SPACE_ID": "a" * 32}).genie_space_id == "a" * 32
    assert load_config({}).genie_space_id is None
    with pytest.raises(ConfigError, match="ATLAS_GENIE_SPACE_ID"):
        load_config({"ATLAS_GENIE_SPACE_ID": "../x"})


@pytest.mark.parametrize(
    "raw",
    ["atlas_dev__semantic__fn_list_metrics", "atlas.semantic.fn_list_metrics", "fn_list_metrics"],
)
def test_short_tool_name(raw: str) -> None:
    assert short_tool_name(raw) == "fn_list_metrics"


def test_genie_mcp_url() -> None:
    assert genie_mcp_url("https://h.cloud.databricks.com/", "ab") == (
        "https://h.cloud.databricks.com/api/2.0/mcp/genie/ab"
    )


def test_pick_tool_missing() -> None:
    assert pick_tool(NAMES, ("poll",)) == "poll_response_abc"
    with pytest.raises(GenieUnavailableError):
        pick_tool(["other"], ("poll",))


def test_status_of() -> None:
    assert status_of('{"status": "completed"}') == "COMPLETED"
    assert status_of("texto livre") is None
    assert status_of("[1]") is None


def test_plain_text_answer_is_returned_without_polling() -> None:
    calls: list[str] = []

    def call(name: str, args: dict[str, str]) -> str:
        calls.append(name)
        return "R$ 10,00"

    assert ask_with_polling(call, NAMES, "q") == "R$ 10,00"
    assert calls == ["query_space_abc"]


def test_polls_until_completed() -> None:
    answers = iter(
        [
            json.dumps({"status": "RUNNING", "conversationId": "c", "messageId": "m"}),
            json.dumps({"status": "RUNNING"}),
            json.dumps({"status": "COMPLETED", "answer": "ok"}),
        ]
    )
    seen: list[tuple[str, dict[str, str]]] = []

    def call(name: str, args: dict[str, str]) -> str:
        seen.append((name, args))
        return next(answers)

    out = ask_with_polling(call, NAMES, "q", sleep=lambda _s: None)
    assert json.loads(out)["answer"] == "ok"
    assert seen[1] == ("poll_response_abc", {"conversation_id": "c", "message_id": "m"})


def test_timeout_raises() -> None:
    ticks = iter(range(0, 1000, 20))

    def call(name: str, args: dict[str, str]) -> str:
        return RUNNING

    with pytest.raises(GenieUnavailableError, match="sem resposta"):
        ask_with_polling(call, NAMES, "q", sleep=lambda _s: None, clock=lambda: next(ticks))


def test_failed_status_raises() -> None:
    answers = iter([RUNNING, json.dumps({"status": "FAILED"})])

    with pytest.raises(GenieUnavailableError, match="FAILED"):
        ask_with_polling(lambda n, a: next(answers), NAMES, "q", sleep=lambda _s: None)


def test_first_call_uses_query_argument() -> None:
    seen: list[dict[str, str]] = []

    def call(name: str, args: dict[str, str]) -> str:
        seen.append(args)
        return "ok"

    ask_with_polling(call, NAMES, "pergunta")
    assert seen == [{"query": "pergunta"}]


def test_missing_ids_raises() -> None:
    with pytest.raises(GenieUnavailableError, match="conversationId"):
        ask_with_polling(
            lambda n, a: json.dumps({"status": "EXECUTING_QUERY"}),
            NAMES,
            "q",
            sleep=lambda _s: None,
        )
