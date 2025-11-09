"""Context summarization and compression for efficient AI context delivery."""

from datetime import datetime
from typing import Dict, List, Optional, Tuple
import re


class ContextSummarizer:
    """
    Intelligently summarizes and compresses context data to reduce token usage
    while maintaining essential information.
    """
    
    def __init__(self, max_tokens: int = 2000):
        """
        Initialize the summarizer.
        
        Args:
            max_tokens: Maximum tokens for summarized context
        """
        self.max_tokens = max_tokens
        # Rough estimate: 1 token ≈ 4 characters
        self.chars_per_token = 4
    
    def summarize_events(
        self,
        events: List[Dict],
        max_items: Optional[int] = None,
        priority: str = "time"
    ) -> List[Dict]:
        """
        Summarize calendar events, keeping most important ones.
        
        Args:
            events: List of calendar events
            max_items: Maximum number of events to keep (None = auto)
            priority: Priority method ('time', 'recent', 'importance')
        
        Returns:
            Summarized list of events
        """
        if not events:
            return []
        
        # Auto-determine max_items if not specified
        if max_items is None:
            # Estimate: each event ~100 chars = ~25 tokens
            max_items = min(len(events), self.max_tokens // 25)
        
        # Sort by priority
        if priority == "time":
            # Sort by start time (upcoming first)
            sorted_events = sorted(
                events,
                key=lambda e: self._get_event_datetime(e)
            )
        elif priority == "recent":
            # Most recent first
            now = datetime.now()
            sorted_events = sorted(
                events,
                key=lambda e: abs((self._get_event_datetime(e) - now).total_seconds()),
                reverse=True
            )
        else:
            sorted_events = events
        
        # Take top N and simplify
        summarized = []
        for event in sorted_events[:max_items]:
            simplified = self._simplify_event(event)
            summarized.append(simplified)
        
        return summarized
    
    def summarize_github_data(
        self,
        repos: Optional[List[Dict]] = None,
        issues: Optional[List[Dict]] = None,
        prs: Optional[List[Dict]] = None,
        deployments: Optional[List[Dict]] = None
    ) -> Dict[str, List[Dict]]:
        """
        Summarize GitHub data, keeping most relevant items.
        
        Args:
            repos: List of repositories
            issues: List of issues
            prs: List of pull requests
            deployments: List of deployments
        
        Returns:
            Dictionary with summarized data
        """
        summarized = {}
        
        if repos:
            # Keep top repos (by activity/recency)
            summarized['repos'] = self._summarize_repos(repos)
        
        if issues:
            # Keep most urgent/recent issues
            summarized['issues'] = self._summarize_issues(issues)
        
        if prs:
            # Keep most recent/important PRs
            summarized['prs'] = self._summarize_prs(prs)
        
        if deployments:
            # Keep recent deployments
            summarized['deployments'] = self._summarize_deployments(deployments)
        
        return summarized
    
    def compress_context(
        self,
        context: str,
        target_length: Optional[int] = None
    ) -> str:
        """
        Compress a context string while preserving key information.
        
        Args:
            context: Full context string
            target_length: Target character length (None = use max_tokens)
        
        Returns:
            Compressed context
        """
        if target_length is None:
            target_length = self.max_tokens * self.chars_per_token
        
        if len(context) <= target_length:
            return context
        
        # Split into lines and prioritize
        lines = context.split('\n')
        important_lines = []
        less_important = []
        
        for line in lines:
            # Prioritize lines with key information
            if any(keyword in line.lower() for keyword in [
                'error', 'conflict', 'urgent', 'important', 'blocking',
                'today', 'tomorrow', 'now', 'deadline'
            ]):
                important_lines.append(line)
            else:
                less_important.append(line)
        
        # Build compressed version
        compressed = []
        current_length = 0
        
        # Add important lines first
        for line in important_lines:
            if current_length + len(line) <= target_length * 0.7:  # Reserve 70% for important
                compressed.append(line)
                current_length += len(line)
        
        # Add less important lines if space allows
        remaining = target_length - current_length
        for line in less_important:
            if len(line) <= remaining:
                compressed.append(line)
                remaining -= len(line)
            else:
                break
        
        result = '\n'.join(compressed)
        
        # If still too long, truncate intelligently
        if len(result) > target_length:
            result = result[:target_length - 50] + "\n[... context truncated ...]"
        
        return result
    
    def _simplify_event(self, event: Dict) -> Dict:
        """Simplify an event dictionary, removing unnecessary fields."""
        simplified = {
            'summary': event.get('summary', 'Untitled Event'),
            'start': event.get('start', {}),
            'calendar_name': event.get('calendar_name', '')
        }
        
        # Only include location if present
        if event.get('location'):
            simplified['location'] = event.get('location')
        
        # Truncate description
        if event.get('description'):
            desc = event.get('description', '')
            simplified['description'] = desc[:200] + "..." if len(desc) > 200 else desc
        
        return simplified
    
    def _summarize_repos(self, repos: List[Dict], max_count: int = 10) -> List[Dict]:
        """Summarize repository list."""
        # Sort by updated date (most recent first)
        sorted_repos = sorted(
            repos,
            key=lambda r: r.get('updated_at', ''),
            reverse=True
        )
        
        # Simplify each repo
        summarized = []
        for repo in sorted_repos[:max_count]:
            simplified = {
                'full_name': repo.get('full_name', ''),
                'description': (repo.get('description', '') or '')[:100],
                'stargazers_count': repo.get('stargazers_count', 0),
                'language': repo.get('language', 'N/A')
            }
            summarized.append(simplified)
        
        return summarized
    
    def _summarize_issues(self, issues: List[Dict], max_count: int = 10) -> List[Dict]:
        """Summarize issues list."""
        # Sort by number (most recent first, typically)
        sorted_issues = sorted(
            issues,
            key=lambda i: i.get('number', 0),
            reverse=True
        )
        
        summarized = []
        for issue in sorted_issues[:max_count]:
            simplified = {
                'number': issue.get('number'),
                'title': issue.get('title', '')[:100],
                'state': issue.get('state', 'open')
            }
            summarized.append(simplified)
        
        return summarized
    
    def _summarize_prs(self, prs: List[Dict], max_count: int = 10) -> List[Dict]:
        """Summarize pull requests list."""
        # Sort by number
        sorted_prs = sorted(
            prs,
            key=lambda p: p.get('number', 0),
            reverse=True
        )
        
        summarized = []
        for pr in sorted_prs[:max_count]:
            simplified = {
                'number': pr.get('number'),
                'title': pr.get('title', '')[:100],
                'state': pr.get('state', 'open')
            }
            summarized.append(simplified)
        
        return summarized
    
    def _summarize_deployments(self, deployments: List[Dict], max_count: int = 10) -> List[Dict]:
        """Summarize deployments list."""
        # Sort by created date
        sorted_deployments = sorted(
            deployments,
            key=lambda d: d.get('created_at', ''),
            reverse=True
        )
        
        summarized = []
        for deployment in sorted_deployments[:max_count]:
            simplified = {
                'id': deployment.get('id'),
                'environment': deployment.get('environment', ''),
                'ref': deployment.get('ref', ''),
                'sha': deployment.get('sha', '')[:7] if deployment.get('sha') else ''
            }
            summarized.append(simplified)
        
        return summarized
    
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
            except:
                pass
        
        return datetime.min

