from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.config import Settings
from nexus_app.enums import PipelineType
from nexus_app.image_analysis import ImageAnalyzer
from nexus_app.mineru import MinerUAdapter
from nexus_app.storage import ObjectStorage


@dataclass
class PipelineContext:
    session: Session
    storage: ObjectStorage
    settings: Settings
    mineru: MinerUAdapter | None  # None for Pipeline B (record) — record pipeline never calls MinerU
    job: models.Job
    raw_object: models.RawObject
    batch: models.IngestBatch
    trace_id: str | None
    pipeline_type: PipelineType = PipelineType.DOCUMENT
    image_analyzer: ImageAnalyzer | None = None  # None disables VLM image analysis
