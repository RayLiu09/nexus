from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.config import Settings
from nexus_app.mineru import MinerUAdapter
from nexus_app.storage import ObjectStorage


@dataclass
class PipelineContext:
    session: Session
    storage: ObjectStorage
    settings: Settings
    mineru: MinerUAdapter
    job: models.Job
    raw_object: models.RawObject
    batch: models.IngestBatch
    trace_id: str | None
