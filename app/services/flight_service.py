from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from ..db import query
from ..errors import ApiError
from .airport_metadata import AIRPORT_REGIONS


def airport_metadata():
    rows = query('SELECT AirportID,Code,Name,City,CountryName,IanaTimeZone,IsActive FROM dbo.Airports')
    for row in rows:
        code = row['Code'].strip()
        row['Code'] = code
        row['CountryCode'], row['RegionCode'] = AIRPORT_REGIONS.get(code, ('VN', 'VIETNAM') if row['CountryName'] == 'Việt Nam' else ('', 'OTHER'))
    return {row['AirportID']: row for row in rows}


def zone(name, status=503):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ApiError('Múi giờ sân bay chưa được cấu hình hợp lệ.', status) from None


def civil_day(day, zone_name):
    local = zone(zone_name)
    start = datetime.combine(day, time.min, local).astimezone(timezone.utc).replace(tzinfo=None)
    end = datetime.combine(day + timedelta(days=1), time.min, local).astimezone(timezone.utc).replace(tzinfo=None)
    return start, end


def decorate_flights(rows, airports=None):
    airports = airports or airport_metadata()
    for row in rows:
        for prefix, time_field in (('Origin', 'DepartureTime'), ('Destination', 'ArrivalTime')):
            airport = airports.get(row.get(prefix + 'ID'))
            if airport:
                row[prefix + 'TimeZone'] = airport['IanaTimeZone']
                row[prefix + 'CountryName'] = airport['CountryName']
                row[prefix + 'CountryCode'] = airport['CountryCode']
                row[prefix + 'Region'] = airport['RegionCode']
            value = row.get(time_field)
            if isinstance(value, datetime) and row.get(prefix + 'TimeZone'):
                local = value.replace(tzinfo=timezone.utc).astimezone(zone(row[prefix + 'TimeZone']))
                row['DepartureDate' if prefix == 'Origin' else 'ArrivalDate'] = local.date().isoformat()
        if isinstance(row.get('DepartureTime'), datetime) and isinstance(row.get('ArrivalTime'), datetime):
            row['DurationMinutes'] = int((row['ArrivalTime'] - row['DepartureTime']).total_seconds() // 60)
    return rows
