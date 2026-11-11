import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from flask import request
from .errors import ApiError

def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError('Cần nội dung JSON hợp lệ.')
    return data

def text(data, key, minimum=1, maximum=120):
    value = data.get(key)
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ApiError(f'Trường {key} cần từ {minimum} đến {maximum} ký tự.')
    return value.strip()

def integer(data, key, minimum=1, maximum=2147483647):
    value = str(data.get(key))
    if value.isdecimal():
        try:
            number = int(value)
        except ValueError:
            pass
        else:
            if minimum <= number <= maximum:
                return number
    raise ApiError(f'Trường {key} phải là số nguyên từ {minimum} đến {maximum}.')

def decimal_value(data, key, minimum=0, maximum=100000000):
    try:
        value = Decimal(str(data.get(key)))
        if not value.is_finite() or not Decimal(str(minimum)) <= value <= Decimal(str(maximum)):
            raise ValueError
        return value
    except (InvalidOperation, ValueError):
        raise ApiError(f'Trường {key} phải là số từ {minimum} đến {maximum}.') from None

def email(data):
    value = text(data, 'Email', 5, 254).lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
        raise ApiError('Email không hợp lệ.')
    return value

def iso_date(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ApiError('Ngày phải theo định dạng YYYY-MM-DD.') from None

def utc_datetime(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if d.tzinfo is None:
            raise ValueError
        return d.astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        raise ApiError('Thời gian phải kèm múi giờ ISO 8601.') from None
