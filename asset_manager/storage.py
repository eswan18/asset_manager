from configparser import ConfigParser
from io import BytesIO
import base64
from typing import Union, List

import boto3
from botocore.exceptions import ClientError

CONFIG_FILE = 'config.ini'
config = ConfigParser()
config.read(CONFIG_FILE)
conf = config['DEFAULT']

_s3 = boto3.resource(
        service_name='s3',
        aws_access_key_id=conf['S3_ACCESS_KEY_ID'],
        aws_secret_access_key=conf['S3_SECRET_ACCESS_KEY']
)

def write_string_to_object(
    object_name: str,
    text: Union[str, bytes]
) -> None:
    if isinstance(text, str):
        text = text.encode()
    bucket = _s3.Bucket(conf['S3_BUCKET'])
    bucket.put_object(Key=object_name, Body=text)


def read_string_from_object(
    object_name: str
) -> str:
    bucket = _s3.Bucket(conf['S3_BUCKET'])
    b = BytesIO()
    bucket.download_fileobj(Key=object_name, Fileobj=b)
    # Must return to the beginning of the file before reading.
    b.seek(0)
    result_bytes = b.read()
    result_str = result_bytes.decode()
    return result_str


def list_objects_in_bucket() -> List[str]:
    bucket = _s3.Bucket(conf['S3_BUCKET'])
    objects = [o.key for o in bucket.objects.all()]
    return objects


def get_secret():
    secret_name = "asset-manager-s3"
    region_name = "us-east-2"
    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    # See https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
    get_secret_value_response = client.get_secret_value(
        SecretId=secret_name
    )
    # Decrypts secret using the associated KMS CMK.
    # Depending on whether the secret is a string or binary, one of these fields will be populated.
    if 'SecretString' in get_secret_value_response:
        secret = get_secret_value_response['SecretString']
    else:
        secret = base64.b64decode(
                get_secret_value_response['SecretBinary']
        )
    return secret
