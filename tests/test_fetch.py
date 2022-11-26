import pandas as pd
from pandas.testing import assert_series_equal

from asset_manager.fetch import setup_service, convert_dollar_cols_to_float


def test_setup_service_runs_without_error():
    _ = setup_service()


def test_convert_dollar_cols_to_float():
    test_df = pd.DataFrame({
        "somedollars": ["$123", "$456"],
        "notdollars": ["123", "456"],
        "alsodollars": ["$ -", "$55,555.55"],
        "definitelynotdollars": ["abc", "def"],
    })
    result_df = convert_dollar_cols_to_float(test_df)
    # Make sure we returned a new DF and didn't just mutate the original.
    assert result_df is not test_df
    # Non-dollar columns should be unchanged.
    assert_series_equal(test_df["notdollars"], result_df["notdollars"])
    assert_series_equal(test_df["definitelynotdollars"], result_df["definitelynotdollars"])
    # Dollary-columns should now be floats.
    assert result_df["somedollars"].dtype == float
    assert result_df["alsodollars"].dtype == float
    # Check their values.
    expected_some_dollars = pd.Series([123, 456], dtype=float)
    assert_series_equal(expected_some_dollars, result_df["somedollars"], check_names=False)
    expected_also_dollars = pd.Series([0, 55_555.55], dtype=float)
    assert_series_equal(expected_also_dollars, result_df["alsodollars"], check_names=False)