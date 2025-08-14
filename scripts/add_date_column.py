"""
Hacked this together to go back and "fix" old objects in S3 that don't have a date
column and are identifiable only by the name of the S3 object.

It also fixes a few cases where there's a "Unnamed: 0" column by dropping it.
"""

from asset_manager.s3 import write_string_to_object
from asset_manager.datastore import (
    _daily_object_names,
    _read_df,
    DAILY_SUMMARY_NAME_REGEX,
)

BUCKET_NAME = "ethanpswan-finances"

print("Pulling object names...")
for name in _daily_object_names():
    df = _read_df(name)
    if "Date" in df.columns:
        print(f"Skipping {name} because it already has a date column")
        continue
    match = DAILY_SUMMARY_NAME_REGEX.match(name)
    if match is None:
        raise Exception(name)
    date = match.groups()[0]
    df["Date"] = date.replace("_", "-")

    if "Unnamed: 0" in df.columns:
        df = df.drop("Unnamed: 0", axis="columns")

    print("Updated DataFrame:")
    updated_df_string = df.to_csv(index=False)
    print(df.to_string())
    yn = input(f'Update object "{name}"? [y/n] ')
    if yn.lower()[0] != "y":
        print("That's not a yes. Moving on.")
        continue
    print("Updating...")
    write_string_to_object(object_name=name, text=updated_df_string)

print("Done")
