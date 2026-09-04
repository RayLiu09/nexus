"""Professional teaching-standard and course fact projections."""

from nexus_app.teaching_standard_library.course_extractor import extract as extract_courses
from nexus_app.teaching_standard_library.course_writer import write as write_courses
from nexus_app.teaching_standard_library.derivation_service import derive_library
from nexus_app.teaching_standard_library.extractor import extract
from nexus_app.teaching_standard_library.writer import write

__all__ = ["derive_library", "extract", "extract_courses", "write", "write_courses"]
