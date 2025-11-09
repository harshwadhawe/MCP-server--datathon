"""Context ranking and relevance scoring for prioritizing context items."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import re


class ContextRanker:
    """
    Ranks context items by relevance to the query.
    Helps prioritize which information is most important.
    """
    
    def __init__(self):
        """Initialize the ranker."""
        pass
    
    def rank_events(
        self,
        events: List[Dict],
        query: str,
        max_items: Optional[int] = None
    ) -> List[Dict]:
        """
        Rank calendar events by relevance to query.
        
        Args:
            events: List of calendar events
            query: User query
            max_items: Maximum number of items to return
        
        Returns:
            Ranked list of events
        """
        if not events:
            return []
        
        # Score each event
        scored_events = []
        for event in events:
            score = self._score_event(event, query)
            scored_events.append((score, event))
        
        # Sort by score (highest first)
        scored_events.sort(key=lambda x: x[0], reverse=True)
        
        # Return top N
        if max_items:
            return [event for _, event in scored_events[:max_items]]
        else:
                return [event for _, event in scored_events]
    
    def rank_github_items(
        self,
        items: List[Dict],
        item_type: str,
        query: str,
        max_items: Optional[int] = None
    ) -> List[Dict]:
        """
        Rank GitHub items (issues, PRs, repos) by relevance.
        
        Args:
            items: List of GitHub items
            item_type: Type of item ('issue', 'pr', 'repo', 'deployment')
            query: User query
            max_items: Maximum number of items to return
        
        Returns:
            Ranked list of items
        """
        if not items:
            return []
        
        # Score each item
        scored_items = []
        for item in items:
            score = self._score_github_item(item, item_type, query)
            scored_items.append((score, item))
        
        # Sort by score
        scored_items.sort(key=lambda x: x[0], reverse=True)
        
        # Return top N
        if max_items:
            return [item for _, item in scored_items[:max_items]]
        else:
            return [item for _, item in scored_items]
    
    def _score_event(self, event: Dict, query: str) -> float:
        """
        Score an event's relevance to the query.
        
        Returns:
            Relevance score (0.0 to 1.0)
        """
        score = 0.0
        query_lower = query.lower()
        
        # Check title match
        title = event.get('summary', '').lower()
        if any(word in title for word in query_lower.split() if len(word) > 3):
            score += 0.3
        
        # Check description match
        description = (event.get('description', '') or '').lower()
        if any(word in description for word in query_lower.split() if len(word) > 3):
            score += 0.2
        
        # Recency boost (events closer to now get higher score)
        start = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
        if start:
            try:
                if 'T' in start:
                    event_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                else:
                    event_dt = datetime.fromisoformat(start)
                
                now = datetime.now()
                days_diff = abs((event_dt.replace(tzinfo=None) - now).days)
                
                # Boost for events today/tomorrow
                if days_diff == 0:
                    score += 0.3
                elif days_diff == 1:
                    score += 0.2
                elif days_diff <= 7:
                    score += 0.1
            except:
                pass
        
        # Importance keywords boost
        important_keywords = ['meeting', 'standup', 'review', 'deadline', 'urgent']
        event_text = f"{title} {description}"
        if any(keyword in event_text for keyword in important_keywords):
            score += 0.1
        
        # Normalize to 0-1 range
        return min(score, 1.0)
    
    def _score_github_item(self, item: Dict, item_type: str, query: str) -> float:
        """
        Score a GitHub item's relevance to the query.
        
        Returns:
            Relevance score (0.0 to 1.0)
        """
        score = 0.0
        query_lower = query.lower()
        
        # Title match
        title = (item.get('title', '') or '').lower()
        if any(word in title for word in query_lower.split() if len(word) > 3):
            score += 0.4
        
        # Body/description match
        body = (item.get('body', '') or item.get('description', '') or '').lower()
        if any(word in body for word in query_lower.split() if len(word) > 3):
            score += 0.2
        
        # State boost (open items are usually more relevant)
        if item.get('state') == 'open':
            score += 0.2
        
        # Recency boost
        updated = item.get('updated_at') or item.get('created_at', '')
        if updated:
            try:
                updated_dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                days_ago = (datetime.now() - updated_dt.replace(tzinfo=None)).days
                
                if days_ago == 0:
                    score += 0.2
                elif days_ago <= 7:
                    score += 0.1
            except:
                pass
        
        # Labels boost (for issues/PRs)
        labels = item.get('labels', [])
        if labels:
            label_names = [l.get('name', '').lower() for l in labels if isinstance(l, dict)]
            # Boost for important labels
            important_labels = ['urgent', 'critical', 'bug', 'blocker', 'priority']
            if any(label in important_labels for label in label_names):
                score += 0.1
        
        # Normalize
        return min(score, 1.0)
    
    def rank_context_sections(
        self,
        context_sections: Dict[str, str],
        query: str
    ) -> List[Tuple[str, str, float]]:
        """
        Rank different context sections by relevance.
        
        Args:
            context_sections: Dictionary mapping section names to content
            query: User query
        
        Returns:
            List of (section_name, content, score) tuples, sorted by score
        """
        scored_sections = []
        
        for section_name, content in context_sections.items():
            score = self._score_section(section_name, content, query)
            scored_sections.append((section_name, content, score))
        
        # Sort by score
        scored_sections.sort(key=lambda x: x[2], reverse=True)
        
        return scored_sections
    
    def _score_section(self, section_name: str, content: str, query: str) -> float:
        """Score a context section's relevance."""
        score = 0.0
        query_lower = query.lower()
        
        # Section name match
        if any(word in section_name.lower() for word in query_lower.split()):
            score += 0.5
        
        # Content match
        content_lower = content.lower()
        query_words = [w for w in query_lower.split() if len(w) > 3]
        matches = sum(1 for word in query_words if word in content_lower)
        if matches > 0:
            score += min(0.3 * (matches / len(query_words)), 0.3)
        
        # Length penalty (shorter, more focused content is better)
        if len(content) < 500:
            score += 0.1
        elif len(content) > 2000:
            score -= 0.1
        
        return min(score, 1.0)

