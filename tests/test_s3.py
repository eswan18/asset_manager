from unittest.mock import MagicMock, patch
from typing import Union

from hypothesis import given, strategies as st

from asset_manager import s3


S3_NAME_REGEX = r"[a-z0-9]([a-z0-9]|[-.]){1,61}[a-z0-9]"


def test_s3_service_builder():
    with patch.object(s3.boto3, "resource", return_value="result"):
        # Relevant function call.
        s3_instance = s3._s3()
        # Assertions.
        s3.boto3.resource.assert_called_with(service_name="s3")
        assert s3_instance == "result"


@given(obj_name=st.from_regex(S3_NAME_REGEX), text=st.one_of(st.text(), st.binary()))
def test_write_string_to_object(obj_name: str, text: Union[str, bytes]):
    # Build some mocks.
    mock_s3_service = MagicMock(spec=["Bucket"])
    mock_bucket = MagicMock(spec=["put_object"])
    mock_s3_service.Bucket.return_value = mock_bucket
    # Patch them in.
    with patch.object(s3, "_s3", return_value=mock_s3_service):
        # Relevant function call.
        s3.write_string_to_object(object_name=obj_name, text=text)
        # Assertions.
        mock_s3_service.Bucket.assert_called_with(s3.conf["S3_BUCKET"])
        text_as_bytes = text.encode() if isinstance(text, str) else text
        mock_bucket.put_object.assert_called_with(Key=obj_name, Body=text_as_bytes)
