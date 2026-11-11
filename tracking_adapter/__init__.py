"""Bounded S1 recorded-pose input, without capture, inference or networking."""

from .adapter import RecordedPoseAdapter, ValidationError, validate_manifest

__all__ = ["RecordedPoseAdapter", "ValidationError", "validate_manifest"]
