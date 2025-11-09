"""Query analyzer for parsing natural language calendar queries."""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
from .utils import parse_date_reference, parse_time_reference


class QueryIntent(Enum):
    """Types of calendar query intents."""
    AVAILABILITY_CHECK = "availability_check"
    SCHEDULE_SUMMARY = "schedule_summary"
    CONFLICT_DETECTION = "conflict_detection"
    EVENT_DETAILS = "event_details"
    GENERAL = "general"


class QueryAnalyzer:
    """Analyzes user queries to extract calendar-related intents and parameters."""
    
    def __init__(self):
        """Initialize the query analyzer."""
        # Will be updated on each analyze() call to ensure current time
        self.base_date = None
    
    def _get_current_time(self) -> datetime:
        """
        Get the current date and time.
        First tries to fetch from a time server if enabled, otherwise uses system time.
        Uses calendar timezone if available via environment variable.
        
        Returns:
            Current datetime (naive, will be converted to calendar timezone later)
        """
        # Check if time server is enabled via environment variable
        use_time_server = os.getenv("USE_TIME_SERVER", "true").lower() == "true"
        
        # Get timezone from environment (set by calendar client) or default to CST
        calendar_tz = os.getenv("CALENDAR_TIMEZONE", "America/Chicago")
        
        if use_time_server:
            try:
                # Try to fetch time from a reliable time API
                import urllib.request
                import json
                
                # Use worldtimeapi.org (free, no API key required)
                # The API uses timezone names like "America/Chicago"
                tz_for_api = calendar_tz.replace("_", "/")
                url = f"http://worldtimeapi.org/api/timezone/{tz_for_api}"
                
                with urllib.request.urlopen(url, timeout=3) as response:
                    data = json.loads(response.read().decode())
                    # Parse the datetime string from the API
                    # The API returns ISO 8601 format with timezone offset
                    dt_str = data['datetime']
                    # Parse as timezone-aware datetime
                    current_time_tz = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                    # Convert to naive datetime in the calendar's timezone
                    # The API returns time in the requested timezone, so we can just remove tzinfo
                    current_time = current_time_tz.replace(tzinfo=None)
                    return current_time
            except Exception:
                # If time server fails, fall back to system time
                pass
        
        # Default: use system time (accurate for most use cases)
        # System time is synchronized with NTP on most modern systems
        return datetime.now()
    
    def analyze(self, query: str) -> Dict:
        """
        Analyze a user query and extract intent and parameters.
        
        Args:
            query: User's natural language query
        
        Returns:
            Dictionary with intent, date, time, and other extracted parameters
        """
        # Always update base_date to current time for accurate date calculations
        self.base_date = self._get_current_time()
        
        query_lower = query.lower()
        
        # Determine intent
        intent = self._detect_intent(query_lower)
        
        # Check for week references first (these should not set target_date)
        is_this_week = 'this week' in query_lower
        is_next_week = 'next week' in query_lower
        
        # Extract date reference (but not for week queries)
        target_date = None
        if not is_this_week and not is_next_week:
            target_date = parse_date_reference(query, self.base_date)
        
        # Extract time reference
        time_ref = parse_time_reference(query)
        
        # Extract additional parameters
        days_ahead = self._extract_days_ahead(query_lower)
        event_count = self._extract_event_count(query_lower)
        
        # For week queries, ensure days_ahead is set properly
        if is_this_week:
            # This week: from today to end of week (Sunday)
            days_ahead = 7 - self.base_date.weekday()
        elif is_next_week:
            # Next week: calculate days to start of next week, then 7 days
            days_to_next_monday = (7 - self.base_date.weekday()) % 7
            if days_to_next_monday == 0:
                days_to_next_monday = 7  # If today is Monday, next week starts next Monday
            days_ahead = days_to_next_monday + 7  # Next week is 7 days
        
        # Extract entities (repos, projects, people)
        entities = self._extract_entities(query)
        
        # Detect multi-intent queries
        is_multi_intent = self._detect_multi_intent(query_lower)
        
        # Determine query domain
        query_domain = self._detect_domain(query_lower)
        
        return {
            'intent': intent,
            'query': query,
            'target_date': target_date,
            'time': time_ref,
            'days_ahead': days_ahead,
            'event_count': event_count,
            'is_availability_check': intent == QueryIntent.AVAILABILITY_CHECK,
            'is_schedule_summary': intent == QueryIntent.SCHEDULE_SUMMARY,
            'is_conflict_check': intent == QueryIntent.CONFLICT_DETECTION,
            'is_this_week': is_this_week,
            'is_next_week': is_next_week,
            'entities': entities,
            'is_multi_intent': is_multi_intent,
            'query_domain': query_domain,  # 'calendar', 'github', 'both', 'general'
        }
    
    def _detect_intent(self, query_lower: str) -> QueryIntent:
        """
        Detect the intent of the query.
        
        Args:
            query_lower: Lowercase query text
        
        Returns:
            Detected QueryIntent
        """
        # Availability check keywords
        availability_keywords = [
            'free', 'available', 'busy', 'open', 'have time',
            'can i', 'am i free', 'do i have time'
        ]
        if any(keyword in query_lower for keyword in availability_keywords):
            return QueryIntent.AVAILABILITY_CHECK
        
        # Conflict detection keywords
        conflict_keywords = [
            'conflict', 'overlap', 'double booked', 'clash',
            'conflicting', 'overlapping'
        ]
        if any(keyword in query_lower for keyword in conflict_keywords):
            return QueryIntent.CONFLICT_DETECTION
        
        # Schedule summary keywords
        schedule_keywords = [
            'schedule', 'meetings', 'events', 'appointments',
            'what do i have', 'what\'s on', 'what\'s coming up',
            'upcoming', 'this week', 'next week'
        ]
        if any(keyword in query_lower for keyword in schedule_keywords):
            return QueryIntent.SCHEDULE_SUMMARY
        
        # Event details keywords
        event_keywords = [
            'details', 'about', 'tell me about', 'what is',
            'when is', 'where is'
        ]
        if any(keyword in query_lower for keyword in event_keywords):
            return QueryIntent.EVENT_DETAILS
        
        return QueryIntent.GENERAL
    
    def _extract_days_ahead(self, query_lower: str) -> Optional[int]:
        """
        Extract number of days ahead from query.
        
        Args:
            query_lower: Lowercase query text
        
        Returns:
            Number of days or None
        """
        import re
        
        # Look for "next N days" or "N days"
        pattern = r'(?:next\s+)?(\d+)\s+days?'
        match = re.search(pattern, query_lower)
        if match:
            return int(match.group(1))
        
        # Look for week references
        if 'week' in query_lower:
            if 'next week' in query_lower:
                return 7
            elif 'this week' in query_lower:
                return 7
        
        return None
    
    def _extract_event_count(self, query_lower: str) -> Optional[int]:
        """
        Extract desired number of events from query.
        
        Args:
            query_lower: Lowercase query text
        
        Returns:
            Number of events or None
        """
        import re
        
        patterns = [
            r'(?:next|first|upcoming)\s+(\d+)\s+events?',
            r'(\d+)\s+events?',
            r'(\d+)\s+meetings?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                return int(match.group(1))
        
        return None
    
    def _extract_entities(self, query: str) -> Dict[str, List[str]]:
        """
        Extract entities from query (repo names, project names, people).
        
        Args:
            query: User query
        
        Returns:
            Dictionary with entity types and values
        """
        import re
        
        entities = {
            'repos': [],
            'projects': [],
            'people': []
        }
        
        # Extract repo names (owner/repo format)
        owner_repo_pattern = r'([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)'
        repo_matches = re.findall(owner_repo_pattern, query)
        if repo_matches:
            entities['repos'] = [f"{m[0]}/{m[1]}" for m in repo_matches]
        
        # Extract potential project/repo names (words with hyphens/underscores)
        project_pattern = r'\b([a-zA-Z0-9_-]{4,})\b'
        potential_projects = re.findall(project_pattern, query)
        
        # Filter out common words
        common_words = {
            'what', 'when', 'where', 'show', 'tell', 'me', 'my', 'the', 'this', 'that',
            'next', 'last', 'week', 'day', 'today', 'tomorrow', 'schedule', 'meeting',
            'events', 'calendar', 'github', 'repo', 'repository', 'repositories',
            'issue', 'issues', 'pr', 'pull', 'request', 'commits', 'deployment'
        }
        
        for word in potential_projects:
            word_lower = word.lower()
            if word_lower not in common_words and ('-' in word or '_' in word or len(word) > 5):
                if word not in entities['repos']:  # Don't duplicate
                    entities['projects'].append(word)
        
        return entities
    
    def _detect_multi_intent(self, query_lower: str) -> bool:
        """
        Detect if query has multiple intents (e.g., calendar + GitHub).
        
        Args:
            query_lower: Lowercase query
        
        Returns:
            True if multi-intent detected
        """
        calendar_keywords = ['meeting', 'schedule', 'calendar', 'event', 'available', 'free', 'busy']
        github_keywords = ['github', 'repo', 'repository', 'issue', 'pr', 'pull request', 'commit', 'deployment']
        
        has_calendar = any(kw in query_lower for kw in calendar_keywords)
        has_github = any(kw in query_lower for kw in github_keywords)
        
        return has_calendar and has_github
    
    def _detect_domain(self, query_lower: str) -> str:
        """
        Detect the primary domain of the query.
        
        Args:
            query_lower: Lowercase query
        
        Returns:
            'calendar', 'github', 'both', or 'general'
        """
        calendar_keywords = ['meeting', 'schedule', 'calendar', 'event', 'appointment', 'available', 'free', 'busy', 'conflict']
        github_keywords = ['github', 'repo', 'repository', 'issue', 'pr', 'pull request', 'commit', 'deployment', 'deploy']
        
        has_calendar = any(kw in query_lower for kw in calendar_keywords)
        has_github = any(kw in query_lower for kw in github_keywords)
        
        if has_calendar and has_github:
            return 'both'
        elif has_calendar:
            return 'calendar'
        elif has_github:
            return 'github'
        else:
            return 'general'
    
    def get_time_range_for_query(self, analysis: Dict) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Determine appropriate time range for calendar query based on analysis.
        
        Args:
            analysis: Query analysis result
        
        Returns:
            Tuple of (time_min, time_max) for calendar query
        """
        target_date = analysis.get('target_date')
        days_ahead = analysis.get('days_ahead')
        is_this_week = analysis.get('is_this_week', False)
        is_next_week = analysis.get('is_next_week', False)
        
        # Handle week queries specially
        if is_this_week:
            # This week: from today to end of this week (Sunday)
            time_min = self.base_date.replace(hour=0, minute=0, second=0, microsecond=0)
            days_to_sunday = 6 - self.base_date.weekday()  # Sunday is 6
            time_max = time_min + timedelta(days=days_to_sunday + 1)  # +1 to include Sunday
            return time_min, time_max
        
        if is_next_week:
            # Next week: from next Monday to next Sunday
            days_to_next_monday = (7 - self.base_date.weekday()) % 7
            if days_to_next_monday == 0:
                days_to_next_monday = 7  # If today is Monday, next week starts next Monday
            next_monday = self.base_date + timedelta(days=days_to_next_monday)
            time_min = next_monday.replace(hour=0, minute=0, second=0, microsecond=0)
            time_max = time_min + timedelta(days=7)  # Full week (Mon to Sun)
            return time_min, time_max
        
        if target_date:
            # Query is about a specific date - include full day (00:00:00 to 23:59:59)
            time_min = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            time_max = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            return time_min, time_max
        
        if days_ahead:
            # Query is about next N days
            time_min = self.base_date.replace(hour=0, minute=0, second=0, microsecond=0)
            time_max = time_min + timedelta(days=days_ahead)
            return time_min, time_max
        
        # Default: next 7 days
        time_min = self.base_date.replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = time_min + timedelta(days=7)
        return time_min, time_max

