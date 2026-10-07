"""Sunset times without any internet service (NOAA's sunrise equation, accurate to a minute or two)."""
import datetime as dt
import math


def sunset(day, lat, lon):
    """Local sunset time (timezone-aware, in the Pi's own time zone) for a date at lat/lon (east positive)."""
    jd_noon = day.toordinal() + 1721424.5 + 0.5          # Julian day at noon UTC on that date
    n = round(jd_noon - 2451545.0)                         # days since 2000-01-01 noon
    j_star = n - lon / 360.0
    m = (357.5291 + 0.98560028 * j_star) % 360
    mr = math.radians(m)
    c = 1.9148 * math.sin(mr) + 0.02 * math.sin(2 * mr) + 0.0003 * math.sin(3 * mr)
    lam = math.radians((m + c + 180 + 102.9372) % 360)
    j_transit = 2451545.0 + j_star + 0.0053 * math.sin(mr) - 0.0069 * math.sin(2 * lam)
    decl = math.asin(math.sin(lam) * math.sin(math.radians(23.4397)))
    phi = math.radians(lat)
    cos_w = (math.sin(math.radians(-0.833)) - math.sin(phi) * math.sin(decl)) / (math.cos(phi) * math.cos(decl))
    cos_w = max(-1.0, min(1.0, cos_w))                     # polar day/night: clamp
    j_set = j_transit + math.degrees(math.acos(cos_w)) / 360
    utc = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=j_set - 2440587.5)
    return utc.astimezone()                                # the Pi's local time zone


def lights_window(now, lat, lon, minutes_before, off_time):
    """When the lights should be on around `now`.

    Returns (is_on, on_at, off_at, sunset_today): on from `minutes_before` sunset until
    `off_time` ("HH:MM", usually early morning) the next day.
    """
    now = now.astimezone()
    h, m = (int(x) for x in off_time.split(":"))
    today = now.date()
    set_today = sunset(today, lat, lon)
    on_today = set_today - dt.timedelta(minutes=minutes_before)
    off_today = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if off_today.time() < on_today.time():                 # usual case: off after midnight
        if now < off_today:                                # still last night's show
            on_at = sunset(today - dt.timedelta(days=1), lat, lon) - dt.timedelta(minutes=minutes_before)
            return True, on_at, off_today, set_today
        if now >= on_today:
            return True, on_today, off_today + dt.timedelta(days=1), set_today
        return False, on_today, off_today + dt.timedelta(days=1), set_today
    return on_today <= now < off_today, on_today, off_today, set_today   # off later the same evening
