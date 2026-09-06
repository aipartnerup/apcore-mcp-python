"""Cross-language conformance: ACL Config Bus loading.

Drives the Python builder from the shared fixture at
``apcore-mcp/conformance/fixtures/acl_config.json``. The TypeScript and Rust
bridges run the same fixture through their own builders; all three
implementations must agree on (rule_count, default_effect) and on which
inputs are rejected.
"""

from __future__ import annotations

import pytest

from apcore_mcp.acl_builder import build_acl_from_config
from tests.conformance_fixtures import load_fixture

# ---------------------------------------------------------------------------
# Success cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    load_fixture("acl_config.json")["test_cases"],
    ids=lambda c: c["id"],
)
def test_conformance_success_case(case: dict):
    result = build_acl_from_config(case["input"])
    expected = case["expected_acl"]
    if expected is None:
        assert result is None, f"{case['id']}: expected no ACL, got {result!r}"
        return

    assert result is not None, f"{case['id']}: expected ACL, got None"
    # Access the rule count via the documented `rules()` accessor or private fallback.
    rules = getattr(result, "rules", None)
    rule_list = rules() if callable(rules) else getattr(result, "_rules", [])
    assert len(rule_list) == expected["rule_count"], (
        f"{case['id']}: rule_count mismatch — got {len(rule_list)}, " f"expected {expected['rule_count']}"
    )
    # default_effect accessor is a private attribute in Python; check both.
    default_effect = getattr(result, "default_effect", None) or getattr(result, "_default_effect", None)
    assert default_effect == expected["default_effect"], (
        f"{case['id']}: default_effect mismatch — got {default_effect!r}, " f"expected {expected['default_effect']!r}"
    )


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    load_fixture("acl_config.json")["error_cases"],
    ids=lambda c: c["id"],
)
def test_conformance_error_case(case: dict):
    with pytest.raises(ValueError) as exc_info:
        build_acl_from_config(case["input"])
    message = str(exc_info.value)

    # contract_version 1.2 accepts `expected_error_substring` (a single string,
    # as in 1.0/1.1) and/or `expected_error_substrings` (an array); every
    # fragment present must appear. The array form exists because a §6.2.1
    # shape case has to pin BOTH the bridge's `mcp.acl.rules[i]` prefix and the
    # axis named by the reason — with one string all twelve shape cases would
    # carry an identical expectation and the fixture could not tell them apart.
    expected: list[str] = []
    if case.get("expected_error_substring"):
        expected.append(case["expected_error_substring"])
    expected.extend(case.get("expected_error_substrings") or [])
    assert expected, f"{case['id']}: fixture case carries no expectation"

    for fragment in expected:
        assert fragment in message, f"{case['id']}: error message {message!r} missing substring {fragment!r}"

    # `expected_error_names_field` asserts the message names the offending
    # field. It is what the fixture pins INSTEAD of a reason phrase: the reason
    # is apcore's, and its wording differs per SDK (apcore-python names the
    # type, apcore-js the rule index, and the sentences share almost nothing).
    field = case.get("expected_error_names_field")
    if field:
        # The BARE name, not the quoted form: apcore-python and apcore-js write
        # `'callers'` while apcore-rust writes `'callers[1]'`, naming the
        # offending element. The bare token is the only spelling all three share.
        assert field in message, f"{case['id']}: error {message!r} does not name the field {field!r}"

    # `must_not_contain` asserts a fragment is ABSENT. It is how an ordering
    # case separates "named the right axis" from "rejected something".
    forbidden = case.get("must_not_contain")
    if forbidden:
        assert forbidden not in message, (
            f"{case['id']}: error message {message!r} contains {forbidden!r}, which means the "
            f"wrong validation axis was reported (PROTOCOL_SPEC §6.2.1 order)"
        )
