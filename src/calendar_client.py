"""Google Calendar API client for fetching calendar events."""

import os
import sys
import json
import contextlib
import io
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False


# Scopes required for Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


class CalendarClient:
    """Client for interacting with Google Calendar API."""
    
    def __init__(self, credentials_path: str = "config/credentials.json", token_path: str = "config/token.json"):
        """
        Initialize the Calendar client.
        
        Args:
            credentials_path: Path to OAuth2 credentials JSON file
            token_path: Path to store/load OAuth2 token
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None
        self.calendar_timezone = None
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate and build the Google Calendar service."""
        creds = None
        
        # Load existing token if available
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception as e:
                sys.stderr.write(f"Error loading token: {e}\n")
        
        # If there are no (valid) credentials available, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    sys.stderr.write(f"Error refreshing token: {e}\n")
                    creds = None
            
            if not creds:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"Credentials file not found at {self.credentials_path}. "
                        "Please download credentials.json from Google Cloud Console."
                    )
                
                # Check credential type (desktop app vs web application)
                with open(self.credentials_path, 'r') as f:
                    creds_data = json.load(f)
                
                # Suppress stdout during OAuth flow to avoid breaking JSON-RPC
                # Note: OAuth flow should ideally be done before running MCP server
                # In MCP server context, authentication should be done beforehand
                original_stdout = sys.stdout
                try:
                    sys.stdout = sys.stderr
                    
                    # Support both desktop app and web application credentials
                    if 'installed' in creds_data:
                        # Desktop application credentials
                        flow = InstalledAppFlow.from_client_secrets_file(
                            self.credentials_path, SCOPES
                        )
                        creds = flow.run_local_server(port=8501)
                    elif 'web' in creds_data:
                        # Web application credentials - can still use local server
                        # Make sure redirect URIs include http://localhost:8501
                        flow = Flow.from_client_secrets_file(
                            self.credentials_path, SCOPES
                        )
                        # For web apps, we need to specify redirect URI explicitly
                        flow.redirect_uri = 'http://localhost:8501'
                        creds = flow.run_local_server(port=8501)
                    else:
                        raise ValueError(
                            "Invalid credentials file format. Expected 'installed' or 'web' key. "
                            "Please ensure you downloaded the correct credentials file from Google Cloud Console."
                        )
                finally:
                    sys.stdout = original_stdout
                    sys.stdout.flush()  # Ensure any buffered output is flushed
            
            # Save the credentials for the next run
            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
        
        self.service = build('calendar', 'v3', credentials=creds)
        
        # Get calendar timezone - this is critical for correct date/time queries
        try:
            calendar = self.service.calendars().get(calendarId='primary').execute()
            self.calendar_timezone = calendar.get('timeZone', 'UTC')
            # Set environment variable so query analyzer can use it for time server
            os.environ['CALENDAR_TIMEZONE'] = self.calendar_timezone
        except Exception as e:
            # Fallback to UTC if we can't get calendar timezone
            self.calendar_timezone = 'UTC'
            os.environ['CALENDAR_TIMEZONE'] = 'UTC'
    
    def get_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 10,
        calendar_id: str = 'primary'
    ) -> List[Dict]:
        """
        Fetch events from Google Calendar.
        
        Args:
            time_min: Start time for event query (defaults to now)
            time_max: End time for event query (defaults to 7 days from now)
            max_results: Maximum number of events to return
            calendar_id: Calendar ID (defaults to 'primary')
        
        Returns:
            List of event dictionaries
        """
        if not self.service:
            raise RuntimeError("Calendar service not initialized. Authentication required.")
        
        if time_min is None:
            time_min = datetime.now()
        if time_max is None:
            time_max = time_min + timedelta(days=7)
        
        try:
            # Google Calendar API expects RFC3339 format with timezone
            # CRITICAL: Use the calendar's actual timezone, not system timezone
            # This ensures events are queried in the same timezone they're stored
            
            # Get the calendar's timezone object
            if PYTZ_AVAILABLE and self.calendar_timezone:
                try:
                    cal_tz = pytz.timezone(self.calendar_timezone)
                except Exception as e:
                    sys.stderr.write(f"[Calendar Query] Warning: Invalid timezone '{self.calendar_timezone}', using UTC: {e}\n")
                    cal_tz = pytz.UTC
            else:
                # Fallback to UTC if pytz not available
                cal_tz = pytz.UTC if PYTZ_AVAILABLE else timezone.utc
            
            # Convert naive datetimes to calendar timezone
            # If datetime is naive, assume it's in the calendar's timezone
            if time_min.tzinfo is None:
                if PYTZ_AVAILABLE:
                    time_min = cal_tz.localize(time_min)
                else:
                    # Fallback: use UTC offset calculation
                    time_min = time_min.replace(tzinfo=timezone.utc)
            else:
                # If timezone-aware, convert to calendar timezone
                if PYTZ_AVAILABLE:
                    time_min = time_min.astimezone(cal_tz)
            
            if time_max.tzinfo is None:
                if PYTZ_AVAILABLE:
                    time_max = cal_tz.localize(time_max)
                else:
                    time_max = time_max.replace(tzinfo=timezone.utc)
            else:
                if PYTZ_AVAILABLE:
                    time_max = time_max.astimezone(cal_tz)
            
            # Format as RFC3339 (ISO 8601) with timezone
            # Google Calendar API expects times in the calendar's timezone
            time_min_str = time_min.isoformat()
            time_max_str = time_max.isoformat()
            
            # Ensure we have proper timezone format (replace +00:00 with Z only if UTC)
            if time_min.tzinfo == timezone.utc and time_min_str.endswith('+00:00'):
                time_min_str = time_min_str.replace('+00:00', 'Z')
            if time_max.tzinfo == timezone.utc and time_max_str.endswith('+00:00'):
                time_max_str = time_max_str.replace('+00:00', 'Z')
            
            # Fetch all events with pagination
            events = []
            page_token = None
            
            while True:
                request_params = {
                    'calendarId': calendar_id,
                    'timeMin': time_min_str,
                    'timeMax': time_max_str,
                    'maxResults': min(max_results, 2500),  # API max is 2500
                    'singleEvents': True,
                    'orderBy': 'startTime'
                }
                
                if page_token:
                    request_params['pageToken'] = page_token
                
                events_result = self.service.events().list(**request_params).execute()
                
                page_events = events_result.get('items', [])
                events.extend(page_events)
                
                # Check if there are more pages
                page_token = events_result.get('nextPageToken')
                if not page_token or len(events) >= max_results:
                    break
            
            return events[:max_results]  # Return up to max_results
        
        except HttpError as error:
            error_details = error.error_details if hasattr(error, 'error_details') else str(error)
            status_code = error.resp.status if hasattr(error, 'resp') else None
            
            # Handle rate limiting
            if status_code == 429:
                raise RuntimeError(
                    "Google Calendar API rate limit exceeded. Please wait a moment and try again."
                )
            
            # Handle authentication errors
            if status_code in [401, 403]:
                raise RuntimeError(
                    "Authentication failed. Please re-authenticate with Google Calendar."
                )
            
            # Handle other HTTP errors
            raise RuntimeError(
                f"Google Calendar API error (status {status_code}): {error_details}"
            )
        
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"Unexpected error while fetching events: {str(e)}")
    
    def list_calendars(self) -> List[Dict]:
        """
        List all calendars the user has access to.
        
        Returns:
            List of calendar dictionaries with id, summary, and other metadata
        """
        if not self.service:
            raise RuntimeError("Calendar service not initialized. Authentication required.")
        
        try:
            calendar_list = self.service.calendarList().list().execute()
            calendars = calendar_list.get('items', [])
            
            return calendars
        except HttpError as error:
            error_details = error.error_details if hasattr(error, 'error_details') else str(error)
            status_code = error.resp.status if hasattr(error, 'resp') else None
            raise RuntimeError(
                f"Error listing calendars (status {status_code}): {error_details}"
            )
    
    def get_events_from_all_calendars(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 250,
        calendar_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Fetch events from multiple calendars (or all calendars if calendar_ids is None).
        
        Args:
            time_min: Start time for event query (defaults to now)
            time_max: End time for event query (defaults to 7 days from now)
            max_results: Maximum number of events per calendar
            calendar_ids: List of calendar IDs to fetch from. If None, fetches from all calendars.
        
        Returns:
            List of event dictionaries, each with a 'calendar_name' field added
        """
        if not self.service:
            raise RuntimeError("Calendar service not initialized. Authentication required.")
        
        # Get list of calendars if not provided
        if calendar_ids is None:
            calendars = self.list_calendars()
            calendar_ids = [cal.get('id') for cal in calendars]
            calendar_names = {cal.get('id'): cal.get('summary', 'Unknown') for cal in calendars}
        else:
            # Fetch calendar names for provided IDs
            calendar_names = {}
            for cal_id in calendar_ids:
                try:
                    cal = self.service.calendars().get(calendarId=cal_id).execute()
                    calendar_names[cal_id] = cal.get('summary', 'Unknown')
                except Exception:
                    calendar_names[cal_id] = cal_id
        
        all_events = []
        
        for cal_id in calendar_ids:
            cal_name = calendar_names.get(cal_id, cal_id)
            try:
                events = self.get_events(
                    time_min=time_min,
                    time_max=time_max,
                    max_results=max_results,
                    calendar_id=cal_id
                )
                
                # Add calendar name to each event
                for event in events:
                    event['calendar_name'] = cal_name
                    event['calendar_id'] = cal_id
                
                all_events.extend(events)
            except Exception as e:
                # Silently skip calendars that fail
                continue
        
        # Sort all events by start time
        all_events.sort(key=lambda e: self._get_event_sort_time(e))
        
        return all_events
    
    def _get_event_sort_time(self, event: Dict) -> datetime:
        """Get event datetime for sorting."""
        start = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
        if start:
            try:
                if 'T' in start:
                    return datetime.fromisoformat(start.replace('Z', '+00:00'))
                else:
                    return datetime.fromisoformat(start)
            except Exception:
                pass
        return datetime.min
    
    def get_events_for_date(self, date: datetime, calendar_id: str = 'primary') -> List[Dict]:
        """
        Get all events for a specific date.
        
        Args:
            date: Date to fetch events for
            calendar_id: Calendar ID (defaults to 'primary')
        
        Returns:
            List of events for the specified date
        
        Raises:
            RuntimeError: If API call fails
        """
        try:
            time_min = date.replace(hour=0, minute=0, second=0, microsecond=0)
            time_max = time_min + timedelta(days=1)
            return self.get_events(time_min=time_min, time_max=time_max, max_results=50, calendar_id=calendar_id)
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"Error fetching events for date: {str(e)}")
    
    def check_availability(
        self,
        start_time: datetime,
        end_time: datetime,
        calendar_id: str = 'primary'
    ) -> tuple[bool, List[Dict]]:
        """
        Check if user is available during a time period.
        
        Args:
            start_time: Start of time period to check
            end_time: End of time period to check
            calendar_id: Calendar ID (defaults to 'primary')
        
        Returns:
            Tuple of (is_available, list_of_conflicting_events)
        
        Raises:
            RuntimeError: If API call fails or invalid time range
        """
        if start_time >= end_time:
            raise ValueError("start_time must be before end_time")
        
        try:
            events = self.get_events(time_min=start_time, time_max=end_time, max_results=50, calendar_id=calendar_id)
        except Exception as e:
            raise RuntimeError(f"Error checking availability: {str(e)}")
        
        conflicts = []
        for event in events:
            event_start = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
            event_end = event.get('end', {}).get('dateTime') or event.get('end', {}).get('date')
            
            if not event_start:
                continue
            
            try:
                if 'T' in event_start:
                    evt_start = datetime.fromisoformat(event_start.replace('Z', '+00:00'))
                    evt_end = datetime.fromisoformat(event_end.replace('Z', '+00:00'))
                    
                    # Check for overlap
                    if not (evt_end <= start_time or evt_start >= end_time):
                        conflicts.append(event)
                else:
                    # All-day event - conflicts if on the same day
                    evt_date = datetime.fromisoformat(event_start)
                    if evt_date.date() == start_time.date():
                        conflicts.append(event)
            except (ValueError, KeyError) as e:
                # Skip events with invalid date formats
                continue
        
        return len(conflicts) == 0, conflicts
    
    def get_upcoming_events(self, days: int = 7, max_results: int = 10) -> List[Dict]:
        """
        Get upcoming events for the next N days.
        
        Args:
            days: Number of days to look ahead
            max_results: Maximum number of events to return
        
        Returns:
            List of upcoming events
        
        Raises:
            RuntimeError: If API call fails
            ValueError: If days or max_results are invalid
        """
        if days < 1:
            raise ValueError("days must be at least 1")
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        
        try:
            # Use local timezone-aware datetime
            local_tz_offset = time.timezone if (time.daylight == 0) else time.altzone
            local_tz = timezone(timedelta(seconds=-local_tz_offset))
            time_min = datetime.now(local_tz)
            time_max = time_min + timedelta(days=days)
            return self.get_events(time_min=time_min, time_max=time_max, max_results=max_results)
        except Exception as e:
            if isinstance(e, (RuntimeError, ValueError)):
                raise
            raise RuntimeError(f"Error fetching upcoming events: {str(e)}")

