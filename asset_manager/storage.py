from configparser import ConfigParser
from io import BytesIO
import base64
import json
from typing import (
    Any, Optional, Union, List, Dict, Literal, overload, TYPE_CHECKING
)
import pkg_resources

import boto3


if TYPE_CHECKING:
    from mypy_boto3_s3.service_resource import S3ServiceResource, Bucket
BucketLikeType = Union[str, Bucket]


config_contents = pkg_resources.resource_string(__name__, "data/config.ini")
config = ConfigParser()
config.read_string(config_contents.decode())
conf = config['DEFAULT']


def _s3() -> 'S3ServiceResource':
    s3 = boto3.resource(service_name='s3')
    return s3


def _default_bucket() -> Bucket:
    return _s3().Bucket(conf['S3_BUCKET'])


def _bucket_from_argument(
    bucket: Optional[BucketLikeType]
) -> Bucket:
    if bucket is None:
        return _default_bucket()
    if isinstance(bucket, str):
        return _s3().Bucket(bucket)
    else:  # Assume it's a bucket object already.
        return bucket


def write_string_to_object(
    object_name: str,
    text: Union[str, bytes],
    bucket: Optional[BucketLikeType] = None
) -> None:
    '''
    Write a string into an object in S3.
    '''
    bucket = _bucket_from_argument(bucket)
    if isinstance(text, str):
        text = text.encode()
    bucket = _s3().Bucket(conf['S3_BUCKET'])
    _default_bucket()
    bucket.put_object(Key=object_name, Body=text)


def read_string_from_object(
    object_name: str,
    bucket: Optional[BucketLikeType] = None
) -> str:
    '''
    sdf

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
    '''
    bucket = _bucket_from_argument(bucket)
    b = BytesIO()
    bucket.download_fileobj(Key=object_name, Fileobj=b)
    # Must return to the beginning of the file before reading.
    b.seek(0)
    result_bytes = b.read()
    result_str = result_bytes.decode()
    return result_str


def list_objects_in_bucket(
    bucket: Any = None
) -> List[str]:
    '''
    Get the names of all objects in a bucket.

    Parameters
    ----------
    bucket:
        An S3 bucket object. Defaults to the bucket in the configuration file.
    '''
    bucket = _bucket_from_argument(bucket)
    objects = [o.key for o in bucket.objects.all()]
    return objects


@overload
def get_secret(
    secret_name: str,
    assume_json: Literal[True] = True
) -> Dict[str, str]: ...


@overload
def get_secret(
    secret_name: str,
    assume_json: Literal[False]
) -> Union[str, bytes]: ...


def get_secret(secret_name: str, assume_json: bool = True):
    '''
    Fetch a secret from AWS Secrets Manager.

    Optionally convert it to a JSON object

    Parameters
    ----------
    secret_name
        The name of the secret
    assume_json
        Whether to treat the secret as a simple JSON dictionary of {str: str} and return
        a decoded object from it.

    Returns
    -------
    secret
        The fetched secret
    '''
    secret_name = "asset-manager-s3"
    region_name = "us-east-2"
    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    # See https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html  # noqa: E501
    get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    # Decrypt secret using the associated KMS CMK. Depending on whether the secret is
    # a string or binary, one of these fields will be populated.
    if 'SecretString' in get_secret_value_response:
        secret = get_secret_value_response['SecretString']
    else:
        secret = base64.b64decode(
                get_secret_value_response['SecretBinary']
        )
    if assume_json:
        return json.loads(secret)
    else:
        return secret
