from __future__ import annotations

from configparser import ConfigParser
from io import BytesIO
from typing import Any, Optional, Union, List, TYPE_CHECKING
import pkg_resources

import boto3
from botocore.exceptions import NoCredentialsError


if TYPE_CHECKING:
    from mypy_boto3_s3.service_resource import S3ServiceResource, Bucket

    BucketLikeType = Union[str, Bucket]


config_contents = pkg_resources.resource_string(__name__, "data/config.ini")
config = ConfigParser()
config.read_string(config_contents.decode())
conf = config["DEFAULT"]


def _s3() -> S3ServiceResource:
    s3 = boto3.resource(service_name="s3")
    return s3


def _default_bucket() -> Bucket:
    return _s3().Bucket(conf["S3_BUCKET"])


def _bucket_from_argument(bucket: Optional[BucketLikeType]) -> Bucket:
    if bucket is None:
        return _default_bucket()
    if isinstance(bucket, str):
        return _s3().Bucket(bucket)
    else:  # Assume it's a bucket object already.
        return bucket


def read_string_from_object(
    object_name: str, bucket: Optional[BucketLikeType] = None
) -> str:
    """
    Get the contents of an object as a string.

    Parameters
    ----------
    object_name:
        Name of the object in the bucket.
    bucket:
        An S3 bucket object. Defaults to the bucket in the configuration file.

    Returns
    -------
    string:
        The string read from the object.
    """
    bucket = _bucket_from_argument(bucket)
    b = BytesIO()
    try:
        bucket.download_fileobj(Key=object_name, Fileobj=b)
    except NoCredentialsError as exc:
        raise Exception("No s3 credentials, you may need to sign in") from exc
    # Must return to the beginning of the file before reading.
    b.seek(0)
    result_bytes = b.read()
    result_str = result_bytes.decode()
    return result_str


def list_objects_in_bucket(bucket: Any = None) -> List[str]:
    """
    Get the names of all objects in a bucket.

    Parameters
    ----------
    bucket:
        An S3 bucket object. Defaults to the bucket in the configuration file.
    """
    bucket = _bucket_from_argument(bucket)
    try:
        objects = [o.key for o in bucket.objects.all()]
    except NoCredentialsError as exc:
        raise Exception("No s3 credentials, you may need to sign in") from exc
    return objects
