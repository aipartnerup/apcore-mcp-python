"""ModuleIDNormalizer: dot-notation module IDs ↔ OpenAI-compatible names."""

from __future__ import annotations

from apcore_mcp.constants import MODULE_ID_PATTERN


class ModuleIDNormalizer:
    """Convert between apcore module IDs and OpenAI-compatible function names.

    OpenAI function names must match the pattern ^[a-zA-Z0-9_-]+$.
    apcore module IDs use dot notation (e.g., "image.resize").

    This normalizer provides a bijective mapping:
    - normalize: replace "." with "-"
    - denormalize: replace "-" with "."

    NOTE: This assumes module IDs do not contain literal dashes.
    If they do, the roundtrip will not work correctly.
    This is an acceptable trade-off documented in the tech design.
    """

    def normalize(self, module_id: str) -> str:
        """Convert apcore module_id to OpenAI-compatible function name.

        Replaces '.' with '-' to satisfy ^[a-zA-Z0-9_-]+$ pattern.

        Args:
            module_id: The apcore module ID (e.g., "image.resize")

        Returns:
            OpenAI-compatible function name (e.g., "image-resize")

        Examples:
            >>> normalizer = ModuleIDNormalizer()
            >>> normalizer.normalize("image.resize")
            'image-resize'
            >>> normalizer.normalize("comfyui.image.resize.v2")
            'comfyui-image-resize-v2'
            >>> normalizer.normalize("ping")
            'ping'
        Raises:
            ValueError: If the module_id does not match the required pattern.
        """
        if not MODULE_ID_PATTERN.match(module_id):
            raise ValueError(
                f"Invalid module ID '{module_id}': must match pattern ^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$"
            )
        return module_id.replace(".", "-")

    def denormalize(self, tool_name: str) -> str:
        """Convert OpenAI function name back to apcore module_id.

        Replaces '-' with '.' (inverse of normalize).

        Args:
            tool_name: The OpenAI function name (e.g., "image-resize")

        Returns:
            apcore module ID (e.g., "image.resize")

        Examples:
            >>> normalizer = ModuleIDNormalizer()
            >>> normalizer.denormalize("image-resize")
            'image.resize'
            >>> normalizer.denormalize("comfyui-image-resize-v2")
            'comfyui.image.resize.v2'
            >>> normalizer.denormalize("ping")
            'ping'
        """
        return tool_name.replace("-", ".")
