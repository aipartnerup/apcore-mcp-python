"""OpenAIConverter: apcore Registry -> OpenAI-compatible tool definitions."""

from __future__ import annotations

import copy
from typing import Any

from apcore_mcp.adapters.annotations import AnnotationMapper
from apcore_mcp.adapters.id_normalizer import ModuleIDNormalizer
from apcore_mcp.adapters.schema import SchemaConverter


class OpenAIConverter:
    """Converts apcore Registry modules to OpenAI-compatible tool definitions."""

    def __init__(self) -> None:
        """Initialize with internal SchemaConverter, AnnotationMapper, and ModuleIDNormalizer."""
        self._schema_converter = SchemaConverter()
        self._annotation_mapper = AnnotationMapper()
        self._id_normalizer = ModuleIDNormalizer()

    def convert_registry(
        self,
        registry: Any,
        embed_annotations: bool = False,
        strict: bool = False,
        tags: list[str] | None = None,
        prefix: str | None = None,
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

        Returns:
            List of OpenAI-compatible tool definition dicts.
        """
        module_ids = registry.list(tags=tags, prefix=prefix)
        tools: list[dict[str, Any]] = []

        for module_id in module_ids:
            descriptor = registry.get_definition(module_id)
            if descriptor is None:
                continue
            tools.append(
                self.convert_descriptor(
                    descriptor,
                    embed_annotations=embed_annotations,
                    strict=strict,
                )
            )

        return tools

    def convert_descriptor(
        self,
        descriptor: Any,
        embed_annotations: bool = False,
        strict: bool = False,
    ) -> dict[str, Any]:
        """Convert a single ModuleDescriptor to OpenAI tool definition.

        Args:
            descriptor: ModuleDescriptor with module_id, description, input_schema,
                and optional annotations.
            embed_annotations: If True, append annotation hints to description.
            strict: If True, enable OpenAI strict mode.

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

        # Build description with optional annotation suffix
        description = descriptor.description
        if embed_annotations:
            suffix = self._annotation_mapper.to_description_suffix(
                descriptor.annotations,
            )
            description += suffix

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

    def _apply_strict_mode(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Convert schema to OpenAI strict mode.

        Transformations applied:
        1. Set additionalProperties: false on all object types
        2. Make all properties required (add to "required" list)
        3. Optional properties (not already in required) become nullable
           (type becomes [original, "null"])
        4. Remove default values
        5. Recurse into nested objects and array items

        Args:
            schema: JSON Schema dict to transform.

        Returns:
            New schema dict with strict mode applied (deep copy).
        """
        schema = copy.deepcopy(schema)
        return self._apply_strict_recursive(schema)

    def _apply_strict_recursive(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Recursively apply strict mode transformations to a schema node.

        Args:
            schema: Schema node to transform in place.

        Returns:
            The transformed schema node.
        """
        if not isinstance(schema, dict):
            return schema

        # Process object types
        if schema.get("type") == "object" and "properties" in schema:
            schema["additionalProperties"] = False

            properties = schema["properties"]
            existing_required = set(schema.get("required", []))
            all_property_names = list(properties.keys())

            # Make optional properties nullable and add them to required
            for prop_name in all_property_names:
                prop_schema = properties[prop_name]

                # Remove default values
                prop_schema.pop("default", None)

                # If not already required, make it nullable
                if prop_name not in existing_required:
                    current_type = prop_schema.get("type")
                    if current_type is not None and current_type != "null":
                        if isinstance(current_type, list):
                            if "null" not in current_type:
                                prop_schema["type"] = current_type + ["null"]
                        else:
                            prop_schema["type"] = [current_type, "null"]

                # Recurse into nested properties
                properties[prop_name] = self._apply_strict_recursive(prop_schema)

            # All properties become required
            schema["required"] = all_property_names

        # Recurse into array items
        if schema.get("type") == "array" and "items" in schema:
            schema["items"] = self._apply_strict_recursive(schema["items"])

        return schema
