# Asset Manager

[![CI Status](https://github.com/eswan18/asset_manager/workflows/Continuous%20Integration/badge.svg)](https://github.com/eswan18/asset_manager/actions)
[![codecov](https://codecov.io/gh/eswan18/asset_manager/branch/main/graph/badge.svg?token=JI0605RMSO)](https://codecov.io/gh/eswan18/asset_manager)


## Setup

Using Poetry is simplest. Install Poetry, then:
```bash
poetry install
```

## Things you can do

Pull finances from Google Sheets and store a record for that day in S3:
```
poetry run python -m asset_manager.fetch
```

View finances over time in a notebook:
- Open `Charts.ipynb` and run it

Consolidate a year's worth of daily file into a single file:
```
poetry run python scripts/consolidate_by_year.py <year>
```
