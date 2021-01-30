from configparser import ConfigParser

import boto3

config = ConfigParser()
config.read('config.ini')
conf = config['DEFAULT']

s3 = boto3.resource(
        service_name='s3',
        aws_access_key_id=conf['S3_ACCESS_KEY_ID'],
        aws_secret_access_key=conf['S3_SECRET_ACCESS_KEY']
)

def write_string_to_object(object_name, string):
    bucket = s3.Bucket(conf['S3_BUCKET'])
    bucket.put_object(Key=object_name, Body=string)
