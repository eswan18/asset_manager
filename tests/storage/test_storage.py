from unittest.mock import MagicMock, patch
from typing import Union

from hypothesis import given, strategies as st

from asset_manager import storage


S3_NAME_REGEX = r'[a-z0-9]([a-z0-9]|[-.]){1,61}[a-z0-9]'


@given(
    obj_name=st.from_regex(S3_NAME_REGEX),
    text=st.one_of(st.text(), st.binary())
)
def test_write_string_to_object(obj_name: str, text: Union[str, bytes]):
    mock_bucket = MagicMock(spec=['put_object'])
    with patch.object(storage._s3, 'Bucket', return_value=mock_bucket):
        storage.write_string_to_object(object_name=obj_name, text=text)
        storage._s3.Bucket.assert_called_with(storage.conf['S3_BUCKET'])
        text_as_bytes = text.encode() if isinstance(text, str) else text
        mock_bucket.put_object.assert_called_with(Key=obj_name, Body=text_as_bytes)
