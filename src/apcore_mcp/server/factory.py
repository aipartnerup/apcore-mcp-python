"""MCPServerFactory: create and configure MCP Server with tools from apcore Registry."""

from __future__ import annotations

import logging
from typing import Any

from mcp import types as mcp_types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from apcore_mcp.adapters.annotations import AnnotationMapper
from apcore_mcp.adapters.schema import SchemaConverter

logger = logging.getLogger(__name__)


class MCPServerFactory:
    """Creates and configures MCP Server instances from apcore Registry."""

    def __init__(self) -> None:
        self._schema_converter = SchemaConverter()
        self._annotation_mapper = AnnotationMapper()

    def create_server(self, name: str = "apcore-mcp", version: str = "0.1.0") -> Server:
        """Create a new MCP low-level Server instance.

        Args:
            name: Server name for identification.
            version: Server version string.

        Returns:
            A configured Server. Handlers are NOT registered yet.
        """
        return Server(name)

    def build_tool(self, descriptor: Any) -> mcp_types.Tool:
        """Build an MCP Tool from a ModuleDescriptor.

        Mapping:
        - descriptor.module_id -> Tool.name
        - descriptor.description -> Tool.description
        - SchemaConverter.convert_input_schema(descriptor) -> Tool.inputSchema
        - AnnotationMapper.to_mcp_annotations(descriptor.annotations) -> ToolAnnotations

        The AnnotationMapper returns a dict with snake_case keys
        (read_only_hint, destructive_hint, etc.). This method converts them
        to the camelCase ToolAnnotations fields (readOnlyHint, etc.).

        Args:
            descriptor: ModuleDescriptor with module_id, description,
                        input_schema, and annotations attributes.

        Returns:
            An MCP Tool object ready for registration.
        """
        input_schema = self._schema_converter.convert_input_schema(descriptor)
        annotations_dict = self._annotation_mapper.to_mcp_annotations(descriptor.annotations)

        tool_annotations = mcp_types.ToolAnnotations(
            readOnlyHint=annotations_dict.get("read_only_hint"),
            destructiveHint=annotations_dict.get("destructive_hint"),
            idempotentHint=annotations_dict.get("idempotent_hint"),
            openWorldHint=annotations_dict.get("open_world_hint"),
            title=annotations_dict.get("title"),
        )

        # Build optional _meta with requires_approval and streaming hints
        meta: dict[str, object] | None = None
        if self._annotation_mapper.has_requires_approval(descriptor.annotations):
            meta = {"requires_approval": True}
        if (
            descriptor.annotations is not None
            and getattr(descriptor.annotations, "streaming", False)
        ):
            if meta is None:
                meta = {}
            meta["streaming"] = True

        return mcp_types.Tool(
            name=descriptor.module_id,
            description=descriptor.description,
            inputSchema=input_schema,
            annotations=tool_annotations,
            _meta=meta,
        )

    def build_tools(
        self,
        registry: Any,
        tags: list[str] | None = None,
        prefix: str | None = None,
    ) -> list[mcp_types.Tool]:
        """Build Tool objects for all modules in a Registry.

        Uses registry.list(tags=tags, prefix=prefix) to discover module IDs,
        then registry.get_definition() to obtain each descriptor. Modules
        whose definition is None are skipped. Errors during build_tool are
        logged as warnings and the module is skipped.

        Args:
            registry: An apcore Registry (or compatible stub) with list()
                      and get_definition() methods.
            tags: Optional tag filter passed to registry.list().
            prefix: Optional prefix filter passed to registry.list().

        Returns:
            List of successfully built MCP Tool objects.
        """
        tools: list[mcp_types.Tool] = []
        for module_id in registry.list(tags=tags, prefix=prefix):
            descriptor = registry.get_definition(module_id)
            if descriptor is None:
                logger.warning("Skipped module %s: no definition found", module_id)
                continue
            try:
                tools.append(self.build_tool(descriptor))
            except Exception as e:
                logger.warning("Failed to build tool for %s: %s", module_id, e)
                continue
        return tools

    def register_handlers(
        self,
        server: Server,
        tools: list[mcp_types.Tool],
        router: Any,
    ) -> None:
        """Register list_tools and call_tool handlers on the Server.

        The call_tool handler extracts the progress token from the MCP
        request context (if present) and passes it to the router via
        the ``extra`` dict so that the router can stream chunks as
        ``notifications/progress`` messages.

        Args:
            server: The MCP Server to register handlers on.
            tools: List of Tool objects to expose via list_tools.
            router: A router with an async handle_call(name, arguments, extra)
                    method that returns (content_list, is_error).
        """

        @server.list_tools()
        async def handle_list_tools() -> list[mcp_types.Tool]:
            return list(tools)

        @server.call_tool()
        async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
            from mcp.server.lowlevel.server import request_ctx

            ctx = request_ctx.get()
            progress_token = ctx.meta.progressToken if ctx.meta else None
            extra: dict[str, Any] | None = None

            if progress_token is not None:
                async def send_notification(notification: dict[str, Any]) -> None:
                    await ctx.session.send_progress_notification(
                        progress_token=notification["params"]["progressToken"],
                        progress=notification["params"]["progress"],
                        total=notification["params"].get("total"),
                        message=notification["params"].get("message"),
                    )

                extra = {
                    "send_notification": send_notification,
                    "progress_token": progress_token,
                }

            content, is_error = await router.handle_call(name, arguments or {}, extra=extra)
            if is_error:
                raise Exception(content[0]["text"])
            return content

    def build_init_options(
        self,
        server: Server,
        name: str,
        version: str,
    ) -> InitializationOptions:
        """Build InitializationOptions for running the server.

        Args:
            server: The configured Server instance.
            name: Server name.
            version: Server version.

        Returns:
            InitializationOptions ready for server.run().
        """
        return InitializationOptions(
            server_name=name,
            server_version=version,
            capabilities=server.get_capabilities(
                notification_options=NotificationOptions(tools_changed=True),
                experimental_capabilities={},
            ),
        )
