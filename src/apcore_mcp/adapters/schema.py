"""SchemaConverter: apcore schemas → MCP inputSchema / OpenAI parameters."""

from __future__ import annotations

import copy
from typing import Any


class SchemaConverter:
    """Converts apcore ModuleDescriptor schemas to MCP-compatible schemas.

    Key transformations:
    - Empty schemas → {"type": "object", "properties": {}}
    - Schemas with $defs and $ref → inline all refs, strip $defs
    - Ensures all schemas have "type": "object" at the root level
    - Returns deep copies (doesn't modify original schemas)
    """

    def convert_input_schema(self, descriptor: Any) -> dict[str, Any]:
        """Convert apcore ModuleDescriptor.input_schema to MCP inputSchema.

        Args:
            descriptor: ModuleDescriptor with input_schema attribute

        Returns:
            MCP-compatible schema dict with $refs inlined and $defs removed
        """
        schema = descriptor.input_schema
        return self._convert_schema(schema)

    def convert_output_schema(self, descriptor: Any) -> dict[str, Any]:
        """Convert apcore ModuleDescriptor.output_schema.

        Args:
            descriptor: ModuleDescriptor with output_schema attribute

        Returns:
            MCP-compatible schema dict with $refs inlined and $defs removed
        """
        schema = descriptor.output_schema
        return self._convert_schema(schema)

    def _convert_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Convert a schema, applying all transformations.

        Args:
            schema: JSON Schema dict to convert

        Returns:
            Converted schema with $refs inlined, $defs removed, and type ensured
        """
        # Make a deep copy to avoid modifying the original
        schema = copy.deepcopy(schema)

        # Handle empty schema
        if not schema:
            return {"type": "object", "properties": {}}

        # Inline $refs if present
        if "$defs" in schema:
            defs = schema["$defs"]
            schema = self._inline_refs(schema, defs)
            # Remove $defs from the final schema
            schema.pop("$defs", None)

        # Ensure schema has type: object
        schema = self._ensure_object_type(schema)

        return schema

    def _inline_refs(
        self,
        schema: dict[str, Any],
        defs: dict[str, Any],
        _seen: set[str] | None = None,
    ) -> dict[str, Any]:
        """Recursively inline all $ref references, removing $defs.

        Args:
            schema: Schema dict that may contain $refs
            defs: Dictionary of definitions from $defs
            _seen: Internal set tracking visited $ref paths to prevent
                infinite recursion on circular references.

        Returns:
            Schema with all $refs replaced by their definitions

        Raises:
            ValueError: If a circular $ref is detected.
        """
        if _seen is None:
            _seen = set()

        if isinstance(schema, dict):
            # If this is a $ref, resolve it
            if "$ref" in schema:
                ref_path = schema["$ref"]
                if ref_path in _seen:
                    raise ValueError(f"Circular $ref detected: {ref_path}")
                _seen = _seen | {ref_path}
                resolved = self._resolve_ref(ref_path, defs)
                # Recursively inline refs in the resolved schema
                return self._inline_refs(resolved, defs, _seen)

            # Otherwise, recursively process all values
            result = {}
            for key, value in schema.items():
                if key == "$defs":
                    # Skip $defs, we'll remove it later
                    continue
                result[key] = self._inline_refs(value, defs, _seen)
            return result
        elif isinstance(schema, list):
            # Recursively process list items
            return [self._inline_refs(item, defs, _seen) for item in schema]
        else:
            # Primitive value, return as-is
            return schema

    def _resolve_ref(self, ref_path: str, defs: dict[str, Any]) -> dict[str, Any]:
        """Resolve a single $ref path against $defs.

        Args:
            ref_path: JSON Schema $ref path like "#/$defs/Step"
            defs: Dictionary of definitions

        Returns:
            The resolved schema definition (deep copy)

        Raises:
            ValueError: If the $ref path is invalid or not found
        """
        # Parse the $ref path
        # Expected format: "#/$defs/DefinitionName"
        if not ref_path.startswith("#/$defs/"):
            raise ValueError(f"Unsupported $ref format: {ref_path}")

        # Extract the definition name
        def_name = ref_path[8:]  # Remove "#/$defs/"

        if def_name not in defs:
            raise ValueError(f"Definition not found: {def_name}")

        # Return a deep copy to avoid circular reference issues
        return copy.deepcopy(defs[def_name])

    def _ensure_object_type(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Ensure schema has type: object with properties.

        Args:
            schema: Schema dict that may be missing "type"

        Returns:
            Schema with "type": "object" guaranteed at root level
        """
        # If schema doesn't have a type, add type: object
        if "type" not in schema:
            schema["type"] = "object"

        # If schema has properties but no type, ensure it's an object
        if "properties" in schema and schema.get("type") != "object":
            schema["type"] = "object"

        return schema
