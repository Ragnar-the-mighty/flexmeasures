from typing import List, Optional, Tuple, Union
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
import timely_beliefs as tb

from sqlalchemy.orm import Query, Session

from bvp.data.config import db
from bvp.data.models.data_sources import DataSource
from bvp.utils import bvp_inflection


def create_beliefs_query(
    cls,
    session: Session,
    asset_class: db.Model,
    asset_name: str,
    start: Optional[datetime],
    end: Optional[datetime],
) -> Query:
    query = (
        session.query(cls.datetime, cls.value, cls.horizon, DataSource)
        .join(DataSource)
        .filter(cls.data_source_id == DataSource.id)
        .join(asset_class)
        .filter(asset_class.name == asset_name)
    )
    if start is not None:
        query = query.filter((cls.datetime > start - asset_class.event_resolution))
    if end is not None:
        query = query.filter((cls.datetime < end))
    return query


def add_user_source_filter(
    cls, query: Query, user_source_ids: Union[int, List[int]]
) -> Query:
    """Add filter to the query to search only through user data from the specified user sources.

    We distinguish user sources (sources with source.type == "user") from other sources (source.type != "user").
    Data with a user source originates from a registered user. Data with e.g. a script source originates from a script.

    This filter doesn't affect the query over non-user type sources.
    It does so by ignoring user sources that are not in the given list of source_ids.
    """
    if user_source_ids is not None and not isinstance(user_source_ids, list):
        user_source_ids = [user_source_ids]  # ensure user_source_ids is a list
    if user_source_ids:
        ignorable_user_sources = (
            DataSource.query.filter(DataSource.type == "user")
            .filter(DataSource.id.notin_(user_source_ids))
            .all()
        )
        ignorable_user_source_ids = [
            user_source.id for user_source in ignorable_user_sources
        ]
        query = query.filter(cls.data_source_id.notin_(ignorable_user_source_ids))
    return query


def add_source_type_filter(cls, query: Query, source_types: List[str]) -> Query:
    """Add filter to the query to collect only data from sources that are of the given type."""
    return query.filter(DataSource.type.in_(source_types)) if source_types else query


def add_horizon_filter(
    cls,
    query: Query,
    end: Optional[datetime],
    asset_class: db.Model,
    horizon_window: Tuple[Optional[timedelta], Optional[timedelta]],
    rolling: bool,
    belief_time: Optional[datetime],
) -> Query:
    if belief_time is not None:
        query = query.filter(
            cls.datetime + asset_class.event_resolution - cls.horizon <= belief_time
        )
    short_horizon, long_horizon = horizon_window
    if (
        short_horizon is not None
        and long_horizon is not None
        and short_horizon == long_horizon
    ):  # search directly for a unique belief_horizon (rolling=True) or belief_time (rolling=False)
        if rolling:
            query = query.filter(cls.horizon == short_horizon)
        else:  # Deduct the difference in end times of the timeslot and the query window
            query = query.filter(
                cls.horizon
                == short_horizon - (end - (cls.datetime + asset_class.event_resolution))
            )
    else:
        if short_horizon is not None:
            if rolling:
                query = query.filter(cls.horizon >= short_horizon)
            else:
                query = query.filter(
                    cls.horizon
                    >= short_horizon
                    - (end - (cls.datetime + asset_class.event_resolution))
                )
        if long_horizon is not None:
            if rolling:
                query = query.filter(cls.horizon <= long_horizon)
            else:
                query = query.filter(
                    cls.horizon
                    <= long_horizon
                    - (end - (cls.datetime + asset_class.event_resolution))
                )
    return query


def read_sqlalchemy_results(session: Session, statement: str) -> List[dict]:
    """Executes a read query and returns a list of dicts, whose keys are column names."""
    data = session.execute(statement).fetchall()
    results: List[dict] = []

    if len(data) == 0:
        return results

    # results from SQLAlchemy are returned as a list of tuples; this procedure converts it into a list of dicts
    for row_number, row in enumerate(data):
        results.append({})
        for column_number, value in enumerate(row):
            results[row_number][row.keys()[column_number]] = value

    return results


def simplify_index(
    bdf: tb.BeliefsDataFrame, index_levels_to_columns: Optional[List[str]] = None
) -> pd.DataFrame:
    """Drops indices other than event_start.
    Optionally, salvage index levels as new columns.

    Because information stored in the index levels is potentially lost*,
    we cannot guarantee a complete description of beliefs in the BeliefsDataFrame.
    Therefore, we type the result as a regular pandas DataFrame.

    * The index levels are dropped (by overwriting the multi-level index with just the “event_start” index level).
    Only if index_levels_to_columns=True the relevant information is kept around.
    """
    if index_levels_to_columns is not None:
        for col in index_levels_to_columns:
            try:
                bdf[col] = bdf.index.get_level_values(col)
            except KeyError:
                if hasattr(bdf, col):
                    bdf[col] = getattr(bdf, col)
                elif hasattr(bdf, bvp_inflection.pluralize(col)):
                    bdf[col] = getattr(bdf, bvp_inflection.pluralize(col))
                else:
                    raise KeyError(f"Level {col} not found")
    bdf.index = bdf.index.get_level_values("event_start")
    return bdf


def new_dataframe_aligned_with(
    df: tb.BeliefsDataFrame, columns: List[str] = None, column_values=np.nan
) -> pd.DataFrame:
    """
    Create new DataFrame, where index & columns are aligned with the
    given BeliefsDataFrame. Index is simplified to "event_start".
    The default values for columns is NaN, but you can pass in others.
    Standard columns are event_value, belief_horizon and source.
    """
    if columns is None:
        columns = ["event_value", "belief_horizon", "source"]
    bdf = tb.BeliefsDataFrame(
        column_values,  # init with NaN values
        index=df.index,
        sensor=df.sensor,
        columns=columns,
    )
    return simplify_index(bdf)
