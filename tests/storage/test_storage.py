from unittest.mock import Mock, MagicMock, patch, create_autospec

from hypothesis import given, strategies as st

from asset_manager import storage

# from mocks import MockBucket

s3_name_regex = r'[a-z0-9]([a-z0-9]|[-.]){1,61}[a-z0-9]'

@given(obj=st.from_regex(s3_name_regex), text=st.text())
def test_write_string_to_object(text, obj):
    mock_bucket = MagicMock(spec=['put_object'])
    with patch.object(storage._s3, 'Bucket', return_value=mock_bucket) as mock_method:
        storage.write_string_to_object(object_name=obj, string=text)
        storage._s3.Bucket.assert_called_with(storage.conf['S3_BUCKET'])
        mock_bucket.put_object.assert_called_with(Key=obj, Body=text)
