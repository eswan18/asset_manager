import os
import re
from unittest.mock import patch

import pytest
import pandas as pd

from asset_manager import fetch
from asset_manager.fetch import get_service, save_df


@pytest.mark.skipif(os.getenv("CI") is not None, reason="no Google credentials")
def test_get_service_runs_without_error():
    _ = get_service()


def test_save_df():
    name = "abc.csv"
    df = pd.DataFrame([(1, 2)], columns=("a", "b"))
    expected_text = "a,b\n1,2\n"

    # Try with an explicitly-specified object name.
    with patch.object(fetch, "write_string_to_object") as writer:
        save_df(df, name=name)
        writer.assert_called_once_with(object_name=name, text=expected_text)

    # Try again but with the writer inferring the object name.
    with patch.object(fetch, "write_string_to_object") as writer:
        save_df(df)
        writer.assert_called_once()
        # We have to inspect the arguments ourselves without mock machinery since we're
        # expecting a pattern.
        args, kwargs = writer.call_args
        assert kwargs["text"] == expected_text or args[1] == expected_text

        object_name_arg = kwargs["object_name"] if "object_name" in kwargs else args[0]
        match = re.match(r"summaries_\d{4}_\d{2}_\d{2}.csv", object_name_arg)
        assert match is not None
