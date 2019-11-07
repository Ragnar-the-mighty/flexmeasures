from datetime import datetime, timedelta
from typing import List, Union

from flask import current_app
from rq import get_current_job
from rq.job import Job
from sqlalchemy.exc import IntegrityError
from timetomodel.forecasting import make_rolling_forecasts

from bvp.data.config import db
from bvp.data.models.assets import Asset, Power
from bvp.data.models.data_sources import DataSource
from bvp.data.models.forecasting import InvalidHorizonException
from bvp.data.models.forecasting.generic import latest_model as latest_generic_model
from bvp.data.models.forecasting.generic import (
    latest_version as latest_generic_model_version,
)
from bvp.data.models.markets import Market, Price
from bvp.data.models.weather import Weather, WeatherSensor
from bvp.data.utils import save_to_database
from bvp.utils.time_utils import (
    as_bvp_time,
    bvp_now,
    forecast_horizons_for,
    supported_horizons,
)

data_source_label = "forecast by Seita (%s)" % latest_generic_model_version()


# TODO: we could also monitor the failed queue and re-enqueue jobs who had missing data
#       (and maybe failed less than three times so far)


def make_forecasts(
    asset_id: int,
    timed_value_type: str,
    horizon: timedelta,
    start: datetime,
    end: datetime,
    custom_model_params: dict = None,
):
    """
    Build forecasting model specs, make rolling forecasts, save the forecasts made.
    Each individual forecast is a belief about an interval.

    Parameters
    ----------
    :param horizon: timedelta
        duration between the end of each interval and the time at which the belief about that interval is formed
    :param start: datetime
        start of forecast period, i.e. start time of the first interval to be forecast
    :param end: datetime
        end of forecast period, i.e end time of the last interval to be forecast
    """
    rq_job = get_current_job()

    data_source = get_data_source()
    asset = get_asset(asset_id, timed_value_type)
    print(
        "Running Forecasting Job %s: %s for %s, from %s to %s"
        % (rq_job.id, asset, horizon, start, end)
    )

    if horizon not in supported_horizons():
        raise InvalidHorizonException(
            "Invalid horizon on job %s: %s" % (rq_job.id, horizon)
        )

    if hasattr(asset, "market_type"):
        ex_post_horizon = (
            None
        )  # Todo: until we sorted out the ex_post_horizon, use all available price data
    else:
        ex_post_horizon = timedelta(hours=0)
    model_specs, model_identifier = latest_generic_model(
        generic_asset=asset,
        start=as_bvp_time(start),
        end=as_bvp_time(end),
        horizon=horizon,
        ex_post_horizon=ex_post_horizon,
        custom_model_params=custom_model_params,
    )
    model_specs.creation_time = bvp_now()

    # TODO: maybe check available data here already?

    forecasts, model_state = make_rolling_forecasts(
        start=as_bvp_time(start), end=as_bvp_time(end), model_specs=model_specs
    )

    ts_value_forecasts = [
        make_timed_value(timed_value_type, asset_id, dt, value, horizon, data_source.id)
        for dt, value in forecasts.items()
    ]

    try:
        save_to_database(ts_value_forecasts)
        db.session.flush()  # not sure we need this
    except IntegrityError as e:

        current_app.logger.warning(e)
        print("Rolling back due to IntegrityError")
        db.session.rollback()

        if current_app.config.get("BVP_MODE", "") == "play":
            print("Saving again, with overwrite=True")
            save_to_database(ts_value_forecasts, overwrite=True)


def create_forecasting_jobs(
    timed_value_type: str,
    asset_id: int,
    start_of_roll: datetime,
    end_of_roll: datetime,
    resolution: timedelta = None,
    horizons: List[timedelta] = None,
    custom_model_params: dict = None,
    enqueue: bool = True,
) -> List[Job]:
    """Create forecasting jobs by rolling through a time window, for a number of given forecast horizons.
    Start and end of the forecasting jobs are equal to the time window (start_of_roll, end_of_roll) plus the horizon.

    For example (with shorthand notation):

        start_of_roll = 3pm
        end_of_roll = 5pm
        resolution = 15min
        horizons = [1h, 6h, 1d]

        This creates the following 3 jobs:

        1) forecast each quarter-hour from 4pm to 6pm, i.e. the 1h forecast
        2) forecast each quarter-hour from 9pm to 11pm, i.e. the 6h forecast
        3) forecast each quarter-hour from 3pm to 5pm the next day, i.e. the 1d forecast

    If not given, relevant horizons are deduced from the resolution of the posted data.
    if enqueue is True (default), the jobs are put on the redis queue.
    Returns the redis-queue forecasting jobs which were created.
    """
    if horizons is None:
        if resolution is None:
            raise Exception(
                "Cannot create forecasting jobs - set either horizons or resolution."
            )
        horizons = forecast_horizons_for(resolution)
    jobs: List[Job] = []
    for horizon in horizons:
        job = Job.create(
            make_forecasts,
            kwargs=dict(
                asset_id=asset_id,
                timed_value_type=timed_value_type,
                horizon=horizon,
                start=start_of_roll + horizon,
                end=end_of_roll + horizon,
                custom_model_params=custom_model_params,
            ),
            connection=current_app.redis_queue.connection,
        )
        jobs.append(job)
        if enqueue:
            current_app.redis_queue.enqueue_job(job)
    return jobs


def get_data_source() -> DataSource:
    """Make sure we have a data source"""
    data_source = DataSource.query.filter(
        DataSource.label == data_source_label
    ).one_or_none()
    if data_source is None:
        data_source = DataSource(label=data_source_label, type="script")
        db.session.add(data_source)
    return data_source


def num_forecasts(start: datetime, end: datetime, resolution: timedelta) -> int:
    """Compute how many forecasts a job needs to make, given a resolution"""
    return (end - start) // resolution


# --- the functions below can hopefully go away if we refactor a real generic asset class


def get_asset(
    asset_id: int, timed_value_type: str
) -> Union[Asset, Market, WeatherSensor]:
    """Get asset for this job. Maybe simpler once we redesign timed value classes (make a generic one)"""
    if timed_value_type not in ("Power", "Price", "Weather"):
        raise Exception("Cannot get asset for asset_type '%s'" % timed_value_type)
    asset = None
    if timed_value_type == "Power":
        asset = Asset.query.filter_by(id=asset_id).one_or_none()
    elif timed_value_type == "Price":
        asset = Market.query.filter_by(id=asset_id).one_or_none()
    elif timed_value_type == "Weather":
        asset = WeatherSensor.query.filter_by(id=asset_id).one_or_none()
    if asset is None:
        raise Exception(
            "Cannot find asset for value type %s with id %d"
            % (timed_value_type, asset_id)
        )
    return asset


def make_timed_value(
    timed_value_type: str,
    asset_id: int,
    dt: datetime,
    value: float,
    horizon: timedelta,
    data_source_id: int,
) -> Union[Power, Price, Weather]:
    if timed_value_type not in ("Power", "Price", "Weather"):
        raise Exception("Cannot get asset for asset_type '%s'" % timed_value_type)
    ts_value = None
    if timed_value_type == "Power":
        ts_value = Power(
            datetime=dt,
            horizon=horizon,
            value=value,
            asset_id=asset_id,
            data_source_id=data_source_id,
        )
    elif timed_value_type == "Price":
        ts_value = Price(
            datetime=dt,
            horizon=horizon,
            value=value,
            market_id=asset_id,
            data_source_id=data_source_id,
        )
    elif timed_value_type == "Weather":
        ts_value = Weather(
            datetime=dt,
            horizon=horizon,
            value=value,
            sensor_id=asset_id,
            data_source_id=data_source_id,
        )
    if ts_value is None:
        raise Exception(
            "Cannot create asset of type %s with id %d" % (timed_value_type, asset_id)
        )
    return ts_value