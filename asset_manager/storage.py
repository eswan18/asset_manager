from configparser import ConfigParser
import base64

import boto3
from botocore.exceptions import ClientError

CONFIG_FILE = 'config.ini'
config = ConfigParser()
config.read(CONFIG_FILE)
conf = config['DEFAULT']

s3 = boto3.resource(
        service_name='s3',
        aws_access_key_id=conf['S3_ACCESS_KEY_ID'],
        aws_secret_access_key=conf['S3_SECRET_ACCESS_KEY']
)

def write_string_to_object(object_name, string):
    bucket = s3.Bucket(conf['S3_BUCKET'])
    bucket.put_object(Key=object_name, Body=string)


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
