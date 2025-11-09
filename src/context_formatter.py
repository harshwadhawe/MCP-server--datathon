"""Context formatter for structuring calendar data into AI-friendly context."""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
from .utils import format_event_time


class ContextFormatter:
    """Formats calendar data into concise, useful context strings."""
    
    def format_calendar_context(
        self,
        events: List[Dict],
        analysis: Dict,
        availability: Optional[bool] = None,
        conflicts: Optional[List[Dict]] = None
    ) -> str:
        """
        Format calendar events into a context string for AI.
        
        Args:
            events: List of calendar events
            analysis: Query analysis result
            availability: Availability status (if checked)
            conflicts: List of conflicting events (if any)
        
        Returns:
            Formatted context string
        """
        if analysis.get('is_availability_check'):
            return self._format_availability_context(events, analysis, availability, conflicts)
        elif analysis.get('is_conflict_check'):
            return self._format_conflict_context(events, analysis, conflicts)
        elif analysis.get('is_schedule_summary'):
            return self._format_schedule_summary(events, analysis)
        else:
            return self._format_general_context(events, analysis)
    
    def _format_availability_context(
        self,
        events: List[Dict],
        analysis: Dict,
        availability: Optional[bool],
        conflicts: Optional[List[Dict]]
    ) -> str:
        """Format context for availability check queries."""
        target_date = analysis.get('target_date')
        time_ref = analysis.get('time')
        
        context_parts = []
        
        if target_date:
            date_str = target_date.strftime('%A, %B %d, %Y')
            context_parts.append(f"User's calendar for {date_str}:")
        else:
            context_parts.append("User's calendar:")
        
        if conflicts:
            conflict_details = []
            for event in conflicts:
                title = event.get('summary', 'Untitled Event')
                time_str = format_event_time(event)
                conflict_details.append(f"'{title}' ({time_str})")
            
            context_parts.append(f"Conflicting events: {', '.join(conflict_details)}")
            
            if availability is False:
                context_parts.append("User is NOT free at the requested time.")
            else:
                context_parts.append("User has conflicting events.")
        elif events:
            event_details = []
            for event in events[:5]:  # Limit to 5 events
                title = event.get('summary', 'Untitled Event')
                time_str = format_event_time(event)
                event_details.append(f"'{title}' ({time_str})")
            
            context_parts.append(f"Events: {', '.join(event_details)}")
            
            if availability is True:
                context_parts.append("User is free at the requested time.")
            else:
                context_parts.append("User has events scheduled.")
        else:
            context_parts.append("No events found.")
            if availability is True:
                context_parts.append("User is free.")
        
        return " ".join(context_parts)
    
    def _format_conflict_context(
        self,
        events: List[Dict],
        analysis: Dict,
        conflicts: Optional[List[Dict]]
    ) -> str:
        """Format context for conflict detection queries."""
        target_date = analysis.get('target_date')
        
        context_parts = []
        
        if target_date:
            date_str = target_date.strftime('%A, %B %d, %Y')
            context_parts.append(f"Conflict check for {date_str}:")
        else:
            context_parts.append("Conflict check:")
        
        if conflicts:
            conflict_details = []
            for event in conflicts:
                title = event.get('summary', 'Untitled Event')
                time_str = format_event_time(event)
                conflict_details.append(f"'{title}' ({time_str})")
            
            context_parts.append(f"Found {len(conflicts)} conflict(s): {', '.join(conflict_details)}")
        else:
            context_parts.append("No conflicts detected.")
            
            if events:
                event_count = len(events)
                context_parts.append(f"You have {event_count} event(s) scheduled:")
                event_list = []
                for event in events[:10]:
                    title = event.get('summary', 'Untitled Event')
                    time_str = format_event_time(event)
                    calendar_name = event.get('calendar_name', '')
                    cal_info = f" [{calendar_name}]" if calendar_name else ""
                    event_list.append(f"'{title}' ({time_str}){cal_info}")
                context_parts.append("; ".join(event_list))
        
        return " ".join(context_parts)
    
    def _format_schedule_summary(
        self,
        events: List[Dict],
        analysis: Dict
    ) -> str:
        """Format context for schedule summary queries - structured for easy parsing."""
        target_date = analysis.get('target_date')
        days_ahead = analysis.get('days_ahead')
        is_this_week = analysis.get('is_this_week', False)
        is_next_week = analysis.get('is_next_week', False)
        
        context_parts = []
        
        # Add clear header with date range
        if target_date:
            date_str = target_date.strftime('%A, %B %d, %Y')
            context_parts.append(f"SCHEDULE FOR: {date_str}\n")
        elif is_this_week:
            context_parts.append("SCHEDULE FOR: THIS WEEK\n")
        elif is_next_week:
            context_parts.append("SCHEDULE FOR: NEXT WEEK\n")
        elif days_ahead:
            context_parts.append(f"SCHEDULE FOR: NEXT {days_ahead} DAYS\n")
        else:
            context_parts.append("UPCOMING SCHEDULE\n")
        
        if not events:
            context_parts.append("No events scheduled for this period.")
            return "\n".join(context_parts)
        
        # Group events by date with detailed formatting
        events_by_date = {}
        for event in events:
            start = event.get('start', {})
            event_time = start.get('dateTime') or start.get('date')
            
            if event_time:
                try:
                    if 'T' in event_time:
                        event_dt = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
                    else:
                        event_dt = datetime.fromisoformat(event_time)
                    
                    date_key = event_dt.date()
                    if date_key not in events_by_date:
                        events_by_date[date_key] = []
                    events_by_date[date_key].append(event)
                except Exception:
                    continue
        
        # Format by date with clear structure
        for date_key in sorted(events_by_date.keys()):
            date_events = events_by_date[date_key]
            date_str = date_key.strftime('%A, %B %d, %Y')
            context_parts.append(f"\n{date_str}:")
            context_parts.append("-" * 50)
            
            # Sort events by time
            sorted_events = sorted(date_events, key=lambda e: self._get_event_datetime(e))
            
            for i, event in enumerate(sorted_events, 1):
                title = event.get('summary', 'Untitled Event')
                time_str = format_event_time(event)
                location = event.get('location', '')
                description = event.get('description', '')
                calendar_name = event.get('calendar_name', '')
                
                event_line = f"  {i}. {title} - {time_str}"
                if calendar_name:
                    event_line += f" [Calendar: {calendar_name}]"
                if location:
                    event_line += f" | Location: {location}"
                if description:
                    desc_short = description[:100] + "..." if len(description) > 100 else description
                    event_line += f" | Notes: {desc_short}"
                
                context_parts.append(event_line)
        
        context_parts.append(f"\nTOTAL EVENTS: {len(events)}")
        
        return "\n".join(context_parts)
    
    def _get_event_datetime(self, event: Dict) -> datetime:
        """Get event datetime for sorting."""
        start = event.get('start', {})
        event_time = start.get('dateTime') or start.get('date')
        
        if event_time:
            try:
                if 'T' in event_time:
                    return datetime.fromisoformat(event_time.replace('Z', '+00:00'))
                else:
                    return datetime.fromisoformat(event_time)
            except Exception:
                pass
        
        return datetime.min
    
    def _format_general_context(
        self,
        events: List[Dict],
        analysis: Dict
    ) -> str:
        """Format context for general queries - structured format."""
        if not events:
            return "No calendar events found for the requested time period."
        
        context_parts = [f"CALENDAR EVENTS ({len(events)} total):\n"]
        
        # Group by date for better organization
        events_by_date = {}
        for event in events:
            start = event.get('start', {})
            event_time = start.get('dateTime') or start.get('date')
            
            if event_time:
                try:
                    if 'T' in event_time:
                        event_dt = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
                    else:
                        event_dt = datetime.fromisoformat(event_time)
                    
                    date_key = event_dt.date()
                    if date_key not in events_by_date:
                        events_by_date[date_key] = []
                    events_by_date[date_key].append(event)
                except Exception:
                    continue
        
        # Format by date
        for date_key in sorted(events_by_date.keys()):
            date_events = events_by_date[date_key]
            date_str = date_key.strftime('%A, %B %d, %Y')
            context_parts.append(f"\n{date_str}:")
            context_parts.append("-" * 50)
            
            # Sort by time
            sorted_events = sorted(date_events, key=lambda e: self._get_event_datetime(e))
            
            for i, event in enumerate(sorted_events, 1):
                title = event.get('summary', 'Untitled Event')
                time_str = format_event_time(event)
                location = event.get('location', '')
                description = event.get('description', '')
                calendar_name = event.get('calendar_name', '')
                
                event_line = f"  {i}. {title} - {time_str}"
                if calendar_name:
                    event_line += f" [Calendar: {calendar_name}]"
                if location:
                    event_line += f" | Location: {location}"
                if description:
                    desc_short = description[:100] + "..." if len(description) > 100 else description
                    event_line += f" | Notes: {desc_short}"
                
                context_parts.append(event_line)
        
        return "\n".join(context_parts)
    
    def format_event_summary(self, event: Dict) -> str:
        """
        Format a single event into a summary string.
        
        Args:
            event: Calendar event dictionary
        
        Returns:
            Formatted event summary
        """
        title = event.get('summary', 'Untitled Event')
        time_str = format_event_time(event)
        location = event.get('location', '')
        description = event.get('description', '')
        
        parts = [f"'{title}' - {time_str}"]
        
        if location:
            parts.append(f"Location: {location}")
        
        if description:
            # Truncate long descriptions
            desc = description[:100] + "..." if len(description) > 100 else description
            parts.append(f"Description: {desc}")
        
        return " | ".join(parts)

