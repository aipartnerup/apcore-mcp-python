"""Unit tests for AnnotationMapper."""

from __future__ import annotations

import pytest
from apcore_mcp.adapters.annotations import AnnotationMapper

from tests.conftest import ModuleAnnotations


class TestAnnotationMapper:
    """Test suite for AnnotationMapper."""

    @pytest.fixture
    def mapper(self) -> AnnotationMapper:
        """Create an AnnotationMapper instance for testing."""
        return AnnotationMapper()

    def test_readonly_annotation(self, mapper: AnnotationMapper) -> None:
        """Test readonly annotation maps to read_only_hint=True."""
        annotations = ModuleAnnotations(readonly=True)
        result = mapper.to_mcp_annotations(annotations)

        assert result == {
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": False,
            "open_world_hint": True,
            "title": None,
        }

    def test_destructive_annotation(self, mapper: AnnotationMapper) -> None:
        """Test destructive annotation maps to destructive_hint=True."""
        annotations = ModuleAnnotations(destructive=True)
        result = mapper.to_mcp_annotations(annotations)

        assert result == {
            "read_only_hint": False,
            "destructive_hint": True,
            "idempotent_hint": False,
            "open_world_hint": True,
            "title": None,
        }

    def test_idempotent_annotation(self, mapper: AnnotationMapper) -> None:
        """Test idempotent annotation maps to idempotent_hint=True."""
        annotations = ModuleAnnotations(idempotent=True)
        result = mapper.to_mcp_annotations(annotations)

        assert result == {
            "read_only_hint": False,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": True,
            "title": None,
        }

    def test_open_world_false(self, mapper: AnnotationMapper) -> None:
        """Test open_world=False maps to open_world_hint=False."""
        annotations = ModuleAnnotations(open_world=False)
        result = mapper.to_mcp_annotations(annotations)

        assert result == {
            "read_only_hint": False,
            "destructive_hint": False,
            "idempotent_hint": False,
            "open_world_hint": False,
            "title": None,
        }

    def test_all_defaults(self, mapper: AnnotationMapper) -> None:
        """Test default ModuleAnnotations maps to default MCP annotations."""
        annotations = ModuleAnnotations()
        result = mapper.to_mcp_annotations(annotations)

        assert result == {
            "read_only_hint": False,
            "destructive_hint": False,
            "idempotent_hint": False,
            "open_world_hint": True,
            "title": None,
        }

    def test_none_annotations(self, mapper: AnnotationMapper) -> None:
        """Test None annotations uses default values."""
        result = mapper.to_mcp_annotations(None)

        assert result == {
            "read_only_hint": False,
            "destructive_hint": False,
            "idempotent_hint": False,
            "open_world_hint": True,
            "title": None,
        }

    def test_combined_annotations(self, mapper: AnnotationMapper) -> None:
        """Test multiple annotations combine correctly."""
        annotations = ModuleAnnotations(
            destructive=True,
            requires_approval=True,
            open_world=False,
        )
        result = mapper.to_mcp_annotations(annotations)

        assert result == {
            "read_only_hint": False,
            "destructive_hint": True,
            "idempotent_hint": False,
            "open_world_hint": False,
            "title": None,
        }

    def test_has_requires_approval_true(self, mapper: AnnotationMapper) -> None:
        """Test has_requires_approval returns True when requires_approval=True."""
        annotations = ModuleAnnotations(requires_approval=True)
        assert mapper.has_requires_approval(annotations) is True

    def test_has_requires_approval_false(self, mapper: AnnotationMapper) -> None:
        """Test has_requires_approval returns False for default annotations."""
        annotations = ModuleAnnotations()
        assert mapper.has_requires_approval(annotations) is False

    def test_has_requires_approval_none(self, mapper: AnnotationMapper) -> None:
        """Test has_requires_approval returns False for None annotations."""
        assert mapper.has_requires_approval(None) is False

    def test_description_suffix_with_annotations(self, mapper: AnnotationMapper) -> None:
        """Test description suffix embeds annotations in readable format."""
        annotations = ModuleAnnotations(
            destructive=True,
            readonly=False,
            idempotent=True,
            requires_approval=True,
            open_world=False,
        )
        result = mapper.to_description_suffix(annotations)

        # Expected format: newlines + bracketed annotation list
        assert result.startswith("\n\n[Annotations: ")
        assert result.endswith("]")
        assert "destructive=true" in result.lower()
        assert "readonly=false" in result.lower()
        assert "idempotent=true" in result.lower()
        assert "requires_approval=true" in result.lower()
        assert "open_world=false" in result.lower()

    def test_description_suffix_empty(self, mapper: AnnotationMapper) -> None:
        """Test description suffix returns empty string for None annotations."""
        result = mapper.to_description_suffix(None)
        assert result == ""

    def test_description_suffix_defaults(self, mapper: AnnotationMapper) -> None:
        """Test description suffix with default annotations shows all fields."""
        annotations = ModuleAnnotations()
        result = mapper.to_description_suffix(annotations)

        # Default annotations should still produce a suffix
        assert result.startswith("\n\n[Annotations: ")
        assert "readonly=false" in result.lower()
        assert "destructive=false" in result.lower()
        assert "idempotent=false" in result.lower()
        assert "requires_approval=false" in result.lower()
        assert "open_world=true" in result.lower()
