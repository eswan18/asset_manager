import re

import pandas as pd


def drop_blank_rows(df: pd.DataFrame) -> pd.DataFrame:
    bad_rows = df.isnull().sum(axis=1) == df.shape[1]
    # Another heuristic: Description should never be blank.
    bad_rows |= df["Description"].str.len() == 0
    return df.loc[~bad_rows]


def convert_dollar_cols_to_float(df: pd.DataFrame) -> pd.DataFrame:
    """
    Find string cols in a DF that contain dollar amounts and convert them to float types
    """

    def dollars_to_float(dollar_str):
        pattern = r"\d+(,\d{3})*(.\d\d)?"
        matches = re.search(pattern, dollar_str)
        if matches is not None:
            as_float = float(matches[0].replace(",", ""))
            return as_float
        elif "$ -" in dollar_str:
            return 0
        else:
            raise ValueError(f"can't parse '{dollar_str}'")

    df2 = df.copy()
    for col in df:
        if all(df[col].str.contains("$", regex=False)):
            df2[col] = df[col].apply(dollars_to_float)
    return df2
