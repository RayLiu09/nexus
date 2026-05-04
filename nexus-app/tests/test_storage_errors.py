import pytest
from botocore.exceptions import ClientError

from nexus_app.storage import InMemoryObjectStorage, ObjectNotFoundError, S3ObjectStorage


def test_in_memory_storage_normalizes_missing_object():
    storage = InMemoryObjectStorage()

    with pytest.raises(ObjectNotFoundError):
        storage.get_bytes("missing/key.json")


def test_s3_storage_treats_aws_no_such_key_as_not_found():
    exc = ClientError(
        {
            "Error": {"Code": "NoSuchKey", "Message": "The specified key does not exist."},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        "GetObject",
    )

    assert S3ObjectStorage._is_not_found_error(exc)


def test_s3_storage_treats_minio_not_found_status_as_not_found():
    exc = ClientError(
        {
            "Error": {"Code": "NotFound", "Message": "Object does not exist"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        "GetObject",
    )

    assert S3ObjectStorage._is_not_found_error(exc)


def test_s3_storage_treats_minio_no_such_object_as_not_found():
    exc = ClientError(
        {
            "Error": {"Code": "NoSuchObject", "Message": "Object does not exist"},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        "GetObject",
    )

    assert S3ObjectStorage._is_not_found_error(exc)


def test_s3_storage_does_not_hide_permission_errors_as_not_found():
    exc = ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": "Access denied"},
            "ResponseMetadata": {"HTTPStatusCode": 403},
        },
        "GetObject",
    )

    assert not S3ObjectStorage._is_not_found_error(exc)


def test_s3_storage_does_not_hide_missing_bucket_as_object_not_found():
    exc = ClientError(
        {
            "Error": {"Code": "NoSuchBucket", "Message": "The specified bucket does not exist."},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        "GetObject",
    )

    assert not S3ObjectStorage._is_not_found_error(exc)
