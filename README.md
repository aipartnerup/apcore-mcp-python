# apcore-mcp

Automatic MCP Server & OpenAI Tools Bridge for apcore.

**apcore-mcp** turns any [apcore](https://github.com/aipartnerup/apcore)-based project into an MCP Server and OpenAI tool provider — with **zero code changes** to your existing project.

```
┌──────────────────┐
│  django-apcore   │  ← your existing apcore project (unchanged)
│  flask-apcore    │
│  ...             │
└────────┬─────────┘
         │  extensions directory
         ▼
┌──────────────────┐
│    apcore-mcp    │  ← just install & point to extensions dir
└───┬──────────┬───┘
    │          │
    ▼          ▼
  MCP       OpenAI
 Server      Tools
```

## Design Philosophy

- **Zero intrusion** — your apcore project needs no code changes, no imports, no dependencies on apcore-mcp
- **Zero configuration** — point to an extensions directory, everything is auto-discovered
- **Pure adapter** — apcore-mcp reads from the apcore Registry; it never modifies your modules
- **Works with any `xxx-apcore` project** — if it uses the apcore Module Registry, apcore-mcp can serve it

## Installation

Install apcore-mcp alongside your existing apcore project:

```bash
pip install apcore-mcp
```

That's it. Your existing project requires no changes.

Requires Python 3.10+ and `apcore >= 0.5.0`.

## Quick Start

### Zero-code approach (CLI)

If you already have an apcore-based project with an extensions directory, just run:

```bash
apcore-mcp --extensions-dir /path/to/your/extensions
```

All modules are auto-discovered and exposed as MCP tools. No code needed.

### Programmatic approach (Python API)

For tighter integration or when you need filtering/OpenAI output:

```python
from apcore import Registry
from apcore_mcp import serve, to_openai_tools

registry = Registry(extensions_dir="./extensions")
registry.discover()

# Launch as MCP Server
serve(registry)

# Or export as OpenAI tools
tools = to_openai_tools(registry)
```

## Integration with Existing Projects

### Typical apcore project structure

```
your-project/
├── extensions/          ← modules live here
│   ├── image_resize/
│   ├── text_translate/
│   └── ...
├── your_app.py          ← your existing code (untouched)
└── ...
```

### Adding MCP support

No changes to your project. Just run apcore-mcp alongside it:

```bash
# Install (one time)
pip install apcore-mcp

# Run
apcore-mcp --extensions-dir ./extensions
```

Your existing application continues to work exactly as before. apcore-mcp operates as a separate process that reads from the same extensions directory.

### Adding OpenAI tools support

For OpenAI integration, a thin script is needed — but still **no changes to your existing modules**:

```python
from apcore import Registry
from apcore_mcp import to_openai_tools

registry = Registry(extensions_dir="./extensions")
registry.discover()

tools = to_openai_tools(registry)
# Use with openai.chat.completions.create(tools=tools)
```

## MCP Client Configuration

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "apcore": {
      "command": "apcore-mcp",
      "args": ["--extensions-dir", "/path/to/your/extensions"]
    }
  }
}
```

### Claude Code

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "apcore": {
      "command": "apcore-mcp",
      "args": ["--extensions-dir", "./extensions"]
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "apcore": {
      "command": "apcore-mcp",
      "args": ["--extensions-dir", "./extensions"]
    }
  }
}
```

### Remote HTTP access

```bash
apcore-mcp --extensions-dir ./extensions \
    --transport streamable-http \
    --host 0.0.0.0 \
    --port 9000
```

Connect any MCP client to `http://your-host:9000/mcp`.

## CLI Reference

```
apcore-mcp --extensions-dir PATH [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--extensions-dir` | *(required)* | Path to apcore extensions directory |
| `--transport` | `stdio` | Transport: `stdio`, `streamable-http`, or `sse` |
| `--host` | `127.0.0.1` | Host for HTTP-based transports |
| `--port` | `8000` | Port for HTTP-based transports (1-65535) |
| `--name` | `apcore-mcp` | MCP server name (max 255 chars) |
| `--version` | package version | MCP server version string |
| `--log-level` | `INFO` | Logging: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--explorer` | off | Enable the browser-based Tool Explorer UI (HTTP only) |
| `--explorer-prefix` | `/explorer` | URL prefix for the explorer UI |
| `--allow-execute` | off | Allow tool execution from the explorer UI |

Exit codes: `0` normal, `1` invalid arguments, `2` startup failure.

## Python API Reference

### `serve()`

```python
from apcore_mcp import serve

serve(
    registry_or_executor,        # Registry or Executor
    transport="stdio",           # "stdio" | "streamable-http" | "sse"
    host="127.0.0.1",           # host for HTTP transports
    port=8000,                   # port for HTTP transports
    name="apcore-mcp",          # server name
    version=None,                # defaults to package version
    on_startup=None,             # callback before transport starts
    on_shutdown=None,            # callback after transport completes
    tags=None,                   # filter modules by tags
    prefix=None,                 # filter modules by ID prefix
    log_level=None,              # logging level ("DEBUG", "INFO", etc.)
    validate_inputs=False,       # validate inputs against schemas
    metrics_collector=None,      # MetricsCollector for /metrics endpoint
    explorer=False,              # enable browser-based Tool Explorer UI
    explorer_prefix="/explorer", # URL prefix for the explorer
    allow_execute=False,         # allow tool execution from the explorer
)
```

Accepts either a `Registry` or `Executor`. When a `Registry` is passed, an `Executor` is created automatically.

### Tool Explorer

When `explorer=True` is passed to `serve()`, a browser-based Tool Explorer UI is mounted on HTTP transports. It provides an interactive page for browsing tool schemas and testing tool execution.

```python
serve(registry, transport="streamable-http", explorer=True, allow_execute=True)
# Open http://127.0.0.1:8000/explorer/ in a browser
```

**Endpoints:**

| Endpoint | Description |
|----------|-------------|
| `GET /explorer/` | Interactive HTML page (self-contained, no external dependencies) |
| `GET /explorer/tools` | JSON array of all tools with name, description, annotations |
| `GET /explorer/tools/<name>` | Full tool detail with inputSchema |
| `POST /explorer/tools/<name>/call` | Execute a tool (requires `allow_execute=True`) |

- **HTTP transports only** (`streamable-http`, `sse`). Silently ignored for `stdio`.
- **Execution disabled by default** — set `allow_execute=True` to enable Try-it.
- **Custom prefix** — use `explorer_prefix="/browse"` to mount at a different path.

### `/metrics` Prometheus Endpoint

When `metrics_collector` is provided to `serve()`, a `/metrics` HTTP endpoint is exposed that returns metrics in Prometheus text exposition format.

- **Available on HTTP-based transports only** (`streamable-http`, `sse`). Not available with `stdio` transport.
- **Returns Prometheus text format** with Content-Type `text/plain; version=0.0.4; charset=utf-8`.
- **Returns 404** when no `metrics_collector` is configured.

```python
from apcore.observability import MetricsCollector
from apcore_mcp import serve

collector = MetricsCollector()
serve(registry, transport="streamable-http", metrics_collector=collector)
# GET http://127.0.0.1:8000/metrics -> Prometheus text format
```

### `to_openai_tools()`

```python
from apcore_mcp import to_openai_tools

tools = to_openai_tools(
    registry_or_executor,       # Registry or Executor
    embed_annotations=False,    # append annotation hints to descriptions
    strict=False,               # OpenAI Structured Outputs strict mode
    tags=None,                  # filter by tags, e.g. ["image"]
    prefix=None,                # filter by module ID prefix, e.g. "image"
)
```

Returns a list of dicts directly usable with the OpenAI API:

```python
import openai

client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Resize the image to 512x512"}],
    tools=tools,
)
```

**Strict mode** (`strict=True`): sets `additionalProperties: false`, makes all properties required (optional ones become nullable), removes defaults.

**Annotation embedding** (`embed_annotations=True`): appends `[Annotations: read_only, idempotent]` to descriptions.

**Filtering**: `tags=["image"]` or `prefix="text"` to expose a subset of modules.

### Using with an Executor

If you need custom middleware, ACL, or execution configuration:

```python
from apcore import Registry, Executor

registry = Registry(extensions_dir="./extensions")
registry.discover()
executor = Executor(registry)

serve(executor)
tools = to_openai_tools(executor)
```

## Features

- **Auto-discovery** — all modules in the extensions directory are found and exposed automatically
- **Three transports** — stdio (default, for desktop clients), Streamable HTTP, and SSE
- **Annotation mapping** — apcore annotations (readonly, destructive, idempotent) map to MCP ToolAnnotations
- **Schema conversion** — JSON Schema `$ref`/`$defs` inlining, strict mode for OpenAI Structured Outputs
- **Error sanitization** — ACL errors and internal errors are sanitized; stack traces are never leaked
- **Dynamic registration** — modules registered/unregistered at runtime are reflected immediately
- **Dual output** — same registry powers both MCP Server and OpenAI tool definitions
- **Tool Explorer** — browser-based UI for browsing schemas and testing tools interactively

## How It Works

### Mapping: apcore to MCP

| apcore | MCP |
|--------|-----|
| `module_id` | Tool name |
| `description` | Tool description |
| `input_schema` | `inputSchema` |
| `annotations.readonly` | `ToolAnnotations.readOnlyHint` |
| `annotations.destructive` | `ToolAnnotations.destructiveHint` |
| `annotations.idempotent` | `ToolAnnotations.idempotentHint` |
| `annotations.open_world` | `ToolAnnotations.openWorldHint` |

### Mapping: apcore to OpenAI Tools

| apcore | OpenAI |
|--------|--------|
| `module_id` (`image.resize`) | `name` (`image-resize`) |
| `description` | `description` |
| `input_schema` | `parameters` |

Module IDs with dots are normalized to dashes for OpenAI compatibility (bijective mapping).

### Architecture

```
Your apcore project (unchanged)
    │
    │  extensions directory
    ▼
apcore-mcp (separate process / library call)
    │
    ├── MCP Server path
    │     SchemaConverter + AnnotationMapper
    │       → MCPServerFactory → ExecutionRouter → TransportManager
    │
    └── OpenAI Tools path
          SchemaConverter + AnnotationMapper + IDNormalizer
            → OpenAIConverter → list[dict]
```

## Development

```bash
git clone https://github.com/aipartnerup/apcore-mcp-python.git
cd apcore-mcp
pip install -e ".[dev]"
pytest                           # 260 tests
pytest --cov                     # with coverage report
```

### Project Structure

```
src/apcore_mcp/
├── __init__.py              # Public API: serve(), to_openai_tools()
├── __main__.py              # CLI entry point
├── adapters/
│   ├── schema.py            # JSON Schema conversion ($ref inlining)
│   ├── annotations.py       # Annotation mapping (apcore → MCP/OpenAI)
│   ├── errors.py            # Error sanitization
│   └── id_normalizer.py     # Module ID normalization (dot ↔ dash)
├── converters/
│   └── openai.py            # OpenAI tool definition converter
├── explorer/
│   ├── __init__.py          # create_explorer_mount() entry point
│   ├── routes.py            # Starlette route handlers
│   └── html.py              # Self-contained HTML/CSS/JS page
└── server/
    ├── factory.py           # MCP Server creation and tool building
    ├── router.py            # Tool call → Executor routing
    ├── transport.py         # Transport management (stdio/HTTP/SSE)
    └── listener.py          # Dynamic module registration listener
```

## License

Apache-2.0
