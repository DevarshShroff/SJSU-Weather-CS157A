"""Weather variables reported by each SJSU station, keyed by station code (SynopticID).

Variable codes match weather_variables.code; list order is the display order.
Stations missing from this dictionary fall back to the station_variables table.
"""

STATION_VARIABLES = {
    "SJS06": (  # BlackberryHill
        "air_temperature", "relative_humidity", "rainfall", "solar_radiation",
        "fuel_moisture", "pa_conductivity", "wind_speed_average", "wind_direction",
        "wind_direction_stddev", "wind_speed_maximum",
    ),
    "SJS62": (  # CZUSoilMoisture
        "air_temperature", "relative_humidity", "rainfall", "solar_radiation",
        "fuel_moisture", "pa_conductivity",
    ),
    "SJS01": (  # DHRoof
        "air_temperature", "relative_humidity", "rainfall", "solar_radiation",
        "wind_speed_average", "wind_direction", "wind_direction_stddev", "wind_speed_maximum",
    ),
    "SJS02": (  # MtDiabloSummit
        "air_temperature", "relative_humidity", "wind_speed_average", "wind_direction",
        "wind_direction_stddev", "wind_speed_maximum",
    ),
    "SJS04": (  # MtUmunhum
        "air_temperature", "relative_humidity", "rainfall", "solar_radiation",
        "fuel_temperature", "fuel_moisture", "pa_conductivity", "wind_speed_average",
        "wind_direction", "wind_direction_stddev", "wind_speed_maximum",
    ),
    "SJS61": (  # PGESanRamon
        "air_temperature", "relative_humidity", "rainfall", "solar_radiation",
        "fuel_moisture", "pa_conductivity", "wind_speed_average", "wind_direction",
        "wind_direction_stddev", "wind_speed_maximum",
    ),
    "SJS41": (  # Portable2
        "air_temperature", "relative_humidity", "rainfall", "solar_radiation",
        "fuel_temperature", "fuel_moisture", "pa_conductivity", "wind_speed_average",
        "wind_direction", "wind_direction_stddev", "wind_speed_maximum",
    ),
    "SJS05": (  # SpringValley
        "air_temperature", "relative_humidity", "rainfall", "solar_radiation",
        "fuel_temperature", "fuel_moisture", "pa_conductivity", "wind_speed_average",
        "wind_direction", "wind_direction_stddev", "wind_speed_maximum",
    ),
}
