"""FR-ACL-004 / PROTOCOL_SPEC §6.2.1 tier 2: rules that load cleanly and can
protect nothing.

This wiring existed and fired (unlike TypeScript, dead, and Rust, missing
entirely) but read the wrong field names off apcore's real
``RuleValidationFinding`` object (``path``/``reason``/``message`` instead of
``condition_path`` / no free-text field at all), so every warning rendered as
``'?': `` with no actionable content. No test previously called this function
against a real ``ACL`` instance to catch it.
"""

from __future__ import annotations

import logging

from apcore import ACL, ACLRule

from apcore_mcp.apcore_mcp import _warn_acl_rules_that_protect_nothing


class _FakeExecutor:
    def __init__(self, acl: object) -> None:
        self.acl = acl


def test_inert_rule_produces_an_actionable_warning(caplog: object) -> None:
    rule = ACLRule(callers=["*"], targets=["$not", "*"], effect="deny")
    acl = ACL(rules=[rule], default_effect="allow")

    with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
        _warn_acl_rules_that_protect_nothing(_FakeExecutor(acl))

    messages = [r.message for r in caplog.records]  # type: ignore[attr-defined]
    assert len(messages) == 1
    message = messages[0]
    assert "mcp.acl.rules[0]" in message
    assert "'targets'" in message
    assert "'?'" not in message  # the exact bug: a missing field defaulted to "?"
    assert "protects nothing" in message


def test_well_formed_rule_produces_no_warning(caplog: object) -> None:
    rule = ACLRule(callers=["*"], targets=["*"], effect="allow")
    acl = ACL(rules=[rule], default_effect="deny")

    with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
        _warn_acl_rules_that_protect_nothing(_FakeExecutor(acl))

    assert caplog.records == []  # type: ignore[attr-defined]


def test_no_acl_is_a_silent_no_op(caplog: object) -> None:
    with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
        _warn_acl_rules_that_protect_nothing(_FakeExecutor(None))

    assert caplog.records == []  # type: ignore[attr-defined]
