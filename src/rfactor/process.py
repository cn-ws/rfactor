import re
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm


def _days_since_start_year(series):
    """Translate datetime series to days since start of the year

    Parameters
    ----------
    series : pd.Series
        Series with Datetime values. All datetime values should be of the same year.

    Returns
    -------
    days_since_start : pd.Series
        Days since the start of the year as a float value.

    Notes
    -----
    Support function to provide integration with original Matlab implementation. Output
    is different from Pandas datetime attribute `dayofyear` as it includes time of the
    day as decimal value.
    """
    current_year = series.dt.year.unique()
    if not len(current_year) == 1:
        raise Exception("Input data should all be in the same year.")

    days_since_start = (
        (series - pd.Timestamp(f"{current_year[0]}-01-01")).dt.total_seconds()
        / 60.0
        / 1440.0
    )
    return days_since_start


def _extract_metadata_from_file_path(file_path):
    """Get metadata from file name

    Expects to be 'STATION_NAME_YYYY.txt' as format with ``STATION_NAME`` the
    measurement station and the ``YYYY`` as the year of the measurement.

    Parameters
    ----------
    file_path : pathlib.Path
        File path of the file to extract station/year from

    Returns
    -------
    station: str
    year : str
    """
    if not re.fullmatch(".*_[0-9]{4}$", file_path.stem):
        raise ValueError(
            "Input file_path_format should " "match with 'STATION_NAME_YYYY.txt'"
        )
    station = "_".join(file_path.stem.split("_")[:-1])
    year = file_path.stem.split("_")[-1]
    return station, year


def _check_path(file_path):
    """Provide user feedback on file_path type."""
    if not isinstance(file_path, Path):
        if isinstance(file_path, str):
            raise TypeError(
                f"`file_path` should be a `pathlib.Path` object, use "
                f"`Path({file_path})` to convert string file_path to valid `Path`."
            )
        else:
            raise TypeError(f"`file_path` should be a pathlib.Path object")


def load_rain_file(file_path):
    """Load (legacy Matlab) file format of rainfall data of a single station/year

    The input files are defined by text files (extension: ``.txt``) that hold
    non-zero rainfall timeseries. The data are split per station and per year with
    a specific datafile tag (file name format: ``SOURCE_STATION_YEAR.txt``). The data
    should not contain headers, with a first column with minutes since the start of the
    year and a second with the rainfall intensity.

    Parameters
    ----------
    file_path : pathlib.Path
        File path with rainfall data according to defined format.

    Returns
    -------
    rain : pd.DataFrame
        DataFrame with rainfall time series. Contains the following columns:

        - *minutes_since* (int): Minutes since the start of the year
        - *rain_mm* (float): Rain in mm
        - *datetime* (pd.Timestamp): Time stamp
        - *station* (str): station name
        - *year* (int): year of the measurement
        - *tag* (str): tag identifier, formatted as 'STATION-NAME_YEAR'
    """
    _check_path(file_path)

    station, year = _extract_metadata_from_file_path(file_path)
    rain = pd.read_csv(
        file_path, delimiter=" ", header=None, names=["minutes_since", "rain_mm"]
    )
    rain["datetime"] = pd.Timestamp(f"{year}-01-01") + pd.to_timedelta(
        rain["minutes_since"], unit="min"
    )
    rain["station"] = station
    rain["year"] = rain["datetime"].dt.year
    rain["tag"] = rain["station"].astype(str) + "_" + rain["year"].astype(str)
    return rain


def load_rain_folder(folder_path):
    """Load all (legacy Matlab format) files of rainfall data in a folder

    Parameters
    ----------
    folder_path : pathlib.Path
        Folder path with rainfall data according to legacy Matlab format,
        see :func:`rfactor.process.load_rain_file`.

    Returns
    -------
    rain : pd.DataFrame
        DataFrame with rainfall time series. Contains the following columns:

        - *minutes_since* (int): Minutes since the start of the year
        - *rain_mm* (float): Rain in mm
        - *datetime* (pd.Timestamp): Time stamp
        - *station* (str): station name
        - *year* (int): year of the measurement
        - *tag* (str): tag identifier, formatted as 'STATION-NAME_YEAR'
    """
    _check_path(folder_path)

    lst_df = []

    files = list(folder_path.glob("*.txt"))
    for file_path in tqdm(files, total=len(files)):
        lst_df.append(load_rain_file(file_path))

    all_rain = pd.concat(lst_df)
    all_rain = all_rain.sort_values(["station", "minutes_since"])
    all_rain.index = range(len(all_rain))
    return all_rain


def write_erosivity_data(df, folder_path):
    """Write output erosivity to (legacy Matlab format) in folder

    Written data is split up for each year and station
    (file name format: SOURCE_STATION_YEAR.txt) and does not contain any headers. The
    columns in the written text files represent the following:

    - *days_since* (float): Days since the start of the year
    - *erosivity_cum* (float): Cumulative erosivity over events
    - *all_event_rain_cum* (float): Cumulative rain over events

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with rfactor/erosivity time series. Can contain multiple columns,
        but should have at least the following:

        - *datetime* (pd.Timestamp): Time stamp
        - *station* (str): Station identifier
        - *erosivity_cum* (float): Cumulative erosivity over events
        - *all_event_rain_cum* (float): Cumulative rain over events

    folder_path : pathlib.Path
        Folder path to save data according to legacy Matlab format,
        see :func:`rfactor.process.load_rain_file`.

    """
    _check_path(folder_path)

    folder_path.mkdir(exist_ok=True, parents=True)

    for (station, year), df_group in df.groupby(["station", df["datetime"].dt.year]):
        df_group["days_since"] = _days_since_start_year(df_group["datetime"])
        formats = {
            "days_since": "{:.3f}",
            "erosivity_cum": "{:.2f}",
            "all_event_rain_cum": "{:.1f}",
        }
        for column, fformat in formats.items():
            df_group[column] = df_group[column].map(lambda x: fformat.format(x))
        df_group[["days_since", "erosivity_cum", "all_event_rain_cum"]].to_csv(
            folder_path / f"{station}_{year}.csv", header=None, index=None, sep=" "
        )


def get_rfactor_station_year(erosivity, stations=None, years=None):
    """Get R-factor at end of every year for each location from cumulative erosivity
    data.

    Parameters
    ----------
    erosivity: pandas.DataFrame
        See :func:`rfactor.rfactor._compute_erosivity`
    stations: list
        List of stations to extract R for
    years: list
        List of years to extract R for

    Returns
    -------
    pandas.DataFrame

        - *year* (int): year
        - *station* (str): station
        - *erosivity_cum* (float): cumulative erosivity at end of *year* and at location
        *station*.

    """

    if stations is not None:
        erosivity = erosivity.loc[erosivity["station"].isin(stations)]
    if years is not None:
        erosivity = erosivity.loc[erosivity["year"].isin(years)]

    erosivity = erosivity.groupby(["year", "station"]).aggregate("erosivity_cum").last()
    return erosivity.reset_index()


def compute_rainfall_statistics(df_rainfall, df_station_metadata=None):
    """Compute general statistics for rainfall timeseries

    Statistics (number of records, min, max, median and years data) are
    computed for each measurement station

    Parameters
    ----------
    df_rainfall: pandas.DataFrame
        See :func:`rfactor.process.load_rain_file`
    df_station_metadata: pandas.DataFrame
        Dataframe holding station metadata. This dataframe has one mandatory
        column:

        - *station* (str): Name or code of the measurement station
        - *x* (float): X-coordinate of station
        - *y* (float): Y-coordinate

    Returns
    -------
    df_statistics: pandas.DataFrame

    """
    df_rainfall = df_rainfall.sort_values(by="year")
    df_statistics = (
        df_rainfall[["year", "station", "rain_mm"]]
        .groupby("station")
        .aggregate(
            {
                "year": lambda x: sorted(set(x)),
                "rain_mm": [np.min, np.max, np.median, lambda x: np.shape(x)[0]],
            }
        )
    ).reset_index()
    df_statistics.columns = df_statistics.columns.map("".join)
    rename_cols = {
        "year<lambda>": "year",
        "rain_mmamin": "min",
        "rain_mmamax": "max",
        "rain_mmmedian": "median",
        "rain_mm<lambda_0>": "records",
    }
    df_statistics = df_statistics.rename(columns=rename_cols)

    if df_station_metadata is not None:
        df_statistics = df_statistics.merge(
            df_station_metadata, on="station", how="left"
        )
        df_statistics = df_statistics[
            [
                "year",
                "location",
                "x",
                "y",
                "records",
                "min",
                "median",
                "max",
            ]
        ]
    else:
        df_statistics = df_statistics[
            ["year", "records", "min", "median", "max"]
        ].reset_index()

    return df_statistics
