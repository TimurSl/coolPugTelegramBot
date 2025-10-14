import logging
import re
from datetime import timedelta
from typing import Optional


class TimeUtils:
    """Enhanced time utilities with flexible parsing"""

    TIME_UNITS = {
        's': 'seconds', 'sec': 'seconds', 'second': 'seconds', 'seconds': 'seconds',
        'm': 'minutes', 'min': 'minutes', 'minute': 'minutes', 'minutes': 'minutes',
        'h': 'hours', 'hr': 'hours', 'hour': 'hours', 'hours': 'hours',
        'd': 'days', 'day': 'days', 'days': 'days',
        'w': 'weeks', 'week': 'weeks', 'weeks': 'weeks',
    }

    @classmethod
    def parse_duration(cls, duration_str: str) -> Optional[timedelta]:
        """
        Parse duration string into timedelta
        Examples: "1d", "2h", "30m", "1d2h30m", "permanent", "forever"
        """
        if not duration_str:
            logging.debug("parse_duration called with empty input")
            return None

        duration_str = duration_str.lower().strip()
        logging.debug("Parsing duration string '%s'", duration_str)

        # Handle permanent bans
        if duration_str in ['permanent', 'forever', 'perm', '0']:
            logging.debug("Duration '%s' considered permanent", duration_str)
            return None

        # Regex to match time components
        pattern = r'(\d+)\s*([a-zA-Z]+)'
        matches = re.findall(pattern, duration_str)

        if not matches:
            logging.debug("No matches found in duration '%s'", duration_str)
            return None

        total_seconds = 0

        for amount_str, unit in matches:
            try:
                amount = int(amount_str)
                unit_normalized = cls.TIME_UNITS.get(unit, unit)
                logging.debug("Processing duration part: %s%s (normalised=%s)", amount, unit, unit_normalized)

                if unit_normalized == 'seconds':
                    total_seconds += amount
                elif unit_normalized == 'minutes':
                    total_seconds += amount * 60
                elif unit_normalized == 'hours':
                    total_seconds += amount * 3600
                elif unit_normalized == 'days':
                    total_seconds += amount * 86400
                elif unit_normalized == 'weeks':
                    total_seconds += amount * 604800
                else:
                    logging.warning("Unknown duration unit '%s'", unit)
                    continue

            except ValueError:
                logging.warning("Invalid duration amount '%s'", amount_str)
                continue

        if total_seconds <= 0:
            logging.debug("Total seconds calculated as %s; returning None", total_seconds)
            return None

        result = timedelta(seconds=total_seconds)
        logging.debug("Duration '%s' parsed as %s", duration_str, result)
        return result

    @classmethod
    def format_duration(cls, duration: timedelta) -> str:
        """Format timedelta into human readable string"""
        if not duration:
            logging.debug("format_duration received falsy duration -> permanent")
            return "permanent"

        total_seconds = int(duration.total_seconds())
        logging.debug("Formatting duration of %s seconds", total_seconds)

        if total_seconds < 60:
            return f"{total_seconds} seconds"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            days = total_seconds // 86400
            return f"{days} day{'s' if days != 1 else ''}"

    @classmethod
    def poetic_to_real(cls, value: str) -> str:
        """Convert poetic durations (like '1d2h') into human readable description."""
        duration = cls.parse_duration(value)
        if duration is None:
            logging.debug("poetic_to_real returning 'permanent' for value '%s'", value)
            return "permanent"
        return cls.format_duration(duration)

