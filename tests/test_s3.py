from unittest.mock import patch

from asset_manager import s3


def test_s3_service_builder():
    with patch.object(s3.boto3, "resource", return_value="result"):
        # Relevant function call.
        s3_instance = s3._s3()
        # Assertions.
        s3.boto3.resource.assert_called_with(service_name="s3")
        assert s3_instance == "result"
