"""Build an apcore ACL instance from a Config Bus `mcp.acl` section.

Config Bus schema (YAML) — a worked example protecting the ``system.*``
management surface (aiperceivable/apcore-mcp#14):

.. code-block:: yaml

    mcp:
      acl:
        default_effect: deny
        rules:
          # Rule 1 — read-only management surface.
          # MUST precede the catch-all deny: evaluation is first-match-wins.
          - callers: ["@external"]
            targets: ["system.health.*", "system.usage.*", "system.manifest.*"]
            effect: allow
            conditions:
              identity_types: ["human"]
              roles: ["apcore.admin"]
            description: "Console read access to the management surface"

          # Rule 2 — administration. ACL allow is not execution:
          # system.control.* declares requiresApproval=true and still passes the approval gate.
          - callers: ["@external"]
            targets: ["system.control.*"]
            effect: allow
            conditions:
              identity_types: ["human"]
              roles: ["apcore.admin"]
            description: "Administration; requires_approval still applies"

          # Rule 3 — catch-all deny. MUST be last.
          # Agent identities, anonymous callers and insufficient roles land here.
          - callers: ["@external"]
            targets: ["system.*"]
            effect: deny
            description: "Block all other access to system modules"

Two mechanics make the ``conditions`` blocks above load-bearing rather than
decorative:

- Every MCP call arrives with ``caller_id`` set to ``null`` — the MCP
  transport has no notion of "which caller". apcore's ACL normalizes a
  ``null`` caller_id to the synthetic identity ``@external`` before matching
  ``callers`` patterns. This means ``callers`` can **never** distinguish a
  human at a console from an autonomous agent — both arrive as
  ``@external``. Only ``conditions`` (evaluated against the authenticated
  JWT's ``identity_types`` / ``roles`` claims) can make that distinction, so
  any rule meant to gate humans vs. agents MUST use ``conditions``, never a
  ``callers`` pattern.
- Rules are evaluated **first-match-wins** — the first rule whose
  ``callers``/``targets``/``conditions`` all match a call decides the
  ``effect``, and no later rule is consulted. A narrower ``allow`` rule
  MUST be listed before a broader ``deny`` (or vice versa) that would
  otherwise shadow it.

A rule may also carry ``approval: required`` (apcore>=0.28.0, spec §6.1.6) to
put a matching call to a human even though the rule's ``effect`` is
``allow`` — see :data:`_ALLOWED_RULE_KEYS`.

The bridge accepts this dict and constructs an ``apcore.ACL`` with the given
rules and default effect. Invalid entries fail loudly at startup. The same
schema is consumed by the TypeScript and Rust bridges via the shared
``conformance/fixtures/acl_config.json`` fixture.

Security note: enabling ``sys_modules.enabled`` (in apcore's own Config Bus
namespace) registers the ``system.*`` modules above into the registry this
server exposes, but it does **not** by itself protect them. ``apcore.ACL``
is only attached when this module's ``mcp.acl`` Config Bus section (or the
``acl=`` constructor argument) is actually configured — with no ``acl/``
directory to discover and no ``mcp.acl`` section, ``ACL.discover()`` returns
``None`` (documented in ``apcore.acl``), which is indistinguishable from
"no ACL was ever configured": every caller reaches every ``system.*``
module, including ``system.control.*``. Always pair
``sys_modules.enabled: true`` with an ``mcp.acl`` section like the one
above.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ALLOWED_EFFECTS = frozenset({"allow", "deny"})
# "approval" joined the set in apcore 0.28.0 (spec §6.1.6, argument-scoped
# approval, aiperceivable/apcore-mcp#14). Before this, a Config Bus rule
# carrying `approval: required` was rejected here with "unexpected keys"
# before it ever reached `ACLRule`, so the feature was unreachable from YAML.
_ALLOWED_RULE_KEYS = frozenset({"callers", "targets", "effect", "description", "conditions", "approval"})
# The only two values `ACLRule.approval` accepts (apcore.acl.APPROVAL_REQUIRED
# / APPROVAL_NOT_REQUIRED). Validated here too so a typo fails with a
# Config-Bus-flavoured message instead of surfacing from deep inside apcore.
_ALLOWED_APPROVALS = frozenset({"required", "not_required"})


def build_acl_from_config(acl_config: Any | None) -> Any | None:
    """Construct an ``apcore.ACL`` from a Config Bus ``mcp.acl`` mapping.

    Returns ``None`` when ``acl_config`` is falsy (no ACL section configured).
    Raises :class:`ValueError` on malformed entries so misconfiguration fails
    loudly at startup.
    """
    if not acl_config:
        return None

    if not isinstance(acl_config, dict):
        raise ValueError(
            f"mcp.acl must be a mapping with 'rules' and optional " f"'default_effect', got {type(acl_config).__name__}"
        )

    try:
        from apcore import ACL, ACLRule
    except ImportError as exc:
        raise RuntimeError("Config Bus `mcp.acl` requires apcore>=0.18 with ACL support") from exc

    default_effect = acl_config.get("default_effect", "deny")
    if default_effect not in _ALLOWED_EFFECTS:
        raise ValueError(f"mcp.acl.default_effect must be 'allow' or 'deny', got {default_effect!r}")

    raw_rules = acl_config.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError(f"mcp.acl.rules must be a list, got {type(raw_rules).__name__}")

    rules: list[Any] = []
    for idx, entry in enumerate(raw_rules):
        if not isinstance(entry, dict):
            raise ValueError(f"mcp.acl.rules[{idx}] must be an object, got {type(entry).__name__}")
        extra = set(entry.keys()) - _ALLOWED_RULE_KEYS
        if extra:
            raise ValueError(f"mcp.acl.rules[{idx}] got unexpected keys: {sorted(extra)}")

        callers = entry.get("callers")
        targets = entry.get("targets")
        effect = entry.get("effect")

        # PROTOCOL_SPEC §6.2.1 (apcore 0.29.0, spec v1.31.0) fixes the order in
        # which a rule bad on more than one axis is refused: `effect` ->
        # `approval` -> `callers` -> `targets`, with the rule index dominating.
        # This builder used to run it in reverse, so a rule wrong in both
        # `effect` and `callers` was refused for `callers` here and for
        # `effect` by apcore's own doors — the same file, two answers,
        # depending on which door it reached first. The unknown-key check above
        # stays ahead of all four: it is a Config-Bus shape fault with no
        # apcore counterpart. `default_effect` is judged ahead of the rule loop,
        # where it already was.
        if effect not in _ALLOWED_EFFECTS:
            raise ValueError(f"mcp.acl.rules[{idx}] 'effect' must be 'allow' or 'deny', got {effect!r}")

        approval = entry.get("approval")
        if "approval" in entry and approval is not None and approval not in _ALLOWED_APPROVALS:
            raise ValueError(f"mcp.acl.rules[{idx}] 'approval' must be 'required' or 'not_required', got {approval!r}")

        if not isinstance(callers, list) or not callers:
            raise ValueError(f"mcp.acl.rules[{idx}] 'callers' must be a non-empty list")
        if not isinstance(targets, list) or not targets:
            raise ValueError(f"mcp.acl.rules[{idx}] 'targets' must be a non-empty list")

        rule_kwargs: dict[str, Any] = {
            "callers": list(callers),
            "targets": list(targets),
            "effect": effect,
        }
        if "description" in entry:
            rule_kwargs["description"] = entry["description"] or ""
        if "conditions" in entry and entry["conditions"] is not None:
            if not isinstance(entry["conditions"], dict):
                raise ValueError(f"mcp.acl.rules[{idx}] 'conditions' must be an object or null")
            rule_kwargs["conditions"] = entry["conditions"]
        if "approval" in entry and approval is not None:
            # `ACLRule.__post_init__` additionally rejects `approval: required`
            # paired with `effect: deny` (meaningless — a refusal is not a
            # question); left to apcore rather than duplicated here so the
            # rule stays the single source of truth for that combination.
            rule_kwargs["approval"] = approval

        rules.append(_build_rule(ACLRule, rule_kwargs, idx))

    logger.info("Built ACL with %d rule(s), default_effect=%s", len(rules), default_effect)
    return _construct_acl(ACL, rules, default_effect)


def _build_rule(acl_rule_cls: Any, kwargs: dict[str, Any], idx: int) -> Any:
    """Construct one ``ACLRule``, re-raising apcore's refusal with the rule index.

    apcore raises ``ACLRuleError`` from inside ``ACLRule.__post_init__`` and its
    message names the **type**, not the rule — ``ACLRule has an invalid
    'targets' (PROTOCOL_SPEC §6.2.1): …``. That is correct for apcore, where a
    rule under construction has no position yet and §6.2.1 forbids inventing
    one, and useless to an operator holding a 20-rule YAML block: the §6.2.1
    arity closure's entire remedy is its message, and delivering it without the
    index throws that away.

    It is also the wrong *type* in Python. ``ACLRuleError`` extends
    ``apcore.errors.ModuleError``, not ``ValueError``, so this builder's
    documented "raises ValueError on malformed entries" contract was false for
    every §6.2.1 fault, and a caller with ``except ValueError:`` around startup
    silently stopped catching them.

    apcore's message is preserved verbatim after the prefix — the reason text
    is apcore's to own — and the original is chained as ``__cause__``.
    """
    try:
        return acl_rule_cls(**kwargs)
    except Exception as exc:
        if type(exc).__name__ != "ACLRuleError":
            raise
        raise ValueError(f"mcp.acl.rules[{idx}] {exc}") from exc


def _construct_acl(acl_cls: Any, rules: list[Any], default_effect: str) -> Any:
    """Construct the ``ACL``, re-raising apcore's refusal under ``mcp.acl``.

    apcore 0.29.0 made ``ACL(rules=[...])`` re-validate every rule it is handed,
    including one mutated after its own construction (spec v1.33.0). A fault
    raised here is section-scoped rather than rule-scoped — the constructor
    reports in list order but does not surface an index — so the prefix is
    ``mcp.acl`` with no ``[i]``.
    """
    try:
        return acl_cls(rules=rules, default_effect=default_effect)
    except Exception as exc:
        if type(exc).__name__ != "ACLRuleError":
            raise
        raise ValueError(f"mcp.acl {exc}") from exc
