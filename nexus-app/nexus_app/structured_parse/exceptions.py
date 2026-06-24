"""Custom exceptions for the `structured_parse` module."""
from __future__ import annotations


class StructuredParseError(Exception):
    """Base class for any failure during structured_parse.

    Wraps low-level openpyxl / csv / json errors so the worker layer can treat
    parse failures uniformly (fail the stage, write PIPELINE_FAILED audit, mark
    the job FAILED — see B1.3 worker integration).
    """


class CorruptSourceError(StructuredParseError):
    """The source bytes could not be opened (e.g. truncated xlsx, invalid zip)."""


class EmptySourceError(StructuredParseError):
    """The source opened but contained no parseable content (no sheets / no rows)."""


class UnsupportedFormatError(StructuredParseError):
    """The format-specific parser cannot handle this MIME / extension."""
