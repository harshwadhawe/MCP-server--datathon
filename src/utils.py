"""Utility functions for the MCP server."""

from datetime import datetime, timedelta
from typing import Optional
import re


def parse_date_reference(text: str, base_date: Optional[datetime] = None) -> Optional[datetime]:
    """
    Parse natural language date references from text.
    
    Args:
        text: Input text containing date references
        base_date: Reference date (defaults to now)
    
    Returns:
        Parsed datetime or None if no date found
    """
    if base_date is None:
        base_date = datetime.now()
    
    text_lower = text.lower()
    
    # Today
    if 'today' in text_lower:
        return base_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Tomorrow
    if 'tomorrow' in text_lower:
        return (base_date + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Next week
    if 'next week' in text_lower:
        days_ahead = 7 - base_date.weekday()
        return (base_date + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # This week
    if 'this week' in text_lower:
        return base_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Day of week references
    days = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }
    for day_name, day_num in days.items():
        if day_name in text_lower:
            current_weekday = base_date.weekday()
            days_ahead = (day_num - current_weekday) % 7
            
            # If "next" is mentioned, always go to next week
            if 'next' in text_lower:
                if days_ahead == 0:
                    # If today is that day, "next" means next week
                    days_ahead = 7
                else:
                    # Already in future, but "next" means next week
                    days_ahead = days_ahead if days_ahead > 0 else days_ahead + 7
            elif days_ahead == 0:
                # If today is that day and no "next", return today
                pass
            
            return (base_date + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    return None


def parse_time_reference(text: str) -> Optional[tuple[int, int]]:
    """
    Parse time references from text (e.g., "2 PM", "14:30").
    
    Args:
        text: Input text containing time references
    
    Returns:
        Tuple of (hour, minute) in 24-hour format, or None
    """
    text_lower = text.lower()
    
    # 12-hour format with AM/PM
    time_pattern = r'(\d{1,2})\s*(am|pm)'
    match = re.search(time_pattern, text_lower)
    if match:
        hour = int(match.group(1))
        period = match.group(2)
        if period == 'pm' and hour != 12:
            hour += 12
        elif period == 'am' and hour == 12:
            hour = 0
        return (hour, 0)
    
    # 24-hour format
    time_pattern_24 = r'(\d{1,2}):(\d{2})'
    match = re.search(time_pattern_24, text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return (hour, minute)
    
    return None


def format_event_time(event: dict) -> str:
    """
    Format event start/end time for display.
    
    Args:
        event: Google Calendar event dictionary
    
    Returns:
        Formatted time string
    """
    start = event.get('start', {})
    end = event.get('end', {})
    
    start_time = start.get('dateTime') or start.get('date')
    end_time = end.get('dateTime') or end.get('date')
    
    if not start_time:
        return "Time TBD"
    
    try:
        if 'T' in start_time:
            # Has time component
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00')) if end_time else None
            
            start_str = start_dt.strftime('%I:%M %p').lstrip('0')
            if end_dt:
                end_str = end_dt.strftime('%I:%M %p').lstrip('0')
                return f"{start_str} - {end_str}"
            return start_str
        else:
            # All-day event
            return "All day"
    except Exception:
        return "Time TBD"

