"""Custom exceptions for the `profile_detect` module.

By design, profile_detect itself does not raise to the worker on identification
failure — it returns a `generic_table_dataset` fallback or a `_candidate`
variant with low confidence. `ProfileDetectError` is reserved for internal
sanity-check failures (e.g. malformed `ProfileDetectResult` constructed
from an inconsistent detector path) that indicate a bug rather than data.
"""
from __future__ import annotations


class ProfileDetectError(Exception):
    """Internal contract violation in profile_detect.

    Worker / pipeline code should not catch this; it indicates a programming
    error in a detector implementation (e.g. emitting an unknown record_type
    string, or a confidence outside [0, 1]).
    """
