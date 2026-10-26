"""The retired Pipeline B writer cannot mutate historical domain records."""
import pytest
from sqlalchemy import select
from nexus_app import models
from nexus_app.domain_normalize.major_distribution_writer import write


def test_legacy_writer_is_rejected_without_side_effects(session):
    with pytest.raises(ValueError, match="retired"):
        write(session=session, normalized_ref=None, record_body={"dataset": {}, "records": []})
    assert list(session.scalars(select(models.MajorDistributionRecord))) == []
    assert list(session.scalars(select(models.MajorDistributionDataset))) == []
