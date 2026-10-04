"""
Compatibility validators used by utils package.
Thin helpers for input sanitization — trading validation lives in core.validators.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID


def validate_email(value: str) -> Tuple[bool, Optional[str]]:
    if not value or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
        return False, "Invalid email"
    return True, None


def validate_phone(value: str) -> Tuple[bool, Optional[str]]:
    if not value or not re.match(r"^\+?[0-9]{7,15}$", str(value).replace(" ", "")):
        return False, "Invalid phone"
    return True, None


def validate_mt5_account(value: str) -> Tuple[bool, Optional[str]]:
    if not value or not str(value).isdigit() or len(str(value)) < 4:
        return False, "Invalid MT5 account"
    return True, None


def validate_mt5_server(value: str) -> Tuple[bool, Optional[str]]:
    if not value or len(str(value).strip()) < 2:
        return False, "Invalid MT5 server"
    return True, None


def validate_symbol(value: str) -> Tuple[bool, Optional[str]]:
    if not value or not re.match(r"^[A-Za-z0-9]{3,12}$", str(value).strip()):
        return False, "Invalid symbol"
    return True, None


def validate_price(value: Any) -> Tuple[bool, Optional[str]]:
    try:
        v = float(value)
        if v <= 0 or not (v == v):  # NaN check
            return False, "Invalid price"
        return True, None
    except (TypeError, ValueError):
        return False, "Invalid price"


def validate_risk_percentage(value: Any) -> Tuple[bool, Optional[str]]:
    try:
        v = float(value)
        if not 0.001 <= v <= 0.1:
            return False, "Risk must be between 0.1% and 10%"
        return True, None
    except (TypeError, ValueError):
        return False, "Invalid risk percentage"


def validate_position_size(value: Any) -> Tuple[bool, Optional[str]]:
    try:
        v = float(value)
        if v <= 0:
            return False, "Position size must be positive"
        return True, None
    except (TypeError, ValueError):
        return False, "Invalid position size"


def validate_telegram_username(value: str) -> Tuple[bool, Optional[str]]:
    if value and not re.match(r"^[a-zA-Z0-9_]{5,32}$", value):
        return False, "Invalid telegram username"
    return True, None


def validate_uuid(value: str) -> Tuple[bool, Optional[str]]:
    try:
        UUID(str(value))
        return True, None
    except Exception:
        return False, "Invalid UUID"


def validate_url(value: str) -> Tuple[bool, Optional[str]]:
    if not value or not re.match(r"^https?://", str(value)):
        return False, "Invalid URL"
    return True, None


def validate_date(value: str) -> Tuple[bool, Optional[str]]:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True, None
    except Exception:
        return False, "Invalid date"


def validate_time_range(start: Any, end: Any) -> Tuple[bool, Optional[str]]:
    try:
        if start is None or end is None:
            return False, "Missing time range"
        return True, None
    except Exception:
        return False, "Invalid time range"


def validate_password_strength(value: str) -> Tuple[bool, Optional[str]]:
    if not value or len(value) < 8:
        return False, "Password too short"
    return True, None


def validate_json_schema(value: str) -> Tuple[bool, Optional[str]]:
    try:
        json.loads(value)
        return True, None
    except Exception:
        return False, "Invalid JSON"


def validate_percentage(value: Any) -> Tuple[bool, Optional[str]]:
    try:
        v = float(value)
        if not 0 <= v <= 100:
            return False, "Percentage out of range"
        return True, None
    except (TypeError, ValueError):
        return False, "Invalid percentage"


def validate_integer(value: Any) -> Tuple[bool, Optional[str]]:
    try:
        int(value)
        return True, None
    except (TypeError, ValueError):
        return False, "Invalid integer"


def validate_float(value: Any) -> Tuple[bool, Optional[str]]:
    try:
        float(value)
        return True, None
    except (TypeError, ValueError):
        return False, "Invalid float"


def validate_boolean(value: Any) -> Tuple[bool, Optional[str]]:
    if isinstance(value, bool):
        return True, None
    if str(value).lower() in {"true", "false", "1", "0", "yes", "no"}:
        return True, None
    return False, "Invalid boolean"


def validate_list(value: Any) -> Tuple[bool, Optional[str]]:
    if isinstance(value, list):
        return True, None
    return False, "Expected list"


def validate_dict(value: Any) -> Tuple[bool, Optional[str]]:
    if isinstance(value, dict):
        return True, None
    return False, "Expected dict"


def validate_not_empty(value: Any) -> Tuple[bool, Optional[str]]:
    if value is None or value == "" or value == [] or value == {}:
        return False, "Value must not be empty"
    return True, None
