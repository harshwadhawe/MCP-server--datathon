"""Multi-source context correlation engine for linking calendar and GitHub data."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict


class ContextCorrelator:
    """
    Correlates data from multiple sources (Calendar, GitHub) to find connections
    and provide intelligent context linking.
    """
    
    def __init__(self):
        """Initialize the correlator."""
        pass
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract entities (repo names, project names, people) from text.
        
        Args:
            text: Text to analyze
        
        Returns:
            Dictionary with entity types and values
        """
        entities = {
            'repos': [],
            'projects': [],
            'people': []
        }
        
        # Extract potential repo names (words with hyphens/underscores, or owner/repo format)
        repo_patterns = [
            r'([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)',  # owner/repo
            r'\b([A-Z][a-zA-Z0-9_-]{3,})\b',  # Capitalized words (project names)
        ]
        
        for pattern in repo_patterns:
            matches = re.findall(pattern, text)
            if matches:
                if isinstance(matches[0], tuple):
                    # owner/repo format
                    entities['repos'].extend([f"{m[0]}/{m[1]}" for m in matches])
                else:
                    entities['projects'].extend(matches)
        
        # Extract people names (capitalized words that might be names)
        # This is a simple heuristic - could be improved
        name_pattern = r'\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b'
        name_matches = re.findall(name_pattern, text)
        entities['people'] = [f"{m[0]} {m[1]}" for m in name_matches]
        
        return entities
    
    def correlate_calendar_github(
        self,
        calendar_events: List[Dict],
        github_repos: List[Dict],
        github_issues: List[Dict],
        github_prs: List[Dict]
    ) -> Dict[str, Any]:
        """
        Correlate calendar events with GitHub activity.
        
        Args:
            calendar_events: List of calendar events
            github_repos: List of GitHub repositories
            github_issues: List of GitHub issues
            github_prs: List of GitHub pull requests
        
        Returns:
            Dictionary with correlations and insights
        """
        correlations = {
            'event_repo_links': [],
            'suggestions': [],
            'insights': []
        }
        
        # Create repo name mapping
        repo_names = {}
        for repo in github_repos:
            full_name = repo.get('full_name', '')
            name = repo.get('name', '')
            repo_names[full_name.lower()] = repo
            repo_names[name.lower()] = repo
        
        # Analyze calendar events for repo/project mentions
        for event in calendar_events:
            event_text = f"{event.get('summary', '')} {event.get('description', '')}"
            entities = self.extract_entities(event_text)
            
            # Find matching repos
            for repo_name in entities['repos']:
                if repo_name.lower() in repo_names:
                    repo = repo_names[repo_name.lower()]
                    # Find related issues/PRs
                    related_issues = [
                        issue for issue in github_issues
                        if repo_name.lower() in issue.get('repository_url', '').lower()
                    ]
                    related_prs = [
                        pr for pr in github_prs
                        if repo_name.lower() in pr.get('head', {}).get('repo', {}).get('full_name', '').lower()
                    ]
                    
                    correlations['event_repo_links'].append({
                        'event': event.get('summary', ''),
                        'event_time': event.get('start', {}).get('dateTime', ''),
                        'repo': repo_name,
                        'related_issues': len(related_issues),
                        'related_prs': len(related_prs),
                        'open_issues': related_issues[:3],
                        'open_prs': related_prs[:3]
                    })
            
            # Check for project names
            for project in entities['projects']:
                # Try to match with repo names
                matching_repos = [
                    repo for repo in github_repos
                    if project.lower() in repo.get('name', '').lower() or
                       project.lower() in repo.get('description', '').lower()
                ]
                
                if matching_repos:
                    correlations['event_repo_links'].append({
                        'event': event.get('summary', ''),
                        'event_time': event.get('start', {}).get('dateTime', ''),
                        'project': project,
                        'matching_repos': [r.get('full_name') for r in matching_repos]
                    })
        
        # Generate suggestions
        correlations['suggestions'] = self._generate_suggestions(
            calendar_events, github_repos, github_issues, github_prs
        )
        
        # Generate insights
        correlations['insights'] = self._generate_insights(
            calendar_events, github_repos, github_issues, github_prs
        )
        
        return correlations
    
    def _generate_suggestions(
        self,
        events: List[Dict],
        repos: List[Dict],
        issues: List[Dict],
        prs: List[Dict]
    ) -> List[str]:
        """Generate proactive suggestions based on correlated data."""
        suggestions = []
        
        # Check for upcoming meetings with related GitHub activity
        now = datetime.now()
        upcoming_events = [
            e for e in events
            if self._is_upcoming(e, now)
        ]
        
        for event in upcoming_events[:5]:  # Check top 5 upcoming events
            event_text = f"{event.get('summary', '')} {event.get('description', '')}"
            entities = self.extract_entities(event_text)
            
            # If event mentions a repo/project, check for related activity
            for repo_name in entities['repos']:
                related_prs = [
                    pr for pr in prs
                    if repo_name.lower() in pr.get('head', {}).get('repo', {}).get('full_name', '').lower()
                ]
                
                if related_prs:
                    suggestions.append(
                        f"Upcoming meeting '{event.get('summary')}' mentions {repo_name}. "
                        f"There are {len(related_prs)} open PR(s) that might be relevant."
                    )
        
        # Check for PRs ready to merge when user has free time
        if prs:
            open_prs_count = len([pr for pr in prs if pr.get('state') == 'open'])
            if open_prs_count > 0:
                # Check if user has free time soon
                busy_times = self._get_busy_periods(events, now)
                if not busy_times:
                    suggestions.append(
                        f"You have {open_prs_count} open PR(s) and appear to have free time. "
                        "Consider reviewing them."
                    )
        
        return suggestions
    
    def _generate_insights(
        self,
        events: List[Dict],
        repos: List[Dict],
        issues: List[Dict],
        prs: List[Dict]
    ) -> List[str]:
        """Generate insights from correlated data."""
        insights = []
        
        # Activity correlation
        if events and repos:
            recent_events = [e for e in events if self._is_recent(e, datetime.now())]
            if recent_events:
                insights.append(
                    f"You have {len(recent_events)} recent calendar event(s) and "
                    f"{len(repos)} active repository/ies. Consider linking meeting notes to GitHub issues."
                )
        
        # Workload insights
        total_issues = len(issues)
        total_prs = len(prs)
        if total_issues + total_prs > 10:
            insights.append(
                f"You have {total_issues} open issue(s) and {total_prs} open PR(s). "
                "Consider prioritizing based on upcoming meetings."
            )
        
        return insights
    
    def _is_upcoming(self, event: Dict, now: datetime) -> bool:
        """Check if event is in the future."""
        start = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
        if not start:
            return False
        
        try:
            if 'T' in start:
                event_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            else:
                event_dt = datetime.fromisoformat(start)
            
            return event_dt.replace(tzinfo=None) > now
        except:
            return False
    
    def _is_recent(self, event: Dict, now: datetime, days: int = 7) -> bool:
        """Check if event is recent (within N days)."""
        start = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
        if not start:
            return False
        
        try:
            if 'T' in start:
                event_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            else:
                event_dt = datetime.fromisoformat(start)
            
            days_diff = (now - event_dt.replace(tzinfo=None)).days
            return 0 <= days_diff <= days
        except:
            return False
    
    def _get_busy_periods(self, events: List[Dict], now: datetime) -> List[Tuple[datetime, datetime]]:
        """Get list of busy time periods from events."""
        busy_periods = []
        
        for event in events:
            start = event.get('start', {}).get('dateTime')
            end = event.get('end', {}).get('dateTime')
            
            if start and end:
                try:
                    start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                    
                    if start_dt.replace(tzinfo=None) > now:
                        busy_periods.append((start_dt.replace(tzinfo=None), end_dt.replace(tzinfo=None)))
                except:
                    pass
        
        return busy_periods
    
    def format_correlations(self, correlations: Dict[str, Any]) -> str:
        """
        Format correlation data into a readable context string.
        
        Args:
            correlations: Correlation data from correlate_calendar_github
        
        Returns:
            Formatted string for AI context
        """
        parts = []
        
        # Event-Repo Links
        if correlations.get('event_repo_links'):
            parts.append("CALENDAR-GITHUB CORRELATIONS:")
            parts.append("-" * 50)
            
            for link in correlations['event_repo_links'][:5]:  # Limit to 5
                event_name = link.get('event', 'Unknown Event')
                repo_name = link.get('repo') or link.get('project', 'Unknown')
                
                correlation_line = f"  • {event_name} → {repo_name}"
                
                if link.get('related_issues', 0) > 0:
                    correlation_line += f" ({link.get('related_issues')} open issues)"
                if link.get('related_prs', 0) > 0:
                    correlation_line += f" ({link.get('related_prs')} open PRs)"
                
                parts.append(correlation_line)
            
            parts.append("")
        
        # Suggestions
        if correlations.get('suggestions'):
            parts.append("SUGGESTIONS:")
            parts.append("-" * 50)
            for suggestion in correlations['suggestions'][:3]:  # Top 3
                parts.append(f"  💡 {suggestion}")
            parts.append("")
        
        # Insights
        if correlations.get('insights'):
            parts.append("INSIGHTS:")
            parts.append("-" * 50)
            for insight in correlations['insights'][:3]:  # Top 3
                parts.append(f"  📊 {insight}")
            parts.append("")
        
        return "\n".join(parts) if parts else ""

