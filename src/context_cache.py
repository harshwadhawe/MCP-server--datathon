"""Context caching system for MCP server to reduce API calls and improve performance."""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict


class ContextCache:
    """
    Intelligent caching system for calendar and GitHub data.
    Implements TTL-based caching with smart invalidation.
    """
    
    def __init__(self):
        """Initialize the cache."""
        # Calendar cache: key -> (data, timestamp, ttl)
        self.calendar_cache: Dict[str, Tuple[Any, float, int]] = {}
        
        # GitHub cache: key -> (data, timestamp, ttl)
        self.github_cache: Dict[str, Tuple[Any, float, int]] = {}
        
        # Query result cache: query_hash -> (context, timestamp, ttl)
        self.query_cache: Dict[str, Tuple[str, float, int]] = {}
        
        # Default TTLs (in seconds)
        self.calendar_ttl = 300  # 5 minutes
        self.github_repos_ttl = 3600  # 1 hour
        self.github_issues_ttl = 300  # 5 minutes
        self.github_prs_ttl = 300  # 5 minutes
        self.github_deployments_ttl = 600  # 10 minutes
        self.query_ttl = 180  # 3 minutes
    
    def _get_cache_key(self, prefix: str, **kwargs) -> str:
        """Generate a cache key from parameters."""
        key_parts = [prefix]
        for k, v in sorted(kwargs.items()):
            if v is not None:
                key_parts.append(f"{k}:{v}")
        return "|".join(key_parts)
    
    def _is_expired(self, timestamp: float, ttl: int) -> bool:
        """Check if cached data is expired."""
        return time.time() - timestamp > ttl
    
    def get_calendar_events(
        self,
        time_min: Optional[datetime],
        time_max: Optional[datetime],
        calendar_ids: Optional[List[str]] = None
    ) -> Optional[List[Dict]]:
        """
        Get calendar events from cache if available and not expired.
        
        Args:
            time_min: Start time for query
            time_max: End time for query
            calendar_ids: List of calendar IDs (None for all)
        
        Returns:
            Cached events or None if not in cache or expired
        """
        cache_key = self._get_cache_key(
            "calendar_events",
            time_min=time_min.isoformat() if time_min else None,
            time_max=time_max.isoformat() if time_max else None,
            calendars=",".join(sorted(calendar_ids)) if calendar_ids else "all"
        )
        
        if cache_key in self.calendar_cache:
            data, timestamp, ttl = self.calendar_cache[cache_key]
            if not self._is_expired(timestamp, ttl):
                return data
            else:
                # Remove expired entry
                del self.calendar_cache[cache_key]
        
        return None
    
    def set_calendar_events(
        self,
        time_min: Optional[datetime],
        time_max: Optional[datetime],
        events: List[Dict],
        calendar_ids: Optional[List[str]] = None,
        ttl: Optional[int] = None
    ):
        """Cache calendar events."""
        cache_key = self._get_cache_key(
            "calendar_events",
            time_min=time_min.isoformat() if time_min else None,
            time_max=time_max.isoformat() if time_max else None,
            calendars=",".join(sorted(calendar_ids)) if calendar_ids else "all"
        )
        
        self.calendar_cache[cache_key] = (
            events,
            time.time(),
            ttl or self.calendar_ttl
        )
    
    def get_github_data(
        self,
        data_type: str,
        **kwargs
    ) -> Optional[Any]:
        """
        Get GitHub data from cache.
        
        Args:
            data_type: Type of data ('repos', 'issues', 'prs', 'deployments', 'commits')
            **kwargs: Additional parameters for cache key
        
        Returns:
            Cached data or None
        """
        # Determine TTL based on data type
        ttl_map = {
            'repos': self.github_repos_ttl,
            'issues': self.github_issues_ttl,
            'prs': self.github_prs_ttl,
            'deployments': self.github_deployments_ttl,
            'commits': self.github_issues_ttl,  # Same as issues
            'user_info': self.github_repos_ttl,  # Same as repos
        }
        
        cache_key = self._get_cache_key(f"github_{data_type}", **kwargs)
        
        if cache_key in self.github_cache:
            data, timestamp, ttl = self.github_cache[cache_key]
            if not self._is_expired(timestamp, ttl):
                return data
            else:
                del self.github_cache[cache_key]
        
        return None
    
    def set_github_data(
        self,
        data_type: str,
        data: Any,
        ttl: Optional[int] = None,
        **kwargs
    ):
        """Cache GitHub data."""
        ttl_map = {
            'repos': self.github_repos_ttl,
            'issues': self.github_issues_ttl,
            'prs': self.github_prs_ttl,
            'deployments': self.github_deployments_ttl,
            'commits': self.github_issues_ttl,
            'user_info': self.github_repos_ttl,
        }
        
        cache_key = self._get_cache_key(f"github_{data_type}", **kwargs)
        
        self.github_cache[cache_key] = (
            data,
            time.time(),
            ttl or ttl_map.get(data_type, 300)
        )
    
    def get_query_result(self, query: str) -> Optional[str]:
        """Get cached query result."""
        # Simple hash of query (could be improved)
        query_hash = str(hash(query.lower().strip()))
        
        if query_hash in self.query_cache:
            context, timestamp, ttl = self.query_cache[query_hash]
            if not self._is_expired(timestamp, ttl):
                return context
            else:
                del self.query_cache[query_hash]
        
        return None
    
    def set_query_result(self, query: str, context: str, ttl: Optional[int] = None):
        """Cache query result."""
        query_hash = str(hash(query.lower().strip()))
        
        self.query_cache[query_hash] = (
            context,
            time.time(),
            ttl or self.query_ttl
        )
    
    def invalidate_calendar_cache(self, pattern: Optional[str] = None):
        """
        Invalidate calendar cache.
        
        Args:
            pattern: Optional pattern to match cache keys (None = invalidate all)
        """
        if pattern is None:
            self.calendar_cache.clear()
        else:
            keys_to_remove = [k for k in self.calendar_cache.keys() if pattern in k]
            for key in keys_to_remove:
                del self.calendar_cache[key]
    
    def invalidate_github_cache(self, data_type: Optional[str] = None):
        """
        Invalidate GitHub cache.
        
        Args:
            data_type: Optional data type to invalidate (None = invalidate all)
        """
        if data_type is None:
            self.github_cache.clear()
        else:
            prefix = f"github_{data_type}"
            keys_to_remove = [k for k in self.github_cache.keys() if k.startswith(prefix)]
            for key in keys_to_remove:
                del self.github_cache[key]
    
    def clear_all(self):
        """Clear all caches."""
        self.calendar_cache.clear()
        self.github_cache.clear()
        self.query_cache.clear()
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            'calendar_entries': len(self.calendar_cache),
            'github_entries': len(self.github_cache),
            'query_entries': len(self.query_cache),
            'total_entries': len(self.calendar_cache) + len(self.github_cache) + len(self.query_cache)
        }

