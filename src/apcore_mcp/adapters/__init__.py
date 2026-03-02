"""Adapters: schema conversion, annotation mapping, error mapping, ID normalization, approval."""

from apcore_mcp.adapters.annotations import AnnotationMapper
from apcore_mcp.adapters.approval import ElicitationApprovalHandler
from apcore_mcp.adapters.errors import ErrorMapper
from apcore_mcp.adapters.id_normalizer import ModuleIDNormalizer

__all__ = ["AnnotationMapper", "ElicitationApprovalHandler", "ErrorMapper", "ModuleIDNormalizer"]
