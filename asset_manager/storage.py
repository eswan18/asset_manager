from configparser import ConfigParser
from io import BytesIO
import base64
import json
from typing import Any, Union, List, Dict, Literal, cast, overload

import boto3

from .custom_types import JSON

CONFIG_FILE = 'config.ini'
config = ConfigParser()
config.read(CONFIG_FILE)
conf = config['DEFAULT']


def _s3() -> Any:
    s3_secret = get_secret(conf['S3_SECRET_NAME'])
    s3_secret = cast(Dict[str, str], s3_secret)
    s3 = boto3.resource(
        service_name='s3',
        aws_access_key_id=s3_secret['S3_ACCESS_KEY_ID'],
        aws_secret_access_key=s3_secret['S3_SECRET_ACCESS_KEY']
    )
    return s3


def write_string_to_object(
    object_name: str,
    text: Union[str, bytes]
) -> None:
    if isinstance(text, str):
        text = text.encode()
    bucket = _s3().Bucket(conf['S3_BUCKET'])
    bucket.put_object(Key=object_name, Body=text)


def read_string_from_object(
    object_name: str
) -> str:
    bucket = _s3().Bucket(conf['S3_BUCKET'])
    b = BytesIO()
    bucket.download_fileobj(Key=object_name, Fileobj=b)
    # Must return to the beginning of the file before reading.
    b.seek(0)
    result_bytes = b.read()
    result_str = result_bytes.decode()
    return result_str


def list_objects_in_bucket() -> List[str]:
    bucket = _s3().Bucket(conf['S3_BUCKET'])
    objects = [o.key for o in bucket.objects.all()]
    return objects


@overload
def get_secret(secret_name: str, assume_json: Literal[True] = True) -> JSON: ...


@overload
def get_secret(secret_name: str, assume_json: Literal[False]) -> Union[str, bytes]: ...


def get_secret(secret_name: str, assume_json: bool = True):
    '''
    Fetch a secret from AWS Secrets Manager.

    Optionally convert it to a JSON object

    Parameters
    ----------
    secret_name
        The name of the secret
    assume_json
        Whether to treat the secret as JSON and return a decoded object from it.

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
