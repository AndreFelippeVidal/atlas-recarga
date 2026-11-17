import pytest
from agent_server.config import ConfigError, load_config


def test_defaults() -> None:
    c = load_config({})
    assert c.gateway_mode == "unity"
    assert c.llm_service == "system.ai.gpt-oss-120b"
    assert c.send_request_tags is False


def test_classic_mode_rejected() -> None:
    with pytest.raises(ConfigError, match="classic"):
        load_config({"ATLAS_GATEWAY_MODE": "classic"})


@pytest.mark.parametrize("name", ["gpt-oss-120b", "system.gpt-oss-120b", "", "a.b.c d"])
def test_llm_service_needs_three_parts(name: str) -> None:
    with pytest.raises(ConfigError, match="três partes"):
        load_config({"ATLAS_LLM_SERVICE": name})


def test_trace_tags_have_spec_keys() -> None:
    tags = load_config({"ATLAS_APP_VERSION": "1.2"}).trace_tags("a@b.com")
    assert set(tags) == {"user", "app_version", "prompt_version", "llm_service"}
    assert tags["user"] == "a@b.com"
    assert load_config({}).trace_tags(None)["user"] == "unknown"


def test_request_tags_opt_in() -> None:
    assert load_config({"ATLAS_LLM_REQUEST_TAGS": "1"}).send_request_tags is True


def test_request_tags_go_in_gateway_header_as_json_map() -> None:
    import json

    headers = load_config({"ATLAS_PROMPT_VERSION": "v"}).request_tags_headers()
    assert list(headers) == ["Databricks-Ai-Gateway-Request-Tags"]
    assert json.loads(headers["Databricks-Ai-Gateway-Request-Tags"]) == {
        "app": "agent-atlas",
        "prompt_version": "v",
    }
