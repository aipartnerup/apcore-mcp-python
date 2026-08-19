# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.18.0] - 2026-08-19

### Security

- **`__apcore_module_preview` no longer discloses module introspection to a caller the ACL denied.** The bridge serialises `Executor.validate()`'s `PreflightResult` verbatim (`_preflight_to_dict` copies `predicted_changes` and `checks` straight through), and apcore `<=0.26.0` gated `Module.preflight()` / `Module.preview()` on module lookup alone — pipeline Step 3 — while the ACL check is Step 4. A denied caller therefore ran module-authored code and received what it returned: for a command-wrapping module the resolved binary and its argv, for a writer the target of the side effect. Raising the `apcore` floor to `>=0.27.0` closes it at the layer that owns the gate (PROTOCOL_SPEC §12.8.5.1, spec v1.13.0, apcore#96); no bridge code changed. A denied caller still receives the failed `acl` check, so it still learns why. Pinned by `tests/server/test_preflight_disclosure.py`, which drives a real `Executor` over a real `Registry` and a real `ACL` and asserts a sentinel binary path and argv appear nowhere in the denied envelope — 5 of its 8 cases fail against apcore 0.26.0.

### Changed

- **Required `apcore` floor raised to `>=0.27.0`.** Of the 0.27 breaking changes, only the `validate()` disclosure gate above reaches this package: the bridge builds no pipeline from YAML, does not use `SchemaValidator`'s coercion knob, does not configure `obs.redaction`, and registers no `StepMiddleware`.

## [0.17.2] - 2026-07-14

Patch release. Fixes the MCP elicitation approval flow and bumps the required `apcore` floor to `0.26.0` (Execution Policy §7.9 / governance events / no-handler fail-loud — additive, no breaking changes). All 856 tests pass (3 new).

### Fixed

- **`ElicitationApprovalHandler` now sends a non-empty elicitation `requestedSchema`.** The approval elicitation was previously sent with an empty `{}` schema; minimal SDK clients tolerate this, but clients that render an approval form (Cursor, Codex, ...) ignore or reject an empty schema, so the request returned no response and the gate failed closed ("Elicitation returned no response"). The handler now sends an object schema with a boolean `approve` field and honors an explicit `approve: false` from the form.
- **Elicitation failures are no longer swallowed silently.** The `ExecutionRouter` elicit callback and the approval handler now log at `warning` (was `debug`) with the traceback, so a failing elicitation surfaces instead of silently denying.

### Changed

- **Required `apcore` floor raised to `>=0.26.0`** to align the ecosystem on the 0.26.0 governance layer. Additive on the apcore side; all existing tests pass unmodified.

## [0.17.1] - 2026-07-07

Patch release. Bumps the required `apcore-toolkit` floor to `0.10.0` (which adds the shared annotation-preservation conformance verifier and centralizes the Python `RegistryWriter` — additive, no breaking changes). No code or API changes; all 853 tests pass unmodified against apcore-toolkit 0.10.0.

## [0.17.0] - 2026-06-23

Audit-driven hardening of the serve/embed entry points and the Phase B approval
chain, plus the apcore 0.25 / apcore-toolkit 0.9.1 dependency uplift.

### Added

- **Top-level `serve()` / `async_serve()` now forward `approval_store` /
  `approval_notify`** to `APCoreMCP`, so Phase B async approval is configurable
  from the top-level entry points (previously only via the `APCoreMCP` class).
- **Non-blocking `MCPServer` reached parity with `serve()` / `APCoreMCP`**: it now
  forwards `output_formatter` / `output_format`, `strategy`, `observability`,
  `redact_output`, `trace`, explorer branding, approval (`handler` / `store` /
  `notify`), `middleware`, `acl`, `dynamic`, and shared input validation, via a
  new shared `APCoreMCP._build_serve_coro()` assembly helper (also used by the
  blocking `serve()`, removing the duplicated pipeline).

### Fixed

- **Approval-bridge gating was too strict**: `ApprovalBridge` (and the
  `__apcore_approval_check` meta-tool) is now registered whenever an
  `approval_handler` is present, no longer requiring `approval_store` as well.
  Passing a `StorageBackedApprovalHandler(store)` directly as `approval_handler`
  now registers the meta-tool and starts/stops the store lifecycle end-to-end.
- **TM-4 session-scoped task cancellation was dead code**: `_scoped_session` and
  `set_async_task_bridge` were never invoked by the transports, so
  `transport_session_var` stayed `None` and client disconnects never fired
  `cancel_session_tasks`. Wired `_run_scoped()` into all four transport entry
  points (`run_stdio`, `run_streamable_http`, `run_sse`,
  `build_streamable_http_app`); disconnect-cancellation now actually fires.

### Changed

- Unified explorer-branding defaults between the top-level and instance
  `serve()` / `async_serve()`; added `dynamic` to top-level `async_serve()` for
  parity with `serve()`.
- Raised dependency floors to `apcore>=0.25.0` and `apcore-toolkit>=0.9.1`
  (drop-in; no consumed API changed). All 853 tests pass.


## [0.16.0] - 2026-06-12

### Added

- **Approval Phase B: async polling via `__apcore_approval_check` meta-tool**.
  apcore-mcp now supports out-of-band human approvals that do not block the MCP connection.

  New public API:
  - `ApprovalStore` (Protocol) — pluggable persistence interface; three async methods:
    `save_pending`, `get_result`, `resolve`.
  - `InMemoryApprovalStore` — in-process implementation for testing/local dev.
    Ships with bounded memory management: per-record TTL via `call_later`, a background
    sweep task, and a `max_records` hard cap with oldest-pending eviction.
    **Not suitable for production** (no persistence, no cross-process sharing).
  - `StorageBackedApprovalHandler` (implements `apcore.ApprovalHandler`) — writes
    pending records on `request_approval()`, reads them on `check_approval()`.
    Optional `notify_callback` lets callers fan out to Slack/email/webhooks.
  - `ApprovalBridge` — registers `__apcore_approval_check` as an MCP meta-tool,
    symmetric with `AsyncTaskBridge`.

  Usage::

      from apcore_mcp import APCoreMCP, InMemoryApprovalStore

      store = InMemoryApprovalStore()
      mcp = APCoreMCP("./extensions", approval_store=store)

      # External system approves out-of-band:
      await store.resolve(approval_id, approved=True)

  Phase A (synchronous `ElicitationApprovalHandler`) is unchanged. All 841 tests pass.

Closes [issue #70](https://github.com/aiperceivable/apcore/issues/70): remove bridge-level `user_fixable` stamping now that apcore 0.24.0 resolves it at construction time via `_USER_FIXABLE_BY_CODE`.

### Changed

- **Raised apcore floor to `>=0.24.0`** (`pyproject.toml`). apcore 0.24.0 introduced `_USER_FIXABLE_BY_CODE`, which auto-populates `user_fixable` on `ModuleError` at construction time for all user-actionable codes (`SCHEMA_VALIDATION_ERROR`, `GENERAL_INVALID_INPUT`, `MODULE_NOT_FOUND`, `VERSION_CONSTRAINT_INVALID`, `BINDING_SCHEMA_INFERENCE_FAILED`, `BINDING_SCHEMA_MODE_CONFLICT`, `BINDING_STRICT_SCHEMA_INCOMPATIBLE`, `DEPENDENCY_NOT_FOUND`, `DEPENDENCY_VERSION_MISMATCH` → `True`; governance/system codes → `False`; `MODULE_EXECUTE_ERROR` and unlisted → `None`).
- **Removed bridge-level `_USER_FIXABLE_CODES` constant and stamping block** from `ErrorMapper._handle_apcore_error` (`src/apcore_mcp/adapters/errors.py`). The bridge no longer overrides or duplicates apcore's own policy; `user_fixable` flows through the existing `_attach_ai_guidance` path unchanged. Removed the fast-path `isinstance` branches for `DependencyNotFoundError` / `DependencyVersionMismatchError` that hardcoded `"userFixable": True`. All 806 tests pass.

## [0.15.0] - 2026-05-29

Audit-driven consistency work from `/apcore-skills:audit --scope mcp`. Eight per-repo fixes land here; the docs/spec repo (`apcore-mcp/`) remains at 0.15.0 because no spec contracts changed, so SDK versions also stay at 0.15.0 pending an explicit release decision. The entries below describe changes already committed on `main`.

### Changed

- **Upgraded required runtime to apcore 0.22.0 and apcore-toolkit 0.8.0** (`pyproject.toml`: `apcore>=0.22.0`, `apcore-toolkit>=0.8.0`). Adopts the apcore 0.22.0 `Context.create()` signature unification (D-24): the cancel token registered for each MCP tool call is now passed as the first-class `cancel_token=` parameter at both `ExecutionRouter._dispatch` context-creation sites, replacing the prior post-hoc `context.cancel_token = …` assignment that the apcore 0.22.0 changelog explicitly flagged in `apcore-mcp-python`. No public API change; full suite green (807 passed).

### Breaking Changes

- **`OpenAIConverter.convert_descriptor(strict=...)` default flipped from `False` to `True`** ([D11-5] / OC-1). Cross-SDK parity with `apcore-mcp-typescript` 0.14.0+, which already defaults to strict mode. Callers that previously relied on the lax default (`additionalProperties` allowed, original `required` ordering preserved) must now pass `strict=False` explicitly. Strict mode injects `additionalProperties: false`, hoists all properties into `required` (sorted alphabetically, with optionals widened to nullable), and emits `"strict": true` on the function definition — the format OpenAI Structured Outputs expects. Note: the top-level `to_openai_tools()` and `APCoreMCP.to_openai_tools()` wrappers (and `OpenAIConverter.convert_registry`) still default to `strict=False` and pass that through; this change only affects callers using `convert_descriptor` directly with no `strict` argument.

### Fixed

- **[D10-001] `ErrorMapper.to_mcp_error` emits canonical `"Schema validation failed"` for `SCHEMA_VALIDATION_ERROR` even when `details` is `None`.** Previously Python's `if code == SCHEMA_VALIDATION_ERROR and details is not None` guard fell through to passthrough and emitted the raw `error.message`, while Rust+TS unconditionally emitted `"Schema validation failed"`. Cross-SDK callers grouping logs or doing i18n on the canonical string no longer silently miss Python.
- **[D10-002] `MCPServerFactory.create_server(name)` now validates non-empty + max 255 chars per spec.** Previously the spec-declared `ValueError` was silently absent; empty / oversized names propagated to the underlying MCP server constructor. Fix applied across all three SDKs.
- **[D11-6] Router-fallback async-bridge dispatch now extracts `_meta.traceparent` and forwards `transport_session_var.get()` as `session_key`.** Previously the factory layer (`register_handlers`) extracted both, but the defensive router-layer fallback path (`_dispatch`) silently lost W3C trace propagation + session mass-cancel indexing. Direct-router consumers (custom test harnesses) now get parity with the factory path.

### Refactored

- **[D9-001] Collapsed parallel `serve()` / `async_serve()` / `to_openai_tools()` pipelines** into a single canonical implementation on `APCoreMCP`. Prior to 0.16.0 the same pipeline was assembled twice — once in the module-level functions in `apcore_mcp/__init__.py` and once in `APCoreMCP`, which then *delegated back* to the module-level functions. Every new feature had to be wired in two places, which had already produced latent bugs in `extra_routes` typing (`list[Mount]` vs. `list[Route | Mount]`) and `metrics_collector` type narrowing. Post-refactor:
  - `APCoreMCP` owns Config Bus loading (via the relocated `_load_config_bus_overrides` helper), observability auto-wiring, async-task bridge construction, explorer routes, auth middleware, and transport selection.
  - Module-level `serve()`, `async_serve()`, and `to_openai_tools()` are now thin delegators that construct an `APCoreMCP` and forward to its instance methods. Their public signatures are unchanged.
  - `APCoreMCP.__init__` gained five new kwargs (`strategy`, `redact_output`, `trace`, `dynamic`, plus internal `_load_pipeline_from_config`) so it can absorb every option the legacy `serve()` signature exposed.
  - `APCoreMCP._build_server_components` now resolves `MCPServerFactory` / `ExecutionRouter` via the `apcore_mcp` package namespace so that existing tests patching `apcore_mcp.MCPServerFactory` / `apcore_mcp.ExecutionRouter` intercept both legacy and class-based entry points.
  - Net source LOC reduction: ~180 lines deleted across the two files. The buggy code paths around `metrics_collector` narrowing (formerly at `__init__.py:442/444/450/557/564/568`) and `extra_routes` typing (formerly at `__init__.py:743/745/751`) are gone, taking the nine pre-existing pyright errors with them.
- **[D9-004] Removed `apcore_mcp.to_mcp_error_any` free function.** The body was effectively `del error; return internal_error_response()` — a no-op delegator that was asymmetric with TypeScript / Rust (method-only on `ErrorMapper`). Callers should use `internal_error_response()` directly (identical observable behavior) or `ErrorMapper().to_mcp_error_any(error)` for the typed-error path.
- **[D9-007] Deleted `apcore_mcp.inspector` stub package.** A 7-line placeholder with module docstring describing future F-039 scope; zero importers. Will be re-created when the F-039 implementation begins.

### Changed

- **[D5-002] Migrated to `apcore.observability.context_logger.ObsLoggingMiddleware`.** The legacy `LoggingMiddleware` emits a `DeprecationWarning` targeting removal in apcore 1.0.0. Public surface (`log_inputs` / `log_outputs` constructor parameters) is preserved. Suite warnings dropped from 9 to 0.

Leverages **apcore 0.21.0 + apcore-toolkit 0.7.0**. Promotes three new
upstream capabilities into MCP-facing surface area: `Module.preview()`
(PROTOCOL_SPEC §5.6), `CircuitBreakerOpenError` (sync alignment A-001),
and `apcore_toolkit.format_module(style="markdown")`. Cross-SDK byte-
equivalent with `apcore-mcp-typescript` and `apcore-mcp-rust` 0.15.0.

### Changed

- **Dependency bump**: `apcore >= 0.21.0` (was `>= 0.19.0`); `apcore-toolkit >= 0.7.0` (was `>= 0.5.0`, optional `[markdown]` extra).

### Added

- **Built-in output format support**: Added `--output-format` (`json`, `csv`, `jsonl`) to CLI and `output_format` parameter to `serve()`. Leverages `apcore-toolkit` 0.7 for standard tabular formatting.
- **`__apcore_module_preview` meta-tool** (apcore 0.21 PROTOCOL_SPEC §5.6 / §12.8) — fifth reserved meta-tool alongside the four `__apcore_task_*` ones. Drives `executor.validate(module_id, inputs, context)` and returns a structured `{valid, requires_approval, predicted_changes, checks}` envelope WITHOUT executing the module. Lets AI orchestrators answer "what would change in the world if I called this?" before invoking destructive or stateful modules. `arguments: null` is preserved verbatim — the calling business decides whether null is a valid input. Structurally-impossible shapes (arrays, scalars) return a typed validation error.
- **`AsyncTaskBridge(executor=...)` constructor kwarg** — explicit Executor reference for the preview meta-tool. When omitted, falls back to the manager's bound executor. The `with_limits` factory wires this automatically.
- **`MCPServerFactory(rich_description=True)`** and **`OpenAIConverter.convert_descriptor(rich_description=True)` / `convert_registry(rich_description=True)`** — render `Tool.description` / OpenAI `function.description` as canonical apcore-toolkit Markdown (`format_module(style="markdown")`) instead of the plain one-line description. Includes title, description, parameters list, returns list, behavior table (only fields differing from defaults — toolkit 0.6 alignment), tags, and examples. LLMs select tools primarily from this string; Markdown packs more decision-relevant signal per token. Display-overlay `mcp.description` overrides still win first. One-shot WARN log when `apcore-toolkit` is not installed (recommend `pip install 'apcore-mcp[markdown]'`).
- **`apcore_mcp.markdown` module** — public helpers: `is_available()`, `descriptor_to_scanned_module(descriptor)`, `render_module_markdown(descriptor, *, display=True)`. The descriptor adapter is forwards-compatible across toolkit minor versions (introspects `dataclasses.fields(ScannedModule)` to drop unknown kwargs).
- **`CIRCUIT_BREAKER_OPEN` error mapping** (apcore 0.20 sync alignment A-001) — `ErrorMapper.to_mcp_error` now dispatches `apcore.errors.CircuitBreakerOpenError` to a retryable=True envelope with the per-module `aiGuidance` mirrored from the apcore error class. New constant `ERROR_CODES["CIRCUIT_BREAKER_OPEN"]`. Best-effort import shim keeps the mapper compatible with pre-0.20 apcore builds.

### Fixed

- **`AsyncTaskBridge` async-API alignment with apcore 0.20+** — adapts to apcore's `AsyncTaskManager.{submit,cancel,shutdown}` becoming async (D10-003 / D10-004). Bridge methods now `await` upstream calls; sync transport-layer cancel handlers route through `tokio`-style fire-and-forget patterns where applicable.
- **`__apcore_task_status` redactor try/except symmetry** — wraps the redactor call so a buggy redactor does not bring down the meta-tool; falls back to the unredacted result with a DEBUG log.

### Tests

- +9 new tests covering `__apcore_module_preview` (basic predict, missing module_id, `arguments: null` preserved, missing arguments preserved, array rejection, meta-tool registration), `CIRCUIT_BREAKER_OPEN` mapping (retryable + aiGuidance), and `rich_description` (Markdown rendering, display-overlay override, toolkit-missing fallback, `convert_registry` propagation, factory build_tool integration).
- Total suite: **771 passed** (was 758).

## [0.14.0] - 2026-05-01

### Changed

- **Dependency bump**: `apcore >= 0.19.0` (was `>= 0.18.0`).
- **New dependency**: `apcore-toolkit >= 0.5.0` — picks up the `ScannedModule.display` field and the `BindingLoader` pure-data loader (not wired in apcore-mcp; this project does not load binding YAML directly).
- `ExecutionRouter.handle_call` response `content` item type widened from `list[dict[str, str]]` to `list[dict[str, Any]]` to carry the optional `_meta` field. The factory translates this to MCP `TextContent.meta` on wire.
- `MCPServerFactory.register_handlers` gains optional `async_bridge` and `descriptor_lookup` kwargs. Backward-compatible: when omitted, behavior is unchanged.

### Added

- **W3C Trace Context propagation** — `ExecutionRouter` now parses `_meta.traceparent` on inbound `tools/call` requests and seeds the apcore `Context` with the extracted `TraceParent`. Responses carry `_meta.traceparent` (per `TextContent.meta`) built from `TraceContext.inject(context)`, letting MCP clients correlate trace chains across module boundaries. Relies on apcore 0.19's strict validation in `Context.create(trace_parent=...)` (all-zero/all-f trace ids are regenerated with a WARN).
- **Async Task Bridge** (F-043) — new `apcore_mcp.server.async_task_bridge.AsyncTaskBridge` wraps apcore's `AsyncTaskManager`. Modules whose descriptor carries `metadata.async == True` or `annotations.extra["mcp_async"] == "true"` are routed to `AsyncTaskManager.submit()` and return an immediate `{"task_id", "status": "pending"}` envelope. Four reserved MCP meta-tools are registered: `__apcore_task_submit`, `__apcore_task_status`, `__apcore_task_cancel`, `__apcore_task_list`. Progress fan-out is available via `_meta.progressToken` (bound per task). `MCPServerFactory.build_tool` now rejects any module whose id starts with `__apcore_`. Enable/disable via `APCoreMCP(async_tasks=...)` or `serve(async_tasks=...)` (default on). Tuning knobs: `async_max_concurrent`, `async_max_tasks`.
- **Observability auto-wiring** — `serve(observability=True)` / `APCoreMCP(observability=True)` instantiate `apcore.observability.MetricsCollector` + `MetricsMiddleware` and `UsageCollector` + `UsageMiddleware` on the Executor and expose `/{explorer_prefix}/api/usage` (and `/api/usage/{module_id}`) returning `ModuleUsageSummary` / `ModuleUsageDetail` JSON. The `metrics_collector=True` sentinel auto-provisions only the metrics middleware (no usage tracking). A user-supplied `MetricsExporter` object continues to work unchanged (back-compat).
- **`--observability` CLI flag** — toggles metrics + usage middleware and usage routes.
- **isinstance-based error dispatch** in `adapters/errors.py` — `TaskLimitExceededError`, `DependencyNotFoundError`, and `DependencyVersionMismatchError` are dispatched via `isinstance` checks against the apcore 0.19 error classes, not duck-typed codes.
- **Expanded `ModuleAnnotations` surfacing** in `AnnotationMapper.to_description_suffix`: `cache_ttl`, `cache_key_fields`, and `pagination_style` now appear in the description annotation block when non-default. Aligns with apcore 0.19's 12-field `ModuleAnnotations`.
- **`DEFAULT_ANNOTATIONS`** in `adapters/annotations.py` extended with `cache_ttl=0`, `cache_key_fields=None`, and `pagination_style="cursor"` to match apcore 0.19 defaults.
- **New error codes** in `constants.ERROR_CODES` and `ErrorMapper`:
  - `DEPENDENCY_NOT_FOUND` — raised by `resolve_dependencies` for missing required deps (replaces prior `ModuleLoadError` path per PROTOCOL_SPEC §5.15.2).
  - `DEPENDENCY_VERSION_MISMATCH` — raised when a declared `version` constraint is unsatisfied.
  - `TASK_LIMIT_EXCEEDED` — raised by `AsyncTaskManager.submit` at capacity. Mapped with `retryable: True`.
  - `VERSION_CONSTRAINT_INVALID` — raised on malformed version constraint strings.
  - `BINDING_SCHEMA_INFERENCE_FAILED` — replaces the deprecated `BINDING_SCHEMA_MISSING` code for auto-schema inference failures.
  - `BINDING_SCHEMA_MODE_CONFLICT`, `BINDING_STRICT_SCHEMA_INCOMPATIBLE`, `BINDING_POLICY_VIOLATION` — parse-time binding validation errors per DECLARATIVE_CONFIG_SPEC.

### Notes

- The `display` overlay resolution in `server/factory.py` already consumes `metadata["display"]["mcp"]` (alias / description / guidance) as produced by `DisplayResolver`; no changes needed for the 0.19 canonical `DisplayOverlay` shape.
- The apcore-toolkit `BindingLoader` was not wired in: apcore-mcp does not load `.binding.yaml` files directly. Registry-bound loads continue to flow through apcore's own `BindingLoader` inside the upstream SDK.
- Async task bridge is in-memory only; tasks do not survive server restart (matches apcore semantics).
- Meta-tool names use the reserved `__apcore_` prefix; user-registered modules with this prefix are now rejected at `build_tool` time to prevent shadowing.
- Usage endpoints are only mounted when Explorer is enabled; headless stdio deployments continue to have no HTTP surface.

### Cross-language sync (deferred-modules round, 2026-04-28)

- **Dependency bump**: `mcp-embedded-ui >= 0.4.0` (was `>= 0.3.1`). The new release ships `POST /tools/{name}/validate` (F7) — read-only schema validation, ungated by `allow_execute` or `auth_hook`. The route flows automatically through `create_explorer_mount`. **Resolves EUI-1.**
- **JWT-1 — `Authenticator.authenticate` is now `async`.** Existing sync implementations continue to work via the new `apcore_mcp.auth.protocol.call_authenticator(auth, headers)` helper, which inspects the return value and awaits if it's a coroutine. Aligns with TS+Rust on the unified `(headers: HeaderMap) -> Awaitable<Identity | None>` contract. Tests for `JWTAuthenticator` are now `async def`.
- **TM-4 — transport-disconnect cancellation forwarding.** `TransportManager.set_async_task_bridge(bridge)` matches TS `setAsyncTaskBridge` and Rust `set_cancel_handler`. The transport scopes a per-connection session id via the new `transport_session_var` `ContextVar`; `factory.handle_call_tool` forwards it as `session_key` to `bridge.submit(...)`, and on transport teardown the manager calls `bridge.cancel_session_tasks(session_id)`. Wired automatically by `serve()`, `async_serve()`, and `APCoreMCP.serve` / `async_serve` when an async bridge is present. 6 regression tests.
- **EB-2 — adapter-hook kwargs.** `serve()` and `async_serve()` accept `schema_converter`, `annotation_mapper`, `error_mapper` kwargs that override the factory's built-in adapters.
- **EM-1 — `McpErrorFormatter` canonical class name.** Added as the preferred PascalCase name (matches TS+Rust). The pre-existing `MCPErrorFormatter` (all-caps) is kept as a backwards-compatible alias. Both are exported from `apcore_mcp` and `apcore_mcp.adapters`.
- **EM-3 — `userFixable=true` stamp.** `ErrorMapper` now hardcodes `userFixable: true` for `DEPENDENCY_NOT_FOUND`, `DEPENDENCY_VERSION_MISMATCH`, `VERSION_CONSTRAINT_INVALID`, and the four `BINDING_*` codes (matches TS). apcore 0.19's error classes don't yet set `user_fixable=true` themselves, so the bridge stamps the hint to give MCP clients a consistent self-healing signal. 9 regression tests.
- **MID-5 — `ModuleIDNormalizer.try_denormalize`.** New bijection-guarded variant validates the dash→dot-replaced result against `MODULE_ID_PATTERN`, returning `None` for inputs that aren't valid pre-images of `normalize`. Plain `denormalize` stays lenient. 8 regression tests.
- **JWT-2 — case-insensitive `Authorization` header lookup.** `JWTAuthenticator.authenticate` now tries both `headers["authorization"]` and `headers["Authorization"]`. ASGI lower-cases header names but direct callers may pass the capitalised form; RFC 7230 §3.2 mandates case-insensitive header names. Matches TS+Rust behaviour. 1 regression test.
- **AM-L1 — F-041 annotation extras format aligned with TS+Rust.** `mcp_*` extras are now appended after the `[Annotations: ...]` block separated by a single newline (was each extra as its own `\n\n`-separated section). 1 regression test.
- TC-011 integration tests added in `tests/explorer/test_explorer.py::TestTC011Validate` pinning the `/validate` wire-up.

---

## [0.13.0] - 2026-04-06

### Added

- **Pipeline Strategy Selection** (F-036) — `serve(strategy=)` parameter and CLI `--strategy` flag with 5 presets: standard, internal, testing, performance, minimal.
- **Tool Output Redaction** (F-038) — `serve(redact_output=True)` applies `redact_sensitive()` to tool output before MCP serialization. Enabled by default.
- **Pipeline Observability** (F-037) — `serve(trace=True)` enables `call_async_with_trace()` for per-step pipeline timing in responses.
- **Tool Preflight Validation** (F-039) — `ExecutionRouter.validate_tool()` for dry-run validation via `Executor.validate()`.
- **YAML Pipeline Configuration** (F-040) — Config Bus `mcp.pipeline` section for declarative pipeline customization.
- **Annotation Metadata Passthrough** (F-041) — `ModuleAnnotations.extra` keys prefixed with `mcp_` flow to tool descriptions.
- **4 new error mappings** — `ConfigEnvMapConflictError`, `PipelineAbortError`, `StepNotFoundError`, `VersionIncompatibleError`.
- **RegistryListener wired to `serve(dynamic=True)`** — dynamic tool registration now operational.

### Changed

- **Dependency bump**: `apcore >= 0.17.1` (was `>= 0.15.1`).
- Pipeline v2 alignment: 11-step pipeline, `call_chain_guard` rename, middleware before input validation.

---

## [0.12.0] - 2026-03-31

### Added

- **Config Bus namespace registration** (F-033) — Registers `mcp` namespace with apcore Config Bus (`APCORE_MCP` env prefix). MCP configuration (transport, host, port, auth, explorer) can be managed via unified `apcore.yaml`.
- **Error Formatter Registry integration** (F-034) — `MCPErrorFormatter` registered with apcore's `ErrorFormatterRegistry`, formalizing MCP error formatting into the shared protocol.
- **Dot-namespaced event constants** (F-035) — `APCORE_EVENTS` dict with canonical event type names from apcore 0.15.0 (§9.16).
- **6 new error code mappings** — `CONFIG_NAMESPACE_DUPLICATE`, `CONFIG_NAMESPACE_RESERVED`, `CONFIG_ENV_PREFIX_CONFLICT`, `CONFIG_MOUNT_ERROR`, `CONFIG_BIND_ERROR`, `ERROR_FORMATTER_DUPLICATE`.

### Changed

- Dependency bump: requires `apcore >= 0.15.1` (was `>= 0.14.0`) for Config Bus (§9.4), Error Formatter Registry (§8.8), and dot-namespaced event types (§9.16).

---

## [0.11.0] - 2026-03-26

### Added

- **Display overlay in `build_tool()`** (§5.13) — MCP tool name, description, and guidance now sourced from `metadata["display"]["mcp"]` when present.
  - Tool name: `metadata["display"]["mcp"]["alias"]` (pre-sanitized by `DisplayResolver`, already `[a-zA-Z_][a-zA-Z0-9_-]*` and ≤ 64 chars).
  - Tool description: `metadata["display"]["mcp"]["description"]`, with `guidance` appended as `\n\nGuidance: <text>` when set.
  - Falls back to raw `module.name` / `module.description` when no display overlay is present.

### Changed

- Dependency bump: requires `apcore-toolkit >= 0.4.0` for `DisplayResolver`.

### Tests

- `TestBuildToolDisplayOverlay` (6 tests): MCP alias used as tool name, MCP description used, guidance appended, surface-specific override wins, fallback to scanner values when no overlay.

---

## [0.10.1] - 2026-03-22

### Changed
- Rebrand: aipartnerup → aiperceivable

## [0.10.0] - 2026-03-14

### Changed

- **BREAKING: `output_formatter` default changed to `None`**: `APCoreMCP` no longer defaults to `apcore_toolkit.to_markdown`. Results are now serialized as raw JSON by default. To restore Markdown formatting, pass `output_formatter=to_markdown` explicitly (requires `apcore-toolkit`).
- **Dependency bump**: Requires `apcore>=0.13.0` (was `>=0.9.0`). Picks up new annotation fields (`cacheable`, `paginated`, `cache_ttl`, `cache_key_fields`, `pagination_style`) and `ExecutionCancelledError` now extending `ModuleError`.
- **Annotation description suffix**: `AnnotationMapper.to_description_suffix()` now includes `cacheable` and `paginated` when set to non-default values.

### Removed

- **`apcore-toolkit` dependency**: Removed from `pyproject.toml` dependencies. `apcore-toolkit` is no longer required to use `apcore-mcp`. Users who want Markdown formatting can install it separately and pass `to_markdown` as the `output_formatter`.

## [0.9.0] - 2026-03-06

### Added

- **`async_serve()` context manager**: New public API for embedding the MCP server into a larger ASGI application. Returns a `Starlette` app via `async with async_serve(registry) as mcp_app:`, enabling co-hosting with A2A, Django ASGI, or other services under a single uvicorn process.
- **`TransportManager.build_streamable_http_app()`**: Low-level async context manager that builds a Starlette ASGI app with MCP transport, health, and metrics routes. Supports `extra_routes` and `middleware` injection.
- **`ExecutionCancelledError` handling**: `ErrorMapper` now maps apcore's `ExecutionCancelledError` to a safe `EXECUTION_CANCELLED` response with `retryable=True`. Internal cancellation details are never leaked.
- **New error codes**: `VERSION_INCOMPATIBLE`, `ERROR_CODE_COLLISION`, and `EXECUTION_CANCELLED` added to `ERROR_CODES` constants.
- **Deep merge for streaming**: Streaming chunk accumulation uses recursive deep merge (depth-capped at 32) instead of shallow merge, correctly handling nested response structures.

### Changed

- **Dependency bump**: Requires `apcore>=0.9.0` (was `>=0.7.0`). Picks up `PreflightResult`, execution pipeline, retry middleware, error code registry, and more.
- **Preflight validation aligned with apcore 0.9.0**: `ExecutionRouter` now passes the router-built `Context` (with identity, callbacks) to `Executor.validate()`, enabling accurate ACL and call-chain preflight checks. Error formatting handles all three `PreflightResult` error shapes: nested schema errors, flat field errors, and code-only errors.
- **Annotation description suffix**: `AnnotationMapper.to_description_suffix()` now produces safety warnings (`WARNING: DESTRUCTIVE`, `REQUIRES APPROVAL`) as a separate section above the machine-readable annotation block, improving AI agent awareness of dangerous operations.
- **Auth middleware best-effort identity on exempt paths**: `AuthMiddleware` now attempts identity extraction on exempt paths. Valid tokens populate `auth_identity_var` even when auth is not required, allowing downstream handlers to use identity when available.

## [0.8.0] - 2026-03-02

### Added

- **Approval system (F-028)**: Full runtime approval support via `ElicitationApprovalHandler` that bridges MCP elicitation to apcore's approval system. New `approval_handler` parameter on `serve()`. Supports `request_approval()` and `check_approval()` methods.
  - `ElicitationApprovalHandler`: Presents approval requests to users via MCP elicitation. Maps elicit actions (`accept`/`decline`/`cancel`) to `ApprovalResult` statuses.
  - CLI `--approval` flag with choices: `elicit`, `auto-approve`, `always-deny`, `off` (default).
- **Approval error codes**: `APPROVAL_DENIED`, `APPROVAL_TIMEOUT`, `APPROVAL_PENDING` added to `ERROR_CODES`.
- **Enhanced error responses with AI guidance**: `ErrorMapper` now extracts `retryable`, `ai_guidance`, `user_fixable`, and `suggestion` fields from apcore `ModuleError` and includes non-None values in error response dicts. `ExecutionRouter` appends AI guidance as structured JSON to error text content for AI agent consumption.
- **AI intent metadata in tool descriptions**: `MCPServerFactory.build_tool()` reads `descriptor.metadata` for AI intent keys (`x-when-to-use`, `x-when-not-to-use`, `x-common-mistakes`, `x-workflow-hints`) and appends them to tool descriptions for agent visibility.
- **Streaming annotation**: `DEFAULT_ANNOTATIONS` now includes `streaming` field. `AnnotationMapper.to_description_suffix()` includes `streaming=true` when the annotation is set.

### Changed

- **`APPROVAL_TIMEOUT` auto-retryable**: `ErrorMapper` sets `retryable=True` for `APPROVAL_TIMEOUT` errors, signaling to AI agents that the operation can be retried.
- **`APPROVAL_PENDING` includes `approval_id`**: `ErrorMapper` extracts `approval_id` from error details for `APPROVAL_PENDING` errors.
- **Error text content enriched**: Router error text now includes AI guidance fields as a structured JSON appendix when present, enabling AI agents to parse retry/fix hints.

## [0.7.0] - 2026-02-28

### Added

- **JWT Authentication (F-027)**: Optional JWT-based authentication for HTTP transports (`streamable-http`, `sse`). New `authenticator` parameter on `serve()` and `MCPServer`. Validates Bearer tokens, maps JWT claims to apcore `Identity`, and injects identity into `Context` for ACL enforcement.
  - `JWTAuthenticator`: Configurable JWT validation with `ClaimMapping` for flexible claim-to-Identity field mapping. Supports custom algorithms, audience, issuer, and required claims.
  - `AuthMiddleware`: ASGI middleware that bridges HTTP authentication to MCP handlers via `ContextVar[Identity]`. Supports `exempt_paths` (exact match) and `exempt_prefixes` (prefix match) for unauthenticated endpoints.
  - `Authenticator` Protocol: `@runtime_checkable` protocol for custom authentication backends.
- **Permissive auth mode**: `require_auth=False` parameter on `serve()` and `MCPServer` allows unauthenticated requests to proceed without identity instead of returning 401.
- **`exempt_paths` parameter**: `serve()` and `MCPServer` accept `exempt_paths` for exact-path authentication bypass (e.g. `{"/health", "/metrics"}`).
- **CLI JWT flags**: `--jwt-secret`, `--jwt-algorithm`, `--jwt-audience`, `--jwt-issuer` arguments for enabling JWT authentication from the command line.
- **CLI `--jwt-key-file`**: Read JWT verification key from a PEM file (e.g. RS256 public key). Takes priority over `--jwt-secret` and `APCORE_JWT_SECRET` env var.
- **CLI `--jwt-require-auth` / `--no-jwt-require-auth`**: Toggle permissive auth mode from the command line.
- **CLI `--exempt-paths`**: Comma-separated list of paths exempt from authentication.
- **`APCORE_JWT_SECRET` env var fallback**: CLI resolves JWT key in priority order: `--jwt-key-file` > `--jwt-secret` > `APCORE_JWT_SECRET` environment variable.
- **Explorer Authorization UI**: Swagger-UI-style Authorization input field in the Tool Explorer. Paste a Bearer token to authenticate tool execution requests. Generated cURL commands automatically include the Authorization header.
- **Explorer auth enforcement**: When `authenticator` is set, tool execution via the Explorer returns 401 Unauthorized without a valid Bearer token. The Explorer UI displays a clear error message prompting the user to enter a token.
- **Auth failure audit logging**: `AuthMiddleware` emits a `WARNING` log with the request path on authentication failure.
- **`extract_headers()` utility**: Public helper to extract ASGI scope headers as a lowercase-key dict. Exported from `apcore_mcp.auth`.
- **JWT authentication example**: `examples/run.py` supports `APCORE_JWT_SECRET` environment variable to demonstrate JWT authentication with a sample token.
- **PyJWT dependency**: Added `PyJWT>=2.0` to project dependencies.

### Changed

- **Explorer UI layout**: Redesigned from a bottom-panel layout to a Swagger-UI-style inline accordion. Each tool expands its detail, schema, and "Try it" section directly below the tool name. Only one tool can be expanded at a time. Detail is loaded once on first expand and cached.
- **AuthMiddleware `exempt_prefixes`**: Added `exempt_prefixes` parameter for prefix-based path exemption. Explorer paths are automatically exempt when both `explorer` and `authenticator` are enabled, so the Explorer UI always loads.
- **`extract_headers` refactored**: Moved from private `AuthMiddleware._extract_headers()` to module-level `extract_headers()` function for reuse in Explorer routes.

## [0.6.0] - 2026-02-25

### Added

- **Example modules**: `examples/` with 5 runnable demo modules — 3 class-based (`text_echo`, `math_calc`, `greeting`) and 2 binding.yaml (`convert_temperature`, `word_count`) — for quick Explorer UI demo out of the box.

### Changed

- **BREAKING: `ExecutionRouter.handle_call()` return type**: Changed from `(content, is_error)` to `(content, is_error, trace_id)`. Callers that unpack the 2-tuple must update to 3-tuple unpacking.
- **BREAKING: Explorer `/call` response format**: Changed from `{"result": ...}` / `{"error": ...}` to MCP-compliant `CallToolResult` format: `{"content": [...], "isError": bool, "_meta": {"_trace_id": ...}}`.

### Fixed

- **MCP protocol compliance**: Router no longer injects `_trace_id` as a content block in tool results. `trace_id` is now returned as a separate tuple element and surfaced in Explorer responses via `_meta`. Factory handler raises exceptions for errors so the MCP SDK correctly sets `isError=True`.
- **Explorer UI default values**: `defaultFromSchema()` now correctly skips `null` defaults and falls through to type-based placeholders, fixing blank form fields for binding.yaml modules.

## [0.5.1] - 2026-02-25

### Changed

- **Rename Inspector to Explorer**: Renamed the MCP Tool Inspector module to MCP Tool Explorer across the entire codebase — module path (`apcore_mcp.inspector` → `apcore_mcp.explorer`), CLI flags, Python API parameters, HTML UI, tests, README, and CHANGELOG. No functional changes; all endpoints and behavior remain identical.

### Fixed

- **Version test**: Fixed `test_run_uses_package_version_when_version_is_none` to patch `importlib.metadata.version` so the test is not sensitive to the installed package version.

## [0.5.0] - 2026-02-24

### Added

- **MCP Tool Explorer (F-026)**: Optional browser-based UI for inspecting and testing MCP tools, mounted at `/explorer` when `explorer=True`. Includes 4 HTTP endpoints (`GET /explorer/`, `GET /explorer/tools`, `GET /explorer/tools/<name>`, `POST /explorer/tools/<name>/call`), a self-contained HTML/CSS/JS page with no external dependencies, configurable `explorer_prefix`, and `allow_execute` guard (default `False`). HTTP transports only; silently ignored for stdio.
- **CLI Explorer flags**: `--explorer`, `--explorer-prefix`, and `--allow-execute` arguments.
- **Explorer UI: proactive execution status detection**: The Explorer probes execution status on page load via a lightweight POST to `/tools/__probe__/call`, so the "Tool execution is disabled" message appears immediately instead of requiring a user click first.
- **Explorer UI: URL-safe tool name encoding**: Tool names in fetch URLs are wrapped with `encodeURIComponent()` to prevent malformed URLs when tool names contain special characters.
- **Explorer UI: error handling on tool detail fetch**: `.catch()` handler on the `loadDetail` fetch chain displays network errors in the detail panel instead of silently swallowing them.

## [0.4.0] - 2026-02-23

### Added

- **Resource handlers**: `MCPServerFactory.register_resource_handlers()` for serving documentation resources via MCP.
- **CI workflow**: GitHub Actions CI pipeline and `CODEOWNERS` file.
- **Missing error codes**: Added `MODULE_EXECUTE_ERROR` and `GENERAL_INVALID_INPUT` to error codes constants.
- **serve() parameter tests**: Comprehensive test suite for `serve()` parameter validation.
- **Metrics endpoint tests**: Dedicated test suite for Prometheus `/metrics` endpoint.

### Changed

- **Version management**: Consolidated version into `__init__.__version__`, removed `_version.py`.

### Fixed

- **Cache configuration**: Removed unnecessary cache configuration from Python setup step.
- **Code formatting**: Improved linting checks in CI workflow, factory, router, and test files.

### Refactored

- **Import cleanup**: Removed unused imports across multiple test files; reordered imports in MCPServer for consistency.
- **Code structure**: General readability and maintainability improvements.

## [0.3.0] - 2026-02-22

### Added

- **metrics_collector parameter**: `serve(metrics_collector=...)` accepts a `MetricsCollector` instance to enable Prometheus metrics export.
- **`/metrics` Prometheus endpoint**: HTTP-based transports (`streamable-http`, `sse`) now serve a `/metrics` route returning Prometheus text format when a `metrics_collector` is provided. Returns 404 when no collector is configured.
- **trace_id passback**: Every successful response now includes a second content item with `_trace_id` metadata for request tracing. *(Removed in 0.5.1: trace_id moved out of content blocks into separate return value for MCP protocol compliance.)*
- **validate_inputs**: `serve(validate_inputs=True)` enables pre-execution input validation via `Executor.validate()`. Invalid inputs are rejected before module execution.
- **Always-on Context**: `Context` is now always created for every tool call, enabling trace_id generation even without MCP callbacks.

### Changed

- **SchemaExporter integration**: `MCPServerFactory.build_tool()` now uses `apcore.schema.exporter.SchemaExporter.export_mcp()` for canonical MCP annotation mapping instead of duplicating logic.
- **to_strict_schema() delegation**: `OpenAIConverter._apply_strict_mode()` now delegates to `apcore.schema.strict.to_strict_schema()` instead of custom recursive implementation. This adds x-* extension stripping, oneOf/anyOf/allOf recursion, $defs recursion, and alphabetically sorted required lists.
- **Dependency bump**: Requires `apcore>=0.5.0` (was `>=0.2.0`).

### Removed

- **Custom strict mode**: Removed `OpenAIConverter._apply_strict_recursive()` in favor of `to_strict_schema()`.

## [0.2.0] - 2026-02-20

### Added

- **MCPServer**: Non-blocking MCP server wrapper for framework integrations with configurable transport and async event loop management.
- **serve() hooks**: `on_startup` and `on_shutdown` callbacks for lifecycle management.
- **Health endpoint**: Built-in health check support for HTTP-based transports.
- **Constants module**: Centralized `REGISTRY_EVENTS`, `ErrorCodes`, and `MODULE_ID_PATTERN` for consistent values across adapters and listeners.
- **Module ID validation**: Enhanced `id_normalizer.normalize()` with format validation using `MODULE_ID_PATTERN`.
- **Exported building blocks**: Public API exports for `MCPServerFactory`, `ExecutionRouter`, `RegistryListener`, and `TransportManager`.

### Fixed

- **MCP Tool metadata**: Fixed use of `_meta` instead of `meta` in MCP Tool constructor for proper internal metadata handling.

### Refactored

- **Circular import resolution**: Moved utility functions (`resolve_registry`, `resolve_executor`) to dedicated `_utils.py` module to prevent circular dependencies between `__init__.py` and `server/server.py`.

## [0.1.0] - 2026-02-15

### Added

- **Public API**: `serve()` to launch an MCP Server from any apcore Registry or Executor.
- **Public API**: `to_openai_tools()` to export apcore modules as OpenAI-compatible tool definitions.
- **CLI**: `apcore-mcp` command with `--extensions-dir`, `--transport`, `--host`, `--port`, `--name`, `--version`, and `--log-level` options.
- **Three transports**: stdio (default), Streamable HTTP, and SSE.
- **SchemaConverter**: JSON Schema conversion with `$ref`/`$defs` inlining for MCP and OpenAI compatibility.
- **AnnotationMapper**: Maps apcore annotations (readonly, destructive, idempotent, open_world) to MCP `ToolAnnotations`.
- **ErrorMapper**: Sanitizes apcore errors for safe client exposure — no stack traces, no internal details leaked.
- **ModuleIDNormalizer**: Bijective dot-to-dash conversion for OpenAI function name compatibility.
- **OpenAIConverter**: Full registry-to-OpenAI conversion with `strict` mode (Structured Outputs) and `embed_annotations` support.
- **MCPServerFactory**: Creates MCP Server instances, builds Tool objects, and registers `list_tools`/`call_tool` handlers.
- **ExecutionRouter**: Routes MCP tool calls to apcore Executor with error sanitization.
- **TransportManager**: Manages stdio, Streamable HTTP, and SSE transport lifecycle.
- **RegistryListener**: Thread-safe dynamic tool registration via `registry.on("register"/"unregister")` callbacks.
- **Structured logging**: All components use `logging.getLogger(__name__)` under the `apcore_mcp` namespace.
- **Dual input**: Both `serve()` and `to_openai_tools()` accept either a Registry or Executor instance.
- **Filtering**: `tags` and `prefix` parameters for selective module exposure.
- **260 tests**: Unit, integration, E2E, performance, and security test suites.

[0.10.0]: https://github.com/aiperceivable/apcore-mcp-python/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/aiperceivable/apcore-mcp-python/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/aiperceivable/apcore-mcp-python/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/aiperceivable/apcore-mcp-python/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/aiperceivable/apcore-mcp-python/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/aiperceivable/apcore-mcp-python/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/aiperceivable/apcore-mcp-python/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/aiperceivable/apcore-mcp-python/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/aiperceivable/apcore-mcp-python/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/aiperceivable/apcore-mcp-python/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aiperceivable/apcore-mcp-python/releases/tag/v0.1.0
