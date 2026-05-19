"""APCoreMCP: Unified entry point for apcore-mcp.

[D9-001] APCoreMCP is the canonical implementation of serve/async_serve/
to_openai_tools. The module-level functions in :mod:`apcore_mcp` are thin
delegators that forward kwargs to this class. Prior to 0.16.0 the pipeline
was duplicated between this module and ``__init__.py``; the duplication was
eliminated to fix latent bugs (extra_routes typing, metrics_collector
narrowing) and to ensure feature parity in a single place.

Symbols such as ``MCPServerFactory``, ``ExecutionRouter`` and
``TransportManager`` are looked up via the :mod:`apcore_mcp` package
namespace rather than imported directly, so that tests patching
``apcore_mcp.MCPServerFactory`` (and siblings) continue to intercept the
construction sites used by APCoreMCP.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.routing import Mount, Route

from apcore_mcp._utils import resolve_executor, resolve_registry
from apcore_mcp.auth.protocol import Authenticator
from apcore_mcp.server.transport import MetricsExporter

if TYPE_CHECKING:
    from starlette.applications import Starlette

logger = logging.getLogger(__name__)


def _load_config_bus_overrides(
    *,
    registry: object,
    strategy: str | None,
    load_pipeline: bool,
) -> dict[str, object]:
    """Load Config Bus overrides for strategy / middleware / ACL / scalar keys.

    [D9-002] Mirrors the TS helper ``loadConfigBusOverrides`` (index.ts:256).
    Returns a mapping with the keys ``pipeline_strategy``, ``config_middleware``,
    ``config_acl``, and ``scalars``.
    """
    pipeline_strategy: object | None = None
    config_middleware: list[object] = []
    config_acl: object | None = None
    scalars: dict[str, object] = {}
    _config_bus_loaded = False
    try:
        from apcore import Config, build_strategy_from_config

        _config_bus_loaded = True
    except ImportError as exc:
        logger.debug("Config Bus not available, skipping: %s", exc)
        return {
            "pipeline_strategy": None,
            "config_middleware": config_middleware,
            "config_acl": None,
            "scalars": scalars,
        }
    config = Config.load() if Config is not None else None  # type: ignore[possibly-undefined]
    if not config:
        return {
            "pipeline_strategy": None,
            "config_middleware": config_middleware,
            "config_acl": None,
            "scalars": scalars,
        }

    if load_pipeline:
        pipeline_config = config.get("mcp.pipeline")
        if pipeline_config and isinstance(pipeline_config, dict) and build_strategy_from_config is not None:
            pipeline_strategy = build_strategy_from_config(pipeline_config, registry=registry)
            if strategy:
                logger.warning("YAML pipeline config overrides strategy parameter")

    mw_config = config.get("mcp.middleware")
    if mw_config and isinstance(mw_config, list):
        from apcore_mcp.middleware_builder import build_middleware_from_config

        config_middleware = build_middleware_from_config(mw_config)

    acl_config = config.get("mcp.acl")
    if acl_config:
        from apcore_mcp.acl_builder import build_acl_from_config

        config_acl = build_acl_from_config(acl_config)

    cfg_transport = config.get("mcp.transport")
    if cfg_transport and isinstance(cfg_transport, str):
        scalars["transport"] = cfg_transport
    cfg_host = config.get("mcp.host")
    if cfg_host and isinstance(cfg_host, str):
        scalars["host"] = cfg_host
    cfg_port = config.get("mcp.port")
    if cfg_port is not None:
        try:
            scalars["port"] = int(cfg_port)
        except (ValueError, TypeError):
            logger.warning(
                "mcp.port Config Bus value %r is not an integer; ignoring",
                cfg_port,
            )
    cfg_name = config.get("mcp.name")
    if cfg_name and isinstance(cfg_name, str):
        scalars["name"] = cfg_name
    cfg_log_level = config.get("mcp.log_level")
    if cfg_log_level and isinstance(cfg_log_level, str):
        scalars["log_level"] = cfg_log_level
    cfg_validate = config.get("mcp.validate_inputs")
    if cfg_validate is not None and isinstance(cfg_validate, bool):
        scalars["validate_inputs"] = cfg_validate
    cfg_explorer = config.get("mcp.explorer")
    if cfg_explorer is not None and isinstance(cfg_explorer, bool):
        scalars["explorer"] = cfg_explorer
    cfg_explorer_prefix = config.get("mcp.explorer_prefix")
    if cfg_explorer_prefix and isinstance(cfg_explorer_prefix, str):
        scalars["explorer_prefix"] = cfg_explorer_prefix
    cfg_require_auth = config.get("mcp.require_auth")
    if cfg_require_auth is not None and isinstance(cfg_require_auth, bool):
        scalars["require_auth"] = cfg_require_auth

    return {
        "pipeline_strategy": pipeline_strategy,
        "config_middleware": config_middleware,
        "config_acl": config_acl,
        "scalars": scalars,
    }


def _validate_common_kwargs(
    *,
    name: str,
    tags: list[str] | None,
    prefix: str | None,
    log_level: str | None,
) -> None:
    """Shared validation used by both APCoreMCP.__init__ and the legacy serve() path."""
    if not name:
        raise ValueError("name must not be empty")
    if len(name) > 255:
        raise ValueError(f"name exceeds maximum length of 255: {len(name)}")
    if tags is not None:
        for tag in tags:
            if not tag:
                raise ValueError("Tag values must not be empty")
    if prefix is not None and not prefix:
        raise ValueError("prefix must not be empty")
    if log_level is not None:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if log_level.upper() not in valid_levels:
            raise ValueError(f"Unknown log level: {log_level!r}. Valid: {sorted(valid_levels)}")


class APCoreMCP:
    """Unified entry point for apcore-mcp.

    Wraps Registry discovery, MCP server creation, and OpenAI tool export
    into a single object with a simple API.

    Examples::

        # Minimal — just point to extensions
        mcp = APCoreMCP("./extensions")
        mcp.serve()

        # With options
        mcp = APCoreMCP("./extensions", name="my-server", tags=["public"])
        mcp.serve(transport="streamable-http", port=9000, explorer=True)

        # Export OpenAI tools
        tools = mcp.to_openai_tools()

        # Embed into ASGI app
        async with mcp.async_serve() as app:
            ...

        # Use existing Registry or Executor
        mcp = APCoreMCP(registry)
        mcp = APCoreMCP(executor)
    """

    def __init__(
        self,
        extensions_dir_or_backend: str | Path | object,
        *,
        name: str = "apcore-mcp",
        version: str | None = None,
        tags: list[str] | None = None,
        prefix: str | None = None,
        log_level: str | None = None,
        validate_inputs: bool = False,
        metrics_collector: MetricsExporter | bool | None = None,
        authenticator: Authenticator | None = None,
        require_auth: bool = True,
        exempt_paths: set[str] | None = None,
        approval_handler: object | None = None,
        output_formatter: Callable[[dict], str] | None = None,
        output_format: str | None = None,
        strategy: str | None = None,
        redact_output: bool = True,
        trace: bool = False,
        dynamic: bool = False,
        middleware: list[object] | None = None,
        acl: object | None = None,
        observability: bool = False,
        async_tasks: bool = True,
        async_max_concurrent: int = 10,
        async_max_tasks: int = 1000,
        _load_pipeline_from_config: bool = True,
    ) -> None:
        """Create an APCoreMCP instance.

        Args:
            extensions_dir_or_backend: Path to an apcore extensions directory
                (str or Path), or an existing Registry or Executor instance.
            name: MCP server name (max 255 chars).
            version: MCP server version. Defaults to apcore-mcp package version.
            tags: Filter modules by tags. Only modules with ALL specified tags
                are exposed.
            prefix: Filter modules by ID prefix.
            log_level: Log level for the apcore_mcp logger (e.g. "DEBUG", "INFO").
            validate_inputs: Validate tool inputs against schemas before execution.
            metrics_collector: Pre-built ``MetricsExporter`` (back-compat) OR
                the sentinel ``True`` / ``observability=True`` to auto-provision
                apcore's default ``MetricsCollector`` + middleware.
            authenticator: Optional Authenticator for JWT/token-based auth (HTTP only).
            require_auth: If True, unauthenticated requests receive 401.
            exempt_paths: Exact paths that bypass authentication.
            approval_handler: Optional approval handler for runtime approval support.
            output_formatter: Optional callable that formats dict results into
                text for LLM consumption. Defaults to ``None`` (raw JSON).
            output_format: Optional built-in output format name ("json", "csv",
                "jsonl"). When set, automatically uses the corresponding
                formatter from ``apcore-toolkit``.
            strategy: Pipeline execution strategy ("standard", "internal",
                "testing", "performance", "minimal"). Ignored when an Executor
                is provided directly.
            redact_output: Redact sensitive fields from tool outputs using
                ``apcore.redact_sensitive()``. Defaults to True.
            trace: Enable pipeline trace capture via ``call_async_with_trace()``.
            dynamic: Enable dynamic tool registration via RegistryListener.
            middleware: Optional list of apcore ``Middleware`` instances appended
                to any middleware declared under Config Bus ``mcp.middleware``.
            acl: Optional apcore ``ACL`` instance. Caller-supplied ACL takes
                precedence over Config Bus ``mcp.acl``.
            observability: When True, auto-install ``MetricsMiddleware`` +
                ``UsageMiddleware`` using freshly provisioned collectors.
            async_tasks: Enable the AsyncTaskBridge meta tools.
            async_max_concurrent: Max concurrent async tasks.
            async_max_tasks: Max total async tasks tracked.
            _load_pipeline_from_config: Internal flag — when False, Config Bus
                ``mcp.pipeline`` is ignored (used by ``async_serve``-style entry
                points where pipeline construction is the caller's job).
        """
        _validate_common_kwargs(name=name, tags=tags, prefix=prefix, log_level=log_level)
        if log_level is not None:
            logging.getLogger("apcore_mcp").setLevel(getattr(logging, log_level.upper()))

        # Resolve backend: str/Path → Registry with discover(), otherwise pass through
        if isinstance(extensions_dir_or_backend, str | Path):
            from apcore import Registry

            backend: object = Registry(extensions_dir=str(extensions_dir_or_backend))
            backend.discover()  # type: ignore[union-attr]
        else:
            backend = extensions_dir_or_backend

        self._registry = resolve_registry(backend)

        # Config Bus overrides — single canonical entry point.
        _cfg = _load_config_bus_overrides(
            registry=self._registry,
            strategy=strategy,
            load_pipeline=_load_pipeline_from_config,
        )
        pipeline_strategy: object | None = _cfg["pipeline_strategy"]
        config_middleware: list[object] = list(_cfg["config_middleware"])  # type: ignore[arg-type]
        config_acl: object | None = _cfg["config_acl"]
        scalars: dict[str, object] = _cfg["scalars"]  # type: ignore[assignment]

        # Config Bus values fall between function-signature defaults and the
        # caller's explicit kwargs; explicit kwargs always win at runtime.
        if "name" in scalars:
            name = scalars["name"]  # type: ignore[assignment]
        if "log_level" in scalars:
            log_level = scalars["log_level"]  # type: ignore[assignment]
        if "validate_inputs" in scalars:
            validate_inputs = scalars["validate_inputs"]  # type: ignore[assignment]
        if "require_auth" in scalars:
            require_auth = scalars["require_auth"]  # type: ignore[assignment]

        combined_middleware: list[object] = list(config_middleware)
        if middleware:
            combined_middleware.extend(middleware)

        effective_acl = acl if acl is not None else config_acl
        if acl is not None and config_acl is not None:
            logger.info("Caller-supplied acl argument overrides Config Bus `mcp.acl`")

        if strategy is not None and hasattr(backend, "call_async"):
            logger.warning("strategy parameter ignored when Executor is provided")

        self._executor = resolve_executor(
            backend,
            approval_handler=approval_handler,
            strategy=pipeline_strategy or strategy,
            middleware=combined_middleware,
            acl=effective_acl,
        )

        # Observability auto-wiring. ``metrics_collector=True`` or
        # ``observability=True`` provisions apcore's default MetricsCollector +
        # MetricsMiddleware (and UsageCollector + UsageMiddleware when
        # ``observability`` is on). An existing MetricsExporter object is left
        # untouched.
        self._usage_collector: Any = None
        resolved_metrics: MetricsExporter | None
        if observability or metrics_collector is True:
            from apcore.observability import (
                MetricsCollector,
                MetricsMiddleware,
                UsageCollector,
                UsageMiddleware,
            )

            mc: MetricsExporter
            if metrics_collector is True or metrics_collector is None or metrics_collector is False:
                mc = MetricsCollector()
            else:
                # Narrow: ``metrics_collector`` is a MetricsExporter instance.
                mc = metrics_collector
            resolved_metrics = mc
            if hasattr(self._executor, "use"):
                # ``MetricsMiddleware`` accepts the concrete ``MetricsCollector``;
                # we typed the kwarg as the broader ``MetricsExporter`` protocol
                # for back-compat with user-supplied exporters.
                self._executor.use(MetricsMiddleware(mc))  # type: ignore[arg-type]
                if observability:
                    uc = UsageCollector()
                    self._executor.use(UsageMiddleware(uc))
                    self._usage_collector = uc
        elif metrics_collector is True or metrics_collector is False:
            # ``True`` is handled above (observability branch); ``False`` is a
            # legacy way of saying "no metrics". Both collapse to None.
            resolved_metrics = None
        else:
            # ``metrics_collector`` is either a MetricsExporter or None — both
            # are valid for ``resolved_metrics: MetricsExporter | None``.
            resolved_metrics = metrics_collector

        # Store configuration for serve()/async_serve()/to_openai_tools()
        self._name = name
        self._version = version
        self._tags = tags
        self._prefix = prefix
        self._validate_inputs = validate_inputs
        self._metrics_collector = resolved_metrics
        self._authenticator = authenticator
        self._require_auth = require_auth
        self._exempt_paths = exempt_paths
        self._redact_output = redact_output
        self._trace = trace
        self._dynamic = dynamic
        self._async_tasks = async_tasks
        self._async_max_concurrent = async_max_concurrent
        self._async_max_tasks = async_max_tasks
        self._async_bridge: Any = None
        self._output_formatter = output_formatter
        self._output_format = output_format

    # ------------------------------------------------------------------ properties
    @property
    def registry(self) -> Any:
        """The underlying apcore Registry."""
        return self._registry

    @property
    def executor(self) -> Any:
        """The underlying apcore Executor."""
        return self._executor

    @property
    def tools(self) -> list[str]:
        """List all discovered module IDs that will be exposed as tools."""
        return list(self._registry.list(tags=self._tags, prefix=self._prefix))

    # ---------------------------------------------------------- internal helpers
    def _resolve_version(self) -> str:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as _pkg_version

        if self._version:
            return self._version
        try:
            return _pkg_version("apcore-mcp")
        except PackageNotFoundError:
            return "unknown"

    def _build_output_schema_map(self) -> dict[str, dict]:
        """Build per-tool output schema map for redaction."""
        if not self._redact_output:
            return {}
        output_schema_map: dict[str, dict] = {}
        for mid in self._registry.list(tags=self._tags, prefix=self._prefix):
            desc = self._registry.get_definition(mid)
            if desc is not None:
                schema = getattr(desc, "output_schema", None)
                if schema:
                    output_schema_map[mid] = schema
        return output_schema_map

    def _build_server_components(self) -> tuple[Any, Any, list, Any, str]:
        """Build shared MCP server components used by serve() and async_serve().

        Returns:
            Tuple of (server, router, tools, init_options, version).

        Note:
            ``MCPServerFactory``, ``ExecutionRouter``, and ``AsyncTaskBridge``
            are resolved via the :mod:`apcore_mcp` package so that tests
            patching ``apcore_mcp.MCPServerFactory`` / ``apcore_mcp.ExecutionRouter``
            intercept these construction sites.
        """
        _pkg = importlib.import_module("apcore_mcp")
        MCPServerFactory = _pkg.MCPServerFactory
        ExecutionRouter = _pkg.ExecutionRouter

        version = self._resolve_version()

        factory = MCPServerFactory()
        server = factory.create_server(name=self._name, version=version)
        tools = factory.build_tools(self._registry, tags=self._tags, prefix=self._prefix)

        router = ExecutionRouter(
            self._executor,
            validate_inputs=self._validate_inputs,
            output_formatter=self._output_formatter,
            output_format=self._output_format,
            redact_output=self._redact_output,
            output_schema_map=self._build_output_schema_map(),
            trace=self._trace,
        )

        async_bridge: Any = None
        if self._async_tasks:
            from apcore.async_task import AsyncTaskManager

            from apcore_mcp.server.async_task_bridge import AsyncTaskBridge

            mgr = AsyncTaskManager(
                self._executor,
                max_concurrent=self._async_max_concurrent,
                max_tasks=self._async_max_tasks,
            )
            async_bridge = AsyncTaskBridge(mgr)
            self._async_bridge = async_bridge

        descriptor_lookup = self._registry.get_definition if self._async_tasks else None
        factory.register_handlers(
            server,
            tools,
            router,
            async_bridge=async_bridge,
            descriptor_lookup=descriptor_lookup,
        )
        factory.register_resource_handlers(server, self._registry)
        init_options = factory.build_init_options(server, name=self._name, version=version)

        return server, router, tools, init_options, version

    def _build_explorer_routes(
        self,
        router: Any,
        *,
        allow_execute: bool,
        explorer_prefix: str,
        explorer_title: str,
        explorer_project_name: str | None,
        explorer_project_url: str | None,
    ) -> list[Route | Mount]:
        """Build explorer mount routes.

        Builds a parallel non-strict tool list for the Explorer "Try it" UI
        because strict-mode schemas strip defaults and mark optional fields as
        ``["string","null"]``, which surfaces as ``null`` in the form.
        """
        _pkg = importlib.import_module("apcore_mcp")
        MCPServerFactory = _pkg.MCPServerFactory
        from apcore_mcp.explorer import create_explorer_mount

        explorer_tools = MCPServerFactory(strict=False).build_tools(
            self._registry, tags=self._tags, prefix=self._prefix, strict=False
        )
        mount = create_explorer_mount(
            explorer_tools,
            router,
            allow_execute=allow_execute,
            explorer_prefix=explorer_prefix,
            authenticator=self._authenticator,
            title=explorer_title,
            project_name=explorer_project_name,
            project_url=explorer_project_url,
        )
        logger.info("Tool Explorer enabled at %s", explorer_prefix)
        return [mount]

    def _build_auth_middleware(
        self,
        *,
        explorer: bool = False,
        explorer_prefix: str = "/explorer",
    ) -> list[tuple[type, dict]] | None:
        """Build auth middleware list if authenticator is configured."""
        if self._authenticator is None:
            return None

        from apcore_mcp.auth import AuthMiddleware

        mw_kwargs: dict[str, object] = {"authenticator": self._authenticator}
        if not self._require_auth:
            mw_kwargs["require_auth"] = False
        if self._exempt_paths is not None:
            mw_kwargs["exempt_paths"] = self._exempt_paths
        if explorer:
            mw_kwargs["exempt_prefixes"] = {explorer_prefix}
        return [(AuthMiddleware, mw_kwargs)]

    def _maybe_append_usage_routes(
        self,
        extra_routes: list[Route | Mount] | None,
        *,
        explorer_prefix: str,
    ) -> list[Route | Mount] | None:
        """Append usage routes to ``extra_routes`` when both UsageCollector and
        explorer routes are present. Mirrors prior pipeline behaviour.
        """
        if self._usage_collector is None or extra_routes is None:
            return extra_routes
        from apcore_mcp.explorer import create_usage_routes

        extra_routes.extend(create_usage_routes(self._usage_collector, prefix=explorer_prefix))
        return extra_routes

    # ---------------------------------------------------------------- serve()
    def serve(
        self,
        *,
        transport: str = "stdio",
        host: str = "127.0.0.1",
        port: int = 8000,
        on_startup: Callable[[], None] | None = None,
        on_shutdown: Callable[[], None] | None = None,
        explorer: bool = False,
        explorer_prefix: str = "/explorer",
        allow_execute: bool = False,
        explorer_title: str = "APCore MCP Explorer",
        explorer_project_name: str | None = "apcore-mcp",
        explorer_project_url: str | None = "https://github.com/aiperceivable/apcore-mcp-python",
        output_format: str | None = None,
    ) -> None:
        """Launch the MCP server (blocking).

        Args:
            transport: Transport type - "stdio", "streamable-http", or "sse".
            host: Host address for HTTP-based transports.
            port: Port number for HTTP-based transports.
            on_startup: Optional callback invoked after setup, before transport starts.
            on_shutdown: Optional callback invoked after the transport completes.
            explorer: Enable the browser-based Tool Explorer UI (HTTP only).
            explorer_prefix: URL prefix for the explorer (default: "/explorer").
            allow_execute: Allow tool execution from the explorer UI.
            explorer_title: Page title for the explorer UI.
            explorer_project_name: Project name shown in the explorer footer.
            explorer_project_url: Project URL linked in the explorer footer.
            output_format: Built-in output format name ("json", "csv", "jsonl").
        """
        if explorer and not explorer_prefix.startswith("/"):
            raise ValueError("explorer_prefix must start with '/'")

        # output_format passed to serve() overrides the instance default for
        # this run only. We mutate the router below by recomputing it.
        if output_format is not None:
            self._output_format = output_format

        _pkg = importlib.import_module("apcore_mcp")
        TransportManager = _pkg.TransportManager

        # Re-read Config Bus scalar overrides for transport/host/port — these
        # are only meaningful at serve() time (the ASGI-app entry point ignores
        # them).
        _cfg = _load_config_bus_overrides(
            registry=self._registry,
            strategy=None,
            load_pipeline=False,
        )
        scalars: dict[str, object] = _cfg["scalars"]  # type: ignore[assignment]
        if "transport" in scalars:
            transport = scalars["transport"]  # type: ignore[assignment]
        if "host" in scalars:
            host = scalars["host"]  # type: ignore[assignment]
        if "port" in scalars:
            port = scalars["port"]  # type: ignore[assignment]
        if "explorer" in scalars:
            explorer = scalars["explorer"]  # type: ignore[assignment]
        if "explorer_prefix" in scalars:
            explorer_prefix = scalars["explorer_prefix"]  # type: ignore[assignment]

        server, router, tools, init_options, version = self._build_server_components()

        if self._dynamic:
            from apcore_mcp.server.listener import RegistryListener

            _pkg2 = importlib.import_module("apcore_mcp")
            MCPServerFactory = _pkg2.MCPServerFactory
            listener = RegistryListener(self._registry, MCPServerFactory())
            listener.start()
            logger.info("RegistryListener started for dynamic tool registration")

        logger.info(
            "Starting MCP server '%s' v%s with %d tools via %s",
            self._name,
            version,
            len(tools),
            transport,
        )

        transport_lower = transport.lower()
        extra_routes: list[Route | Mount] | None = None
        if explorer and transport_lower in ("streamable-http", "sse"):
            extra_routes = self._build_explorer_routes(
                router,
                allow_execute=allow_execute,
                explorer_prefix=explorer_prefix,
                explorer_title=explorer_title,
                explorer_project_name=explorer_project_name,
                explorer_project_url=explorer_project_url,
            )

        auth_middleware: list[tuple[type, dict]] | None = None
        if self._authenticator is not None and transport_lower in ("streamable-http", "sse"):
            auth_middleware = self._build_auth_middleware(
                explorer=explorer,
                explorer_prefix=explorer_prefix,
            )

        transport_manager = TransportManager(metrics_collector=self._metrics_collector)
        transport_manager.set_module_count(len(tools))
        extra_routes = self._maybe_append_usage_routes(extra_routes, explorer_prefix=explorer_prefix)

        async def _run() -> None:
            if transport_lower == "stdio":
                await transport_manager.run_stdio(server, init_options)
            elif transport_lower == "streamable-http":
                await transport_manager.run_streamable_http(
                    server,
                    init_options,
                    host=host,
                    port=port,
                    extra_routes=extra_routes,
                    middleware=auth_middleware,
                )
            elif transport_lower == "sse":
                await transport_manager.run_sse(
                    server,
                    init_options,
                    host=host,
                    port=port,
                    extra_routes=extra_routes,
                    middleware=auth_middleware,
                )
            else:
                raise ValueError(
                    f"Unknown transport: {transport!r}. Expected 'stdio', 'streamable-http', or 'sse'."
                )

        if on_startup is not None:
            on_startup()

        try:
            asyncio.run(_run())
        finally:
            if on_shutdown is not None:
                on_shutdown()

    # ---------------------------------------------------------- async_serve()
    @contextlib.asynccontextmanager
    async def async_serve(
        self,
        *,
        explorer: bool = False,
        explorer_prefix: str = "/explorer",
        allow_execute: bool = False,
        explorer_title: str = "APCore MCP Explorer",
        explorer_project_name: str | None = "apcore-mcp",
        explorer_project_url: str | None = "https://github.com/aiperceivable/apcore-mcp-python",
        output_format: str | None = None,
    ) -> AsyncIterator[Starlette]:
        """Build an MCP Starlette ASGI app for embedding into a larger service.

        Use this when you want to mount the MCP server alongside other ASGI apps.

        Example::

            async with mcp.async_serve(explorer=True) as mcp_app:
                combined = Starlette(routes=[
                    Mount("/mcp", app=mcp_app),
                    Mount("/a2a", app=a2a_app),
                ])
                config = uvicorn.Config(combined, host="0.0.0.0", port=8000)
                await uvicorn.Server(config).serve()

        Args:
            explorer: Enable the browser-based Tool Explorer UI.
            explorer_prefix: URL prefix for the explorer (default: "/explorer").
            allow_execute: Allow tool execution from the explorer UI.
            explorer_title: Page title for the explorer UI.
            explorer_project_name: Project name shown in the explorer footer.
            explorer_project_url: Project URL linked in the explorer footer.
            output_format: Built-in output format name ("json", "csv", "jsonl").

        Yields:
            A configured Starlette ASGI application with MCP endpoints.
        """
        if explorer and not explorer_prefix.startswith("/"):
            raise ValueError("explorer_prefix must start with '/'")

        if output_format is not None:
            self._output_format = output_format

        _pkg = importlib.import_module("apcore_mcp")
        TransportManager = _pkg.TransportManager

        server, router, tools, init_options, version = self._build_server_components()

        logger.info(
            "Building MCP app '%s' v%s with %d tools",
            self._name,
            version,
            len(tools),
        )

        extra_routes: list[Route | Mount] | None = None
        if explorer:
            extra_routes = self._build_explorer_routes(
                router,
                allow_execute=allow_execute,
                explorer_prefix=explorer_prefix,
                explorer_title=explorer_title,
                explorer_project_name=explorer_project_name,
                explorer_project_url=explorer_project_url,
            )

        auth_middleware: list[tuple[type, dict]] | None = None
        if self._authenticator is not None:
            auth_middleware = self._build_auth_middleware(
                explorer=explorer,
                explorer_prefix=explorer_prefix,
            )

        transport_manager = TransportManager(metrics_collector=self._metrics_collector)
        transport_manager.set_module_count(len(tools))
        extra_routes = self._maybe_append_usage_routes(extra_routes, explorer_prefix=explorer_prefix)

        async with transport_manager.build_streamable_http_app(
            server,
            init_options,
            extra_routes=extra_routes,
            middleware=auth_middleware,
        ) as app:
            yield app

    # ----------------------------------------------------------- openai tools
    def to_openai_tools(
        self,
        *,
        embed_annotations: bool = False,
        strict: bool = False,
    ) -> list[dict]:
        """Export modules as OpenAI-compatible tool definitions.

        Args:
            embed_annotations: Embed annotation metadata in tool descriptions.
            strict: Add strict: true for OpenAI Structured Outputs.

        Returns:
            List of OpenAI tool definition dicts, directly usable with
            openai.chat.completions.create(tools=...).
        """
        from apcore_mcp.converters.openai import OpenAIConverter

        converter = OpenAIConverter()
        tools = converter.convert_registry(
            self._registry,
            embed_annotations=embed_annotations,
            strict=strict,
            tags=self._tags,
            prefix=self._prefix,
        )
        logger.debug("Converted %d tools to OpenAI format", len(tools))
        return tools
