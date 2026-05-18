"""OpenAIConverter: apcore Registry -> OpenAI-compatible tool definitions."""

from __future__ import annotations

import logging
from typing import Any

from apcore.schema.strict import _apply_llm_descriptions, to_strict_schema

import apcore_mcp.markdown as _markdown
from apcore_mcp.adapters.annotations import AnnotationMapper
from apcore_mcp.adapters.id_normalizer import ModuleIDNormalizer
from apcore_mcp.adapters.schema import SchemaConverter

_logger = logging.getLogger(__name__)


class OpenAIConverter:
    """Converts apcore Registry modules to OpenAI-compatible tool definitions."""

    def __init__(self) -> None:
        """Initialize with internal SchemaConverter, AnnotationMapper, and ModuleIDNormalizer."""
        self._schema_converter = SchemaConverter()
        self._annotation_mapper = AnnotationMapper()
        self._id_normalizer = ModuleIDNormalizer()
        # One-shot flag: warn about missing apcore-toolkit at most once
        # per converter instance instead of once per descriptor (mirrors
        # MCPServerFactory._warned_toolkit_missing).
        self._warned_toolkit_missing = False

    def convert_registry(
        self,
        registry: Any,
        embed_annotations: bool = False,
        strict: bool = False,
        tags: list[str] | None = None,
        prefix: str | None = None,
        rich_description: bool = False,
    ) -> list[dict[str, Any]]:
        """Convert all modules in a Registry to OpenAI tool definitions.

        Uses registry.list(tags=tags, prefix=prefix) for filtering.
        For each module_id, gets descriptor via registry.get_definition(module_id).
        Skips modules where get_definition returns None (race condition).

        Args:
            registry: apcore Registry (duck typed) with list() and get_definition() methods.
            embed_annotations: If True, append annotation hints to descriptions.
            strict: If True, enable OpenAI strict mode on schemas.
            tags: Optional tag filter passed to registry.list().
            prefix: Optional prefix filter passed to registry.list().
            rich_description: If True, replace the plain ``description`` with
                an apcore-toolkit-rendered Markdown body (title, description,
                annotations table, schema, examples). LLMs select tools
                primarily from this string — Markdown delivers more signal
                per token than a single-line summary. Requires the
                ``[markdown]`` extra (``apcore-toolkit``); falls back to
                the plain description with a WARN log when toolkit is
                unavailable.

        Returns:
            List of OpenAI-compatible tool definition dicts.
        """
        module_ids = registry.list(tags=tags, prefix=prefix)
        tools: list[dict[str, Any]] = []
        # [OC-3] Track normalized names so we can detect collisions.
        # OpenAI function names must be unique post-normalization
        # (dot→hyphen). E.g. `a.b` and `a-b` both normalize to `a-b`;
        # without this guard we'd silently emit two tools with identical
        # function.name, producing undefined OpenAI behavior.
        seen_names: dict[str, str] = {}

        for module_id in module_ids:
            descriptor = registry.get_definition(module_id)
            if descriptor is None:
                continue
            tool = self.convert_descriptor(
                descriptor,
                embed_annotations=embed_annotations,
                strict=strict,
                rich_description=rich_description,
            )
            tool_name = tool["function"]["name"]
            if tool_name in seen_names and seen_names[tool_name] != module_id:
                raise ValueError(
                    f"OpenAI function-name collision: module ids "
                    f"{seen_names[tool_name]!r} and {module_id!r} both normalize "
                    f"to {tool_name!r}. OpenAI requires unique function names; "
                    f"rename one of the modules to avoid the collision."
                )
            seen_names[tool_name] = module_id
            tools.append(tool)

        return tools

    def convert_descriptor(
        self,
        descriptor: Any,
        embed_annotations: bool = False,
        strict: bool = True,
        rich_description: bool = False,
    ) -> dict[str, Any]:
        """Convert a single ModuleDescriptor to OpenAI tool definition.

        Args:
            descriptor: ModuleDescriptor with module_id, description, input_schema,
                and optional annotations.
            embed_annotations: If True, append annotation hints to description.
            strict: If True (default since 0.16.0, parity with TS), enable OpenAI
                strict mode: inject ``additionalProperties: false``, hoist all
                properties into ``required`` (with optionals widened to nullable),
                and emit ``strict: true`` on the function. [D11-5]
            rich_description: If True, render the description as
                apcore-toolkit Markdown (see :func:`convert_registry`).

        Returns:
            Dict with structure:
            {
                "type": "function",
                "function": {
                    "name": <normalized_id>,
                    "description": <description [+ annotation suffix]>,
                    "parameters": <converted input_schema>,
                    "strict": True  # only if strict=True
                }
            }
        """
        name = self._id_normalizer.normalize(descriptor.module_id)
        parameters = self._schema_converter.convert_input_schema(descriptor)

        description = self._render_description(
            descriptor,
            embed_annotations=embed_annotations,
            rich_description=rich_description,
        )

        # Apply strict mode transformations if requested
        if strict:
            parameters = self._apply_strict_mode(parameters)

        # Build the function dict
        function: dict[str, Any] = {
            "name": name,
            "description": description,
            "parameters": parameters,
        }

        if strict:
            function["strict"] = True

        return {
            "type": "function",
            "function": function,
        }

    def _render_description(
        self,
        descriptor: Any,
        *,
        embed_annotations: bool,
        rich_description: bool,
    ) -> str:
        """Resolve the OpenAI ``description`` field for a module descriptor.

        ``rich_description`` takes precedence: when toolkit is installed
        the LLM-facing description is the canonical Markdown rendering
        from ``apcore_toolkit.format_module``. ``embed_annotations`` is
        still honoured (suffix appended) as a strict superset.
        """
        base = descriptor.description or ""
        if rich_description:
            if _markdown.is_available():
                try:
                    base = _markdown.render_module_markdown(descriptor)
                except Exception:
                    _logger.warning(
                        "rich_description: format_module failed for %s; " "falling back to plain description",
                        descriptor.module_id,
                        exc_info=True,
                    )
            elif not self._warned_toolkit_missing:
                self._warned_toolkit_missing = True
                _logger.warning(
                    "rich_description: apcore-toolkit not installed; "
                    "install 'apcore-mcp[markdown]' to enable Markdown "
                    "tool descriptions. Falling back to plain descriptions."
                )
        if embed_annotations:
            base += self._annotation_mapper.to_description_suffix(
                descriptor.annotations,
            )
        return base

    def _apply_strict_mode(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Convert schema to OpenAI strict mode via apcore's to_strict_schema().

        Steps:
        1. Deep-copies the input (done by to_strict_schema)
        2. Promotes x-llm-description to description (before stripping)
        3. Strips x-* extensions and default values
        4. Sets additionalProperties: false on all objects
        5. Makes all properties required (sorted alphabetically)
        6. Optional properties become nullable
        7. Recurses into nested objects, array items, oneOf/anyOf/allOf, and $defs

        This matches the behavior of SchemaExporter.export_openai().

        Args:
            schema: JSON Schema dict to transform.

        Returns:
            New schema dict with strict mode applied.
        """
        import copy

        schema = copy.deepcopy(schema)
        _apply_llm_descriptions(schema)
        return to_strict_schema(schema)
