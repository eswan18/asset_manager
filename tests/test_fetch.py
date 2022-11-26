import os

import pytest

from asset_manager.fetch import setup_service


@pytest.mark.skipif(os.getenv("CI") is not None, reason="no Google credentials")
def test_setup_service_runs_without_error():
    _ = setup_service()
