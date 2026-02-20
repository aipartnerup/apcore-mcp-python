# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.0]: https://github.com/aipartnerup/apcore-mcp-python/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/aipartnerup/apcore-mcp-python/releases/tag/v0.1.0
