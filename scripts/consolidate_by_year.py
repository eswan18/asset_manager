"""
This script takes a year as input, finds all daily files for that year, and groups them
into a single file. If a year file already exists, it will append rather than overwrite,
but honestly there's no need to run it before the year is over.

This is just helpful for performance because otherwise reads from S3 take a long time
(there are a lot of day-level objects).
"""

import sys

import pandas as pd

from asset_manager.s3 import write_string_to_object
from asset_manager.datastore import _daily_object_names, _yearly_object_names, DAILY_SUMMARY_NAME_REGEX, YEARLY_SUMMARY_NAME_REGEX, _read_df

if len(sys.argv) != 2:
    raise Exception('Usage: python consolidate_by_year.py <year>')

year = sys.argv[1]
if len(year) != 4 or not year.isnumeric():
    raise Exception('Invalid year specified')

to_consolidate: list[pd.DataFrame] = []

# Start by seeing if there is a year summary file already
existing_object = None
for yearly_object_name in _yearly_object_names():
    match = YEARLY_SUMMARY_NAME_REGEX.match(yearly_object_name)
    found_year = match.groups()[0]
    if found_year == year:
        existing_object = yearly_object_name
        break
if existing_object is not None:
    print(f"Found existing object for year {year}: '{existing_object}. Will append to it.")
    existing_df = _read_df(existing_object)
    to_consolidate.append(existing_df)
else:
    print(f"No existing summary object for year {year} found; will create a new one.")

# Find all daily files for the given year
consolidated_objects: list[str] = []
for daily_object_name in _daily_object_names():
    match = DAILY_SUMMARY_NAME_REGEX.match(daily_object_name)
    found_date = match.groups()[0]
    found_year = found_date[:4]
    if found_year == year:
        print(f"Found object '{daily_object_name}'; adding its contents to yearly DataFrame")
        df = _read_df(daily_object_name)
        to_consolidate.append(df)
        consolidated_objects.append(daily_object_name)
    
# Build consolidated DataFrame.
final_df = pd.concat(to_consolidate)
final_df = final_df.reset_index(drop=True)

# Confirm with user.
print(f"Resulting DataFrame of shape {final_df.shape}")
print(final_df.to_string())
result_object = f"summaries_{year}.csv"
yn = input(f"Write this to {result_object}? [y/n] ")
if yn.lower()[0] != 'y':
    print("That's not a yes")
    sys.exit()

# Write result.
print("Writing new object...")
final_df_string = final_df.to_csv(index=False)
write_string_to_object(object_name=result_object, text=final_df_string)
print("Done")

print("I haven't actually bothered with automating the deletion of the consolidated objects, sorry. Here are their names:")
print(consolidated_objects)
print("I'll print some commands for you to throw in a script and run with bash...")
for obj in consolidated_objects:
    print(f"    aws s3 rm s3://ethanpswan-finances/{obj}")