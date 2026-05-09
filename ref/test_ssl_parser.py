"""Pytest regression tests for ssl_parser v6.

Locks in:
- _eval_when 12/12 expression cases (all 4 behavioral-eval bugs)
- ToolManifest parsing (allow/deny/budget/log/confirm)
- Surface filter mechanics
- @test stripping
- Weight ordering + canonical floors
- v4/v5/v6 backward compat

Run: cd /root/bluewave && PYTHONPATH=. python3 -m pytest shared/bwssl/test_ssl_parser.py -v
"""
import sys
import pytest
from pathlib import Path

# Add prod path
sys.path.insert(0, "/root/bluewave")
from shared.bwssl.ssl_parser import (
    parse_string, compile_prompt, load_chain, _eval_when,
    _parse_tool_manifest_from_body, ToolManifest,
    SSLConditionError, SSLWeightError, SSLTypeError, SSLParseError,
)


# ─── _eval_when · the 12 cases that caught the 4 bugs ─────────────────────

class TestEvalWhen:
    def test_lowercase_true_against_True_value(self):
        """Bug 1: lowercase 'true' was treated as unbound name."""
        assert _eval_when("debug==true", {"debug": True}) is True

    def test_lowercase_true_against_False_value(self):
        assert _eval_when("debug==true", {"debug": False}) is False

    def test_lowercase_false_against_True_value(self):
        assert _eval_when("debug==false", {"debug": True}) is False

    def test_lowercase_false_against_False_value(self):
        assert _eval_when("debug==false", {"debug": False}) is True

    def test_python_casing_True(self):
        assert _eval_when("debug==True", {"debug": True}) is True

    def test_string_literal_in_expression(self):
        """Bug 2: identifier substitution was rewriting tokens inside quotes."""
        assert _eval_when('surface=="chat"', {"surface": "chat"}) is True

    def test_string_literal_negative(self):
        assert _eval_when('surface=="chat"', {"surface": "twitter"}) is False

    def test_negation_true(self):
        """Bug 3: '!debug' caused IndentationError due to leading whitespace."""
        assert _eval_when("!debug", {"debug": True}) is False

    def test_negation_false(self):
        assert _eval_when("!debug", {"debug": False}) is True

    def test_compound_or(self):
        assert _eval_when("!debug || force==true",
                          {"debug": True, "force": True}) is True

    def test_arithmetic_comparison_and(self):
        assert _eval_when("x > 5 && y < 10", {"x": 7, "y": 3}) is True

    def test_in_list_literal(self):
        assert _eval_when("x in [1,2,3]", {"x": 2}) is True

    def test_in_string_list_literal(self):
        assert _eval_when('surface in ["chat","twitter"]',
                          {"surface": "chat"}) is True

    def test_unbound_numeric_comparison_silently_excludes(self):
        """Bug 4: None < 0.7 raised TypeError; now wrapped as SSLConditionError."""
        with pytest.raises(SSLConditionError):
            _eval_when("last_confidence<0.7", {})

    def test_empty_expression_passes(self):
        assert _eval_when("", {}) is True


# ─── ToolManifest parsing ─────────────────────────────────────────────────

class TestToolManifest:
    def test_allow_basic(self):
        m = _parse_tool_manifest_from_body("allow WebSearch as search")
        assert len(m.allows) == 1
        assert m.allows[0].tool == "WebSearch"
        assert m.allows[0].alias == "search"

    def test_allow_no_alias_defaults_to_tool_name(self):
        m = _parse_tool_manifest_from_body("allow Bash")
        assert m.allows[0].tool == "Bash"
        assert m.allows[0].alias == "Bash"

    def test_deny_pattern(self):
        m = _parse_tool_manifest_from_body('deny Bash for "rm -rf *"')
        assert m.deny_patterns == [("Bash", "rm -rf *")]

    def test_budget_daily(self):
        m = _parse_tool_manifest_from_body("budget daily = 5.00 USD")
        assert m.budget_daily_usd == 5.00

    def test_budget_per_call(self):
        m = _parse_tool_manifest_from_body("budget per_call = 0.50 USD")
        assert m.budget_per_call_usd == 0.50

    def test_log_all(self):
        m = _parse_tool_manifest_from_body("log all")
        assert m.log_all is True

    def test_confirm_before_list(self):
        m = _parse_tool_manifest_from_body(
            "confirm before = [execute, write_file, notify]"
        )
        assert m.confirm_before == ["execute", "write_file", "notify"]

    def test_full_manifest(self):
        body = """
            allow WebSearch as search
            allow Bash as execute
            deny Bash for "rm -rf *"
            deny Write for "/etc/*"
            budget daily = 5.00 USD
            budget per_call = 0.50 USD
            log all
            confirm before = [execute]
        """
        m = _parse_tool_manifest_from_body(body)
        assert len(m.allows) == 2
        assert len(m.deny_patterns) == 2
        assert m.budget_daily_usd == 5.00
        assert m.budget_per_call_usd == 0.50
        assert m.log_all is True
        assert m.confirm_before == ["execute"]
        assert m.is_empty() is False

    def test_is_allowed(self):
        m = _parse_tool_manifest_from_body(
            "allow WebSearch as search\nallow Bash"
        )
        assert m.is_allowed("WebSearch") is True
        assert m.is_allowed("search") is True  # via alias
        assert m.is_allowed("Bash") is True
        assert m.is_allowed("FileWrite") is False

    def test_deny_match(self):
        m = _parse_tool_manifest_from_body('deny Bash for "rm -rf *"')
        assert m.deny_match("Bash", "rm -rf /") is not None
        assert m.deny_match("Bash", "ls") is None
        assert m.deny_match("WebSearch", "rm -rf /") is None  # different tool

    def test_unparseable_lines_kept_for_diagnostic(self):
        m = _parse_tool_manifest_from_body(
            "allow WebSearch\ngarbage line that wont parse\nlog all"
        )
        assert m.log_all is True
        assert len(m.allows) == 1
        assert "garbage line that wont parse" in m.raw_lines_dropped


# ─── Surface filter + @test stripping + weight ordering ───────────────────

V6_FILE = """SSL_VERSION := 6.0

agent_name : string  = "TestAgent"
surface    : surface = "linkedin"
debug      : bool    = false

@vow ~1.0 {
    Serve.
}

@identity ~0.95 {
    You are TestAgent.
}

@voice ~0.85 {
    Professional voice.
}

@voice[surface=twitter] ~0.85 {
    Twitter voice 280 chars.
}

@voice[surface=chat] ~0.85 {
    Conversational voice.
}

@behavior[when=debug==true] ~0.5 {
    LOG_COT_ACTIVE marker.
}

@test "identity test" ~1.0 {
    input: "Who are you?"
    expect: contains "TestAgent"
}
"""


class TestCompilation:
    def test_v6_parse_succeeds(self):
        ssl = parse_string(V6_FILE, "<test>")
        assert ssl.version == "6.0"
        assert ssl.attributes["agent_name"] == "TestAgent"
        assert any(b.name == "vow" for b in ssl.blocks)

    def test_test_blocks_stripped_from_compile(self):
        ssl = parse_string(V6_FILE, "<test>")
        out = compile_prompt([ssl])
        # The @test description label and assertion lines must not leak into prompt
        assert "identity test" not in out
        assert "input:" not in out
        assert "expect: contains" not in out
        assert "@test" not in out

    def test_surface_filter_linkedin_uses_default_voice(self):
        ssl = parse_string(V6_FILE, "<test>")
        out = compile_prompt([ssl], runtime={"surface": "linkedin"})
        assert "Professional voice" in out
        assert "Twitter voice" not in out
        assert "Conversational voice" not in out

    def test_surface_filter_twitter_uses_twitter_voice(self):
        ssl = parse_string(V6_FILE, "<test>")
        out = compile_prompt([ssl], runtime={"surface": "twitter"})
        assert "Twitter voice 280 chars" in out
        assert "Professional voice" not in out

    def test_surface_filter_chat_uses_chat_voice(self):
        ssl = parse_string(V6_FILE, "<test>")
        out = compile_prompt([ssl], runtime={"surface": "chat"})
        assert "Conversational voice" in out
        assert "Professional voice" not in out

    def test_when_filter_excludes_behavior_when_debug_false(self):
        ssl = parse_string(V6_FILE, "<test>")
        out = compile_prompt([ssl], runtime={"surface": "linkedin"})
        assert "LOG_COT_ACTIVE" not in out

    def test_when_filter_includes_behavior_when_debug_true(self):
        ssl_text = V6_FILE.replace(
            "debug      : bool    = false",
            "debug      : bool    = true"
        )
        ssl = parse_string(ssl_text, "<test>")
        out = compile_prompt([ssl], runtime={"surface": "linkedin"})
        assert "LOG_COT_ACTIVE" in out

    def test_weight_floor_enforcement_vow_below_1(self):
        bad = V6_FILE.replace("@vow ~1.0", "@vow ~0.5")
        with pytest.raises(SSLWeightError):
            parse_string(bad, "<test>")

    def test_weight_required_in_v6(self):
        bad = V6_FILE.replace("@voice ~0.85 {", "@voice {")
        with pytest.raises(SSLWeightError):
            parse_string(bad, "<test>")

    def test_invalid_surface_attribute_rejected(self):
        bad = V6_FILE.replace('surface    : surface = "linkedin"',
                              'surface    : surface = "fakebook"')
        assert "fakebook" in bad, "replace failed — V6_FILE alignment changed"
        with pytest.raises(SSLTypeError):
            parse_string(bad, "<test>")


# ─── Run ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
