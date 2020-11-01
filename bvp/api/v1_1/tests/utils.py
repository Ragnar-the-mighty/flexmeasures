"""Useful test messages"""
from typing import Optional, Dict, Any
from datetime import timedelta
from isodate import duration_isoformat, parse_duration, parse_datetime

import pandas as pd
from numpy import tile

from bvp.api.common.utils.api_utils import parse_entity_address
from bvp.data.models.markets import Market, Price


def message_for_get_prognosis(
    no_horizon: bool = False,
    invalid_horizon=False,
    rolling_horizon=False,
    no_data=False,
    no_resolution=False,
    single_connection=False,
    timezone_alternative=False,
) -> dict:
    message = {
        "type": "GetPrognosisRequest",
        "start": "2015-01-01T00:00:00Z",
        "duration": "PT1H30M",
        "horizon": "R/PT6H",
        "resolution": "PT15M",
        "connections": ["CS 1", "CS 2", "CS 3"],
        "unit": "MW",
    }
    if no_horizon:
        message.pop("horizon", None)
        message.pop(
            "start", None
        )  # Otherwise, the server will determine the horizon based on when the API endpoint was called
    elif invalid_horizon:
        message["horizon"] = "T6H"
    elif rolling_horizon:
        message["horizon"] = "R/PT6H"
    if no_data:
        message["start"] = ("2010-01-01T00:00:00Z",)
    if no_resolution:
        message.pop("resolution", None)
    if single_connection:
        message["connection"] = message["connections"][0]
        message.pop("connections", None)
    if timezone_alternative:
        message["start"] = ("2015-01-01T00:00:00+00:00",)
    return message


def message_for_post_price_data(
    invalid_unit: bool = False,
    tile_n: int = 1,
    compress_n: int = 1,
    duration: Optional[timedelta] = None,
) -> dict:
    """
    The default message has 24 hourly values.

    :param tile_n: Tile the price profile back to back to obtain price data for n days (default = 1).
    :param compress_n: Compress the price profile to obtain price data with a coarser resolution (default = 1),
                       e.g. compress=4 leads to a resolution of 4 hours.
    :param duration: Set a duration explicitly to obtain price data with a coarser or finer resolution (default is equal to 24 hours * tile_n),
                     e.g. (assuming tile_n=1) duration=timedelta(hours=6) leads to a resolution of 15 minutes,
                     and duration=timedelta(hours=48) leads to a resolution of 2 hours.
    """
    message = {
        "type": "PostPriceDataRequest",
        "market": "ea1.2018-06.localhost:5000:epex_da",
        "values": tile(
            [
                52.37,
                51.14,
                49.09,
                48.35,
                48.47,
                49.98,
                58.7,
                67.76,
                69.21,
                70.26,
                70.46,
                70,
                70.7,
                70.41,
                70,
                64.53,
                65.92,
                69.72,
                70.51,
                75.49,
                70.35,
                70.01,
                66.98,
                58.61,
            ],
            tile_n,
        ).tolist(),
        "start": "2015-01-01T15:00:00+09:00",
        "duration": duration_isoformat(timedelta(hours=24 * tile_n)),
        "horizon": duration_isoformat(timedelta(hours=11 + 24 * tile_n)),
        "unit": "EUR/MWh",
    }
    if duration is not None:
        message["duration"] = duration
    if compress_n > 1:
        message["values"] = message["values"][::compress_n]
    if invalid_unit:
        message["unit"] = "KRW/kWh"  # That is, an invalid unit for EPEX SPOT.
    return message


def message_for_post_weather_data(
    invalid_unit: bool = False, temperature: bool = False
) -> dict:
    message: Dict[str, Any] = {
        "type": "PostWeatherDataRequest",
        "groups": [
            {
                "sensor": "ea1.2018-06.localhost:5000:wind_speed:33.4843866:126",
                "values": [20.04, 20.23, 20.41, 20.51, 20.55, 20.57],
            }
        ],
        "start": "2015-01-01T15:00:00+09:00",
        "duration": "PT30M",
        "horizon": "PT3H",
        "unit": "m/s",
    }
    if temperature:
        message["groups"][0][
            "sensor"
        ] = "ea1.2018-06.localhost:5000:temperature:33.4843866:126"
        if not invalid_unit:
            message["unit"] = "°C"  # Right unit for temperature
    elif invalid_unit:
        message["unit"] = "°C"  # Wrong unit for wind speed
    return message


def get_market(post_message) -> Optional[Market]:
    """util method to get market from our post message"""
    market_info = parse_entity_address(post_message["market"], "market")
    if market_info is None:
        return None
    return Market.query.filter_by(name=market_info["market_name"]).one_or_none()


def verify_prices_in_db(post_message, values, db):
    """util method to verify that price data ended up in the database"""
    start = parse_datetime(post_message["start"])
    end = start + parse_duration(post_message["duration"])
    horizon = parse_duration(post_message["horizon"])
    market = get_market(post_message)
    resolution = market.event_resolution
    query = (
        db.session.query(Price.value, Market.name)
        .filter((Price.datetime > start - resolution) & (Price.datetime < end))
        .filter(Price.horizon == horizon - (end - (Price.datetime + resolution)))
        .join(Market)
        .filter(Market.name == market.name)
    )
    df = pd.read_sql(query.statement, db.session.bind)
    assert df.value.tolist() == values
