"""AnnotationMapper: apcore ModuleAnnotations → MCP ToolAnnotations."""

from __future__ import annotations

from typing import Any

DEFAULT_ANNOTATIONS = {
    "readonly": False,
    "destructive": False,
    "idempotent": False,
    "requires_approval": False,
    "open_world": True,
}


class AnnotationMapper:
    """Maps apcore ModuleAnnotations to MCP ToolAnnotations format.

    This adapter converts between apcore's module annotation system and
    MCP's tool annotation hints, enabling proper tool behavior signaling
    to LLM clients.
    """

    def to_mcp_annotations(self, annotations: Any | None) -> dict[str, Any]:
        """Convert ModuleAnnotations to MCP ToolAnnotations dict.

        Args:
            annotations: ModuleAnnotations instance or None

        Returns:
            Dict with MCP ToolAnnotations fields:
            - read_only_hint: bool | None
            - destructive_hint: bool | None
            - idempotent_hint: bool | None
            - open_world_hint: bool | None
            - title: str | None
        """
        # Default values when annotations is None
        if annotations is None:
            return {
                "read_only_hint": False,
                "destructive_hint": False,
                "idempotent_hint": False,
                "open_world_hint": True,
                "title": None,
            }

        # Map apcore ModuleAnnotations to MCP ToolAnnotations
        return {
            "read_only_hint": annotations.readonly,
            "destructive_hint": annotations.destructive,
            "idempotent_hint": annotations.idempotent,
            "open_world_hint": annotations.open_world,
            "title": None,  # MCP title is not mapped from apcore annotations
        }

    def to_description_suffix(self, annotations: Any | None) -> str:
        """Generate annotation text to append to OpenAI tool descriptions.

        This creates a human-readable suffix that embeds annotation metadata
        in the tool description for LLM clients that don't support MCP's
        native annotation hints.

        Args:
            annotations: ModuleAnnotations instance or None

        Returns:
            String suffix in format: "\\n\\n[Annotations: key=value, ...]"
            Empty string if annotations is None
        """
        if annotations is None:
            return ""

        # Build annotation key-value pairs only for non-default values
        parts = []
        if annotations.readonly != DEFAULT_ANNOTATIONS["readonly"]:
            parts.append(f"readonly={str(annotations.readonly).lower()}")
        if annotations.destructive != DEFAULT_ANNOTATIONS["destructive"]:
            parts.append(f"destructive={str(annotations.destructive).lower()}")
        if annotations.idempotent != DEFAULT_ANNOTATIONS["idempotent"]:
            parts.append(f"idempotent={str(annotations.idempotent).lower()}")
        if annotations.requires_approval != DEFAULT_ANNOTATIONS["requires_approval"]:
            parts.append(f"requires_approval={str(annotations.requires_approval).lower()}")
        if annotations.open_world != DEFAULT_ANNOTATIONS["open_world"]:
            parts.append(f"open_world={str(annotations.open_world).lower()}")

        if not parts:
            return ""

        return f"\n\n[Annotations: {', '.join(parts)}]"

    def has_requires_approval(self, annotations: Any | None) -> bool:
        """Check if module requires human approval before execution.

        Args:
            annotations: ModuleAnnotations instance or None

        Returns:
            True if requires_approval is set, False otherwise
        """
        if annotations is None:
            return False

        return annotations.requires_approval
