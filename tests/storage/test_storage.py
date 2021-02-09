from unittest.mock import MagicMock, patch
from typing import Union
from contextlib import ExitStack

# from _pytest.monkeypatch import MonkeyPatch
from hypothesis import given, example, strategies as st

from asset_manager import storage


S3_NAME_REGEX = r'[a-z0-9]([a-z0-9]|[-.]){1,61}[a-z0-9]'


@given(
    key_id=st.text(max_size=50),
    access_key=st.text(max_size=150)
)
@example(
    key_id='abc',
    access_key='def'
)
def test_s3_service_builder(key_id, access_key):
    secret = {'S3_ACCESS_KEY_ID': key_id,
              'S3_SECRET_ACCESS_KEY': access_key}
    # This (oddly) is the nicest way to do multiple context managers before Python 3.9.
    with ExitStack() as es:
        es.enter_context(patch.object(storage, 'get_secret', return_value=secret))
        es.enter_context(patch.object(storage.boto3, 'resource', return_value='result'))
        # Relevant function call.
        s3 = storage._s3()
        # Assertions.
        storage.boto3.resource.assert_called_with(
            service_name='s3',
            aws_access_key_id=key_id,
            aws_secret_access_key=access_key
        )
        assert s3 == 'result'


@given(
    obj_name=st.from_regex(S3_NAME_REGEX),
    text=st.one_of(st.text(), st.binary())
)
def test_write_string_to_object(obj_name: str, text: Union[str, bytes]):
    # Build some mocks.
    mock_s3_service = MagicMock(spec=['Bucket'])
    mock_bucket = MagicMock(spec=['put_object'])
    mock_s3_service.Bucket.return_value = mock_bucket
    # Patch them in.
    with patch.object(storage, '_s3', return_value=mock_s3_service):
        # Relevant function call.
        storage.write_string_to_object(object_name=obj_name, text=text)
        # Assertions.
        mock_s3_service.Bucket.assert_called_with(storage.conf['S3_BUCKET'])
        text_as_bytes = text.encode() if isinstance(text, str) else text
        mock_bucket.put_object.assert_called_with(Key=obj_name, Body=text_as_bytes)
