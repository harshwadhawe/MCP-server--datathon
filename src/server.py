"""Main MCP server implementation for Google Calendar and GitHub integration."""

import os
import sys
import re
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging (to stderr to avoid breaking JSON-RPC on stdout)
logger = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import Tool, TextContent
except ImportError:
    # Fallback for different MCP SDK versions
    try:
        from mcp import FastMCP
    except ImportError:
        raise ImportError(
            "MCP SDK not found. Please install it with: pip install mcp"
        )

from .calendar_client import CalendarClient
from .query_analyzer import QueryAnalyzer, QueryIntent
from .context_formatter import ContextFormatter
from .utils import format_event_time
from .context_cache import ContextCache
from .context_correlator import ContextCorrelator
from .context_summarizer import ContextSummarizer
from .context_ranker import ContextRanker

# Try to import Gemini client (optional)
try:
    from .gemini_client import GeminiClient
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    GeminiClient = None

# Try to import GitHub client (optional)
try:
    from .github_client import GitHubClient
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False
    GitHubClient = None

# Try to import Slack client (optional)
try:
    from .slack_client import SlackClient
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False
    SlackClient = None


# Initialize MCP server
mcp = FastMCP("Calendar & GitHub MCP Server")

# Initialize components
calendar_client: Optional[CalendarClient] = None
github_client: Optional[GitHubClient] = None
slack_client: Optional[SlackClient] = None
query_analyzer = QueryAnalyzer()
context_formatter = ContextFormatter()
gemini_client: Optional[GeminiClient] = None

# Initialize 2.0 components
context_cache = ContextCache()
context_correlator = ContextCorrelator()
context_summarizer = ContextSummarizer(max_tokens=2000)
context_ranker = ContextRanker()


def initialize_calendar_client():
    """Initialize the Google Calendar client."""
    global calendar_client
    if calendar_client is None:
        credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/credentials.json")
        token_path = os.getenv("GOOGLE_TOKEN_PATH", "config/token.json")
        try:
            # Suppress any potential stdout output during initialization
            original_stdout = sys.stdout
            try:
                sys.stdout = sys.stderr
                calendar_client = CalendarClient(credentials_path, token_path)
            finally:
                sys.stdout = original_stdout
        except Exception as e:
            # Write error to stderr instead of raising to avoid breaking JSON-RPC
            sys.stderr.write(f"Failed to initialize calendar client: {e}\n")
            raise RuntimeError(f"Failed to initialize calendar client: {e}")


def initialize_github_client():
    """Initialize the GitHub client."""
    global github_client
    if github_client is None:
        if not GITHUB_AVAILABLE:
            raise RuntimeError(
                "GitHub client not available. Install requests package and set GITHUB_TOKEN."
            )
        try:
            github_client = GitHubClient()
        except Exception as e:
            raise RuntimeError(f"Failed to initialize GitHub client: {e}")


def initialize_gemini_client():
    """Initialize the Gemini client."""
    global gemini_client
    if not GEMINI_AVAILABLE:
        raise RuntimeError("Gemini client not available. Install google-generativeai package.")
    
    if gemini_client is None:
        try:
            gemini_client = GeminiClient()
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Gemini client: {e}")


def initialize_slack_client():
    """Initialize the Slack client."""
    global slack_client
    if slack_client is None:
        if not SLACK_AVAILABLE:
            raise RuntimeError(
                "Slack client not available. Install slack-sdk package and set SLACK_USER_TOKEN."
            )
        try:
            slack_client = SlackClient()
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Slack client: {e}")


@mcp.tool()
def get_calendar_context(query: str) -> str:
    """
    Get calendar context for a user query. This is the main tool that analyzes
    the query, fetches relevant calendar data, and formats it as context.
    
    Args:
        query: User's natural language query about their calendar
    
    Returns:
        Formatted context string with calendar information
    """
    try:
        initialize_calendar_client()
        
        # Analyze the query
        analysis = query_analyzer.analyze(query)
        
        # Determine time range
        time_min, time_max = query_analyzer.get_time_range_for_query(analysis)
        
        # Fetch events from ALL calendars
        events = calendar_client.get_events_from_all_calendars(
            time_min=time_min,
            time_max=time_max,
            max_results=50
        )
        
        # Handle availability checks
        availability = None
        conflicts = None
        if analysis.get('is_availability_check'):
            target_date = analysis.get('target_date')
            time_ref = analysis.get('time')
            
            if target_date and time_ref:
                # Check availability at specific time
                hour, minute = time_ref
                start_time = target_date.replace(hour=hour, minute=minute)
                end_time = start_time + timedelta(hours=1)  # Default 1-hour window
                
                availability, conflicts = calendar_client.check_availability(
                    start_time, end_time
                )
            elif target_date:
                # Check availability for the whole day
                start_time = target_date.replace(hour=0, minute=0)
                end_time = start_time + timedelta(days=1)
                
                availability, conflicts = calendar_client.check_availability(
                    start_time, end_time
                )
        
        # Handle conflict detection
        if analysis.get('is_conflict_check'):
            target_date = analysis.get('target_date')
            if target_date:
                start_time = target_date.replace(hour=0, minute=0)
                end_time = start_time + timedelta(days=1)
                _, conflicts = calendar_client.check_availability(
                    start_time, end_time
                )
        
        # Format context
        context = context_formatter.format_calendar_context(
            events, analysis, availability, conflicts
        )
        
        return context
    
    except Exception as e:
        logger.error(f"Error in get_calendar_context: {e}", exc_info=True)
        return f"Error fetching calendar context: {str(e)}"


@mcp.tool()
def check_availability(date: str, time: Optional[str] = None, duration_hours: float = 1.0) -> str:
    """
    Check if the user is available at a specific date and time.
    
    Args:
        date: Date to check (YYYY-MM-DD format or natural language like "tomorrow")
        time: Time to check (HH:MM format or natural language like "2 PM")
        duration_hours: Duration of the time slot to check in hours (default: 1.0)
    
    Returns:
        Availability status and any conflicting events
    """
    try:
        initialize_calendar_client()
        
        # Parse date
        if date.lower() in ['today', 'tomorrow']:
            target_date = query_analyzer.base_date
            if date.lower() == 'tomorrow':
                target_date += timedelta(days=1)
        else:
            try:
                target_date = datetime.strptime(date, '%Y-%m-%d')
            except ValueError:
                # Try natural language parsing
                parsed = query_analyzer.analyze(f"on {date}")
                target_date = parsed.get('target_date') or query_analyzer.base_date
        
        # Parse time
        if time:
            if ':' in time:
                hour, minute = map(int, time.split(':'))
            else:
                # Try natural language parsing
                parsed = query_analyzer.analyze(f"at {time}")
                time_ref = parsed.get('time')
                if time_ref:
                    hour, minute = time_ref
                else:
                    hour, minute = 9, 0  # Default to 9 AM
        else:
            hour, minute = 9, 0  # Default to 9 AM
        
        start_time = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        end_time = start_time + timedelta(hours=duration_hours)
        
        # Check availability
        is_available, conflicts = calendar_client.check_availability(start_time, end_time)
        
        # Format response
        date_str = start_time.strftime('%A, %B %d, %Y at %I:%M %p')
        if is_available:
            return f"User is available on {date_str}."
        else:
            conflict_details = []
            for event in conflicts:
                title = event.get('summary', 'Untitled Event')
                time_str = format_event_time(event)
                conflict_details.append(f"'{title}' ({time_str})")
            return f"User is NOT available on {date_str}. Conflicting events: {', '.join(conflict_details)}"
    
    except Exception as e:
        logger.error(f"Error in check_availability: {e}", exc_info=True)
        return f"Error checking availability: {str(e)}"


@mcp.tool()
def get_upcoming_events(days: int = 7, max_results: int = 10) -> str:
    """
    Get upcoming calendar events.
    
    Args:
        days: Number of days to look ahead (default: 7)
        max_results: Maximum number of events to return (default: 10)
    
    Returns:
        Formatted list of upcoming events
    """
    try:
        initialize_calendar_client()
        
        events = calendar_client.get_upcoming_events(days=days, max_results=max_results)
        
        if not events:
            return f"No upcoming events in the next {days} days."
        
        # Format events with better details
        event_list = []
        for i, event in enumerate(events, 1):
            title = event.get('summary', 'Untitled Event')
            time_str = format_event_time(event)
            location = event.get('location', '')
            description = event.get('description', '')
            
            # Build event string
            event_str = f"{i}. '{title}' - {time_str}"
            if location:
                event_str += f" (Location: {location})"
            if description:
                # Truncate long descriptions
                desc = description[:100] + "..." if len(description) > 100 else description
                event_str += f"\n   Description: {desc}"
            
            event_list.append(event_str)
        
        result = f"Upcoming events in the next {days} days ({len(events)} total):\n\n" + "\n\n".join(event_list)
        return result
    
    except Exception as e:
        logger.error(f"Error in get_upcoming_events: {e}", exc_info=True)
        return f"Error fetching upcoming events: {str(e)}"


@mcp.tool()
def detect_conflicts(date: str) -> str:
    """
    Detect scheduling conflicts for a specific date.
    
    Args:
        date: Date to check (YYYY-MM-DD format or natural language like "tomorrow")
    
    Returns:
        Conflict detection results
    """
    try:
        initialize_calendar_client()
        
        # Parse date
        if date.lower() in ['today', 'tomorrow']:
            target_date = query_analyzer.base_date
            if date.lower() == 'tomorrow':
                target_date += timedelta(days=1)
        else:
            try:
                target_date = datetime.strptime(date, '%Y-%m-%d')
            except ValueError:
                parsed = query_analyzer.analyze(f"on {date}")
                target_date = parsed.get('target_date') or query_analyzer.base_date
        
        start_time = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = start_time + timedelta(days=1)
        
        # Get all events for the day
        events = calendar_client.get_events_for_date(target_date)
        
        # Check for overlapping events
        conflicts = []
        for i, event1 in enumerate(events):
            start1 = event1.get('start', {}).get('dateTime') or event1.get('start', {}).get('date')
            end1 = event1.get('end', {}).get('dateTime') or event1.get('end', {}).get('date')
            
            if not start1 or 'T' not in start1:
                continue
            
            try:
                dt_start1 = datetime.fromisoformat(start1.replace('Z', '+00:00'))
                dt_end1 = datetime.fromisoformat(end1.replace('Z', '+00:00'))
                
                for j, event2 in enumerate(events[i+1:], i+1):
                    start2 = event2.get('start', {}).get('dateTime') or event2.get('start', {}).get('date')
                    end2 = event2.get('end', {}).get('dateTime') or event2.get('end', {}).get('date')
                    
                    if not start2 or 'T' not in start2:
                        continue
                    
                    dt_start2 = datetime.fromisoformat(start2.replace('Z', '+00:00'))
                    dt_end2 = datetime.fromisoformat(end2.replace('Z', '+00:00'))
                    
                    # Check for overlap
                    if not (dt_end1 <= dt_start2 or dt_start1 >= dt_end2):
                        conflicts.append((event1, event2))
            except Exception:
                continue
        
        # Format response
        date_str = target_date.strftime('%A, %B %d, %Y')
        if not conflicts:
            if events:
                return f"No conflicts detected for {date_str}. You have {len(events)} event(s) scheduled."
            else:
                return f"No conflicts detected for {date_str}. No events scheduled."
        else:
            conflict_details = []
            for event1, event2 in conflicts:
                title1 = event1.get('summary', 'Untitled Event')
                title2 = event2.get('summary', 'Untitled Event')
                time1 = format_event_time(event1)
                time2 = format_event_time(event2)
                conflict_details.append(f"'{title1}' ({time1}) conflicts with '{title2}' ({time2})")
            
            return f"Found {len(conflicts)} conflict(s) on {date_str}:\n" + "\n".join(f"- {c}" for c in conflict_details)
    
    except Exception as e:
        logger.error(f"Error in detect_conflicts: {e}", exc_info=True)
        return f"Error detecting conflicts: {str(e)}"


@mcp.tool()
def get_github_issues(owner: str, repo: str, state: str = "open", assignee: Optional[str] = None) -> str:
    """
    Get issues for a GitHub repository.
    
    Args:
        owner: Repository owner (username or organization)
        repo: Repository name
        state: Issue state (open, closed, all) - default: open)
        assignee: Filter by assignee username (optional)
    
    Returns:
        Formatted list of issues
    """
    try:
        initialize_github_client()
        
        issues = github_client.get_issues(owner, repo, state=state, assignee=assignee, per_page=30)
        
        if not issues:
            return f"No {state} issues found in {owner}/{repo}."
        
        result_parts = [f"Issues in {owner}/{repo} ({len(issues)} {state}):\n"]
        
        for i, issue in enumerate(issues, 1):
            title = issue.get('title', 'Untitled')
            number = issue.get('number', '?')
            state_icon = "✓" if state == "closed" else "○"
            assignees = [a.get('login', '') for a in issue.get('assignees', [])]
            labels = [l.get('name', '') for l in issue.get('labels', [])]
            
            result_parts.append(f"{i}. {state_icon} #{number}: {title}")
            if assignees:
                result_parts.append(f"   Assignees: {', '.join(assignees)}")
            if labels:
                result_parts.append(f"   Labels: {', '.join(labels)}")
            result_parts.append(f"   URL: {issue.get('html_url', '')}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_github_issues: {e}", exc_info=True)
        return f"Error fetching GitHub issues: {str(e)}"


@mcp.tool()
def get_github_pull_requests(owner: str, repo: str, state: str = "open") -> str:
    """
    Get pull requests for a GitHub repository.
    
    Args:
        owner: Repository owner (username or organization)
        repo: Repository name
        state: PR state (open, closed, all - default: open)
    
    Returns:
        Formatted list of pull requests
    """
    try:
        initialize_github_client()
        
        prs = github_client.get_pull_requests(owner, repo, state=state, per_page=30)
        
        if not prs:
            return f"No {state} pull requests found in {owner}/{repo}."
        
        result_parts = [f"Pull Requests in {owner}/{repo} ({len(prs)} {state}):\n"]
        
        for i, pr in enumerate(prs, 1):
            title = pr.get('title', 'Untitled')
            number = pr.get('number', '?')
            author = pr.get('user', {}).get('login', 'unknown')
            state_icon = "✓" if state == "closed" else "○"
            
            result_parts.append(f"{i}. {state_icon} #{number}: {title}")
            result_parts.append(f"   Author: {author}")
            result_parts.append(f"   URL: {pr.get('html_url', '')}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_github_pull_requests: {e}", exc_info=True)
        return f"Error fetching GitHub pull requests: {str(e)}"


@mcp.tool()
def get_github_repositories(username: Optional[str] = None) -> str:
    """
    Get repositories for a GitHub user.
    
    Args:
        username: GitHub username (optional, defaults to authenticated user)
    
    Returns:
        Formatted list of repositories
    """
    try:
        initialize_github_client()
        
        repos = github_client.get_repositories(username, per_page=30)
        
        if not repos:
            return f"No repositories found for {username or 'authenticated user'}."
        
        result_parts = [f"Repositories ({len(repos)} total):\n"]
        
        for i, repo in enumerate(repos, 1):
            name = repo.get('name', 'Unknown')
            full_name = repo.get('full_name', '')
            stars = repo.get('stargazers_count', 0)
            language = repo.get('language', 'N/A')
            description = repo.get('description', '') or 'No description'
            
            result_parts.append(f"{i}. {full_name}")
            result_parts.append(f"   ⭐ {stars} | {language}")
            result_parts.append(f"   {description[:100]}")
            result_parts.append(f"   URL: {repo.get('html_url', '')}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_github_repositories: {e}", exc_info=True)
        return f"Error fetching GitHub repositories: {str(e)}"


@mcp.tool()
def get_github_deployments(owner: Optional[str] = None, repo: Optional[str] = None, environment: Optional[str] = None) -> str:
    """
    Get deployments for GitHub repositories.
    
    Args:
        owner: Repository owner (optional, if not provided, fetches from all user repos)
        repo: Repository name (optional, if not provided, fetches from all user repos)
        environment: Filter by environment (e.g., 'production', 'staging') - optional
    
    Returns:
        Formatted list of deployments
    """
    try:
        initialize_github_client()
        
        if owner and repo:
            # Get deployments for a specific repository
            deployments = github_client.get_deployments(owner, repo, environment=environment, per_page=30)
            
            if not deployments:
                return f"No deployments found for {owner}/{repo}" + (f" in {environment}" if environment else "") + "."
            
            result_parts = [f"Deployments for {owner}/{repo} ({len(deployments)} total):\n"]
            
            for i, deployment in enumerate(deployments, 1):
                deployment_id = deployment.get('id', '?')
                env = deployment.get('environment', 'unknown')
                ref = deployment.get('ref', 'unknown')
                sha = deployment.get('sha', '')[:7] if deployment.get('sha') else 'unknown'
                creator = deployment.get('creator', {}).get('login', 'unknown')
                created_at = deployment.get('created_at', '')
                
                result_parts.append(f"{i}. Deployment #{deployment_id}")
                result_parts.append(f"   Environment: {env}")
                result_parts.append(f"   Branch: {ref} (commit: {sha})")
                result_parts.append(f"   Created by: {creator}")
                if created_at:
                    try:
                        created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        result_parts.append(f"   Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    except:
                        pass
                result_parts.append("")
            
            return "\n".join(result_parts)
        else:
            # Get deployments from all user repositories
            user_info = github_client.get_user_info()
            username = user_info.get('login', 'Unknown')
            all_deployments = github_client.get_all_deployments(username, per_repo=10)
            
            if not all_deployments:
                return "No deployments found across your repositories."
            
            result_parts = [f"Deployments across all repositories:\n"]
            total_deployments = sum(len(deploys) for deploys in all_deployments.values())
            result_parts.append(f"Total: {total_deployments} deployments across {len(all_deployments)} repositories\n")
            
            for repo_name, deployments in all_deployments.items():
                result_parts.append(f"\n{repo_name}:")
                for i, deployment in enumerate(deployments, 1):
                    deployment_id = deployment.get('id', '?')
                    env = deployment.get('environment', 'unknown')
                    ref = deployment.get('ref', 'unknown')
                    sha = deployment.get('sha', '')[:7] if deployment.get('sha') else 'unknown'
                    
                    # Get latest status
                    latest_status = deployment.get('latest_status', {})
                    status_state = latest_status.get('state', 'unknown') if latest_status else 'pending'
                    
                    status_icons = {
                        'success': '✅',
                        'failure': '❌',
                        'pending': '⏳',
                        'in_progress': '🔄',
                        'queued': '⏸️',
                        'error': '⚠️'
                    }
                    status_icon = status_icons.get(status_state, '❓')
                    
                    result_parts.append(f"  {i}. #{deployment_id} - {status_icon} {status_state.upper()}")
                    result_parts.append(f"     Environment: {env} | Branch: {ref} | Commit: {sha}")
                    result_parts.append("")
            
            return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_github_deployments: {e}", exc_info=True)
        return f"Error fetching GitHub deployments: {str(e)}"


@mcp.tool()
def get_slack_channels() -> str:
    """
    Get list of Slack channels the user has access to.
    
    Returns:
        Formatted string with channel information
    """
    try:
        initialize_slack_client()
        
        channels = slack_client.get_channels()
        
        if not channels:
            return "No Slack channels found."
        
        result_parts = [f"SLACK CHANNELS ({len(channels)} total):\n"]
        result_parts.append("-" * 50)
        
        for i, channel in enumerate(channels[:30], 1):  # Limit to 30
            name = channel.get('name', 'Unknown')
            is_private = channel.get('is_private', False)
            is_archived = channel.get('is_archived', False)
            topic = channel.get('topic', {}).get('value', '') or 'No topic'
            purpose = channel.get('purpose', {}).get('value', '') or 'No purpose'
            num_members = channel.get('num_members', 0)
            
            channel_line = f"  {i}. #{name}"
            if is_private:
                channel_line += " [PRIVATE]"
            if is_archived:
                channel_line += " [ARCHIVED]"
            channel_line += f" | {num_members} members"
            
            result_parts.append(channel_line)
            if topic and topic != 'No topic':
                result_parts.append(f"     Topic: {topic[:100]}")
            if purpose and purpose != 'No purpose':
                result_parts.append(f"     Purpose: {purpose[:100]}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_slack_channels: {e}", exc_info=True)
        return f"Error fetching Slack channels: {str(e)}"


@mcp.tool()
def get_slack_unread() -> str:
    """
    Get Slack channels with unread messages.
    
    Returns:
        Formatted string with unread channel information
    """
    try:
        initialize_slack_client()
        
        unread_channels = slack_client.get_unread_channels()
        
        if not unread_channels:
            return "No unread messages in Slack channels."
        
        result_parts = [f"UNREAD SLACK CHANNELS ({len(unread_channels)} total):\n"]
        result_parts.append("-" * 50)
        
        for i, channel in enumerate(unread_channels, 1):
            name = channel.get('name', 'Unknown')
            unread_count = channel.get('unread_count', 0)
            
            result_parts.append(f"  {i}. #{name} - {unread_count} unread message(s)")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_slack_unread: {e}", exc_info=True)
        return f"Error fetching unread Slack messages: {str(e)}"


@mcp.tool()
def get_slack_mentions(days: int = 7) -> str:
    """
    Get recent Slack messages where the user was mentioned.
    
    Args:
        days: Number of days to look back (default: 7)
    
    Returns:
        Formatted string with mention information
    """
    try:
        initialize_slack_client()
        
        mentions = slack_client.get_mentions(days=days, limit=20)
        
        if not mentions:
            return f"No Slack mentions found in the last {days} days."
        
        result_parts = [f"SLACK MENTIONS ({len(mentions)} total in last {days} days):\n"]
        result_parts.append("-" * 50)
        
        for i, mention in enumerate(mentions, 1):
            channel_name = mention.get('channel_name', 'Unknown')
            text = mention.get('text', '')[:200]
            user = mention.get('user', 'Unknown')
            timestamp = mention.get('ts', '')
            
            result_parts.append(f"  {i}. In #{channel_name}:")
            result_parts.append(f"     {text}")
            if timestamp:
                try:
                    from datetime import datetime
                    ts_float = float(timestamp)
                    dt = datetime.fromtimestamp(ts_float)
                    result_parts.append(f"     Time: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                except:
                    pass
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_slack_mentions: {e}", exc_info=True)
        return f"Error fetching Slack mentions: {str(e)}"


@mcp.tool()
def chat(message: str, include_calendar_context: bool = True, include_github_context: bool = False, include_slack_context: bool = False) -> str:
    """
    Chat with the AI assistant about your calendar, GitHub, and Slack. This is a conversational interface
    that uses Gemini AI to answer questions about your schedule, availability, events, GitHub activity, and Slack messages.
    
    Args:
        message: Your message or question
        include_calendar_context: Whether to include calendar context in the response (default: True)
        include_github_context: Whether to include GitHub context in the response (default: False)
        include_slack_context: Whether to include Slack context in the response (default: False)
    
    Returns:
        AI assistant's response
    """
    try:
        initialize_gemini_client()
        
        # Enhanced query analysis with 2.0 features
        analysis = query_analyzer.analyze(message)
        message_lower = message.lower()
        query_domain = analysis.get('query_domain', 'general')
        is_multi_intent = analysis.get('is_multi_intent', False)
        entities = analysis.get('entities', {})
        
        # Detect Slack-related queries
        is_slack_query = any(keyword in message_lower for keyword in 
                           ['slack', 'message', 'messages', 'channel', 'channels', 'mention', 'mentions',
                            'unread', 'dm', 'direct message', 'thread', 'threads'])
        
        # Auto-enable Slack context if query mentions Slack
        if is_slack_query:
            include_slack_context = True
        
        # Use query domain to determine context needs
        if query_domain == 'github' or (query_domain == 'both' and not include_calendar_context):
            include_calendar_context = False
            include_github_context = True
        elif query_domain == 'calendar' or (query_domain == 'both' and not include_github_context):
            include_github_context = False
        elif query_domain == 'both':
            # Multi-intent query - include both
            include_calendar_context = True
            include_github_context = True
        
        calendar_context = None
        github_context = None
        slack_context = None
        correlation_context = None
        
        # Fetch calendar context (with caching, ranking, and summarization)
        if include_calendar_context:
            # Get relevant calendar context for the query (with caching)
            try:
                initialize_calendar_client()
                
                time_min, time_max = query_analyzer.get_time_range_for_query(analysis)
                
                # Check cache first
                events = context_cache.get_calendar_events(time_min, time_max)
                
                if events is None:
                    # Cache miss - fetch from API
                    events = calendar_client.get_events_from_all_calendars(
                        time_min=time_min,
                        time_max=time_max,
                        max_results=250
                    )
                    # Cache the results
                    context_cache.set_calendar_events(time_min, time_max, events)
                
                # Rank events by relevance to query
                ranked_events = context_ranker.rank_events(events, message, max_items=50)
                
                # Summarize events to reduce token usage
                summarized_events = context_summarizer.summarize_events(
                    ranked_events,
                    max_items=30,
                    priority="time"
                )
                
                # Format context with date information
                calendar_context = context_formatter.format_calendar_context(
                    summarized_events, analysis, None, None
                )
                
                # Add explicit date range information at the top
                date_info_parts = [f"CURRENT DATE: {datetime.now().strftime('%A, %B %d, %Y')}"]
                
                if time_min and time_max:
                    days_diff = (time_max.date() - time_min.date()).days
                    if days_diff <= 1:
                        date_info_parts.append(f"QUERY DATE: {time_min.strftime('%A, %B %d, %Y')}")
                    else:
                        date_info_parts.append(
                            f"QUERY DATE RANGE: {time_min.strftime('%A, %B %d, %Y')} to {time_max.strftime('%A, %B %d, %Y')} "
                            f"({days_diff} days)"
                        )
                
                date_info = "\n".join(date_info_parts) + "\n\n"
                calendar_context = date_info + calendar_context
            except Exception as e:
                # If calendar context fails, continue without it
                calendar_context = f"Note: Could not fetch calendar context: {str(e)}"
        
        if include_github_context:
            # Get GitHub context if requested
            try:
                initialize_github_client()
                
                github_context_parts = []
                
                # Always get user info
                try:
                    user_info = github_client.get_user_info()
                    username = user_info.get('login', 'Unknown')
                    github_context_parts.append(f"GITHUB USER: {username}")
                    github_context_parts.append("")
                except Exception:
                    pass
                
                # Check what type of GitHub data is needed
                needs_repos = any(keyword in message_lower for keyword in 
                                ['repo', 'repository', 'repositories', 'project', 'projects'])
                needs_issues = 'issue' in message_lower
                needs_prs = any(keyword in message_lower for keyword in 
                              ['pr', 'pull request', 'pull-request', 'merge'])
                needs_commits = any(keyword in message_lower for keyword in 
                                  ['commit', 'commits', 'history', 'changes', 'log'])
                needs_deployments = any(keyword in message_lower for keyword in 
                                      ['deployment', 'deploy', 'deployed', 'deploying', 'production', 
                                       'staging', 'environment', 'live', 'release'])
                needs_readme = any(keyword in message_lower for keyword in 
                                 ['readme', 'about', 'summary', 'what is', 'tell me about', 'describe'])
                
                # Try to extract repository name from message for README fetching
                repo_for_readme = None
                if needs_repos or needs_readme or needs_commits:
                    # Try to find owner/repo pattern
                    owner_repo_pattern = r'([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)'
                    match = re.search(owner_repo_pattern, message)
                    if match:
                        repo_owner = match.group(1)
                        repo_name = match.group(2)
                        repo_for_readme = (repo_owner, repo_name)
                    else:
                        # Try to find just repo name (assume it's user's repo)
                        words = re.findall(r'\b[a-zA-Z0-9_-]{3,}\b', message)
                        common_words = {'show', 'me', 'last', 'recent', 'commits', 'commit', 'history', 
                                      'repo', 'repository', 'github', 'what', 'are', 'the', 'my', 'about',
                                      'readme', 'summary', 'tell', 'describe', 'is', 'this', 'that'}
                        potential_repos = [w for w in words if w.lower() not in common_words and 
                                         ('-' in w or '_' in w or len(w) > 5)]
                        
                        if potential_repos:
                            # Use the first potential repo name
                            repo_name = potential_repos[0]
                            repo_for_readme = (username, repo_name)
                
                # Fetch README if a specific repository is mentioned
                # Always fetch README when a repo is mentioned, as it provides valuable context
                if repo_for_readme:
                    try:
                        repo_owner, repo_name = repo_for_readme
                        readme_content = github_client.get_readme(repo_owner, repo_name)
                        
                        if readme_content:
                            # Limit README content to first 3000 characters to avoid token limits
                            # but keep enough context for a good summary
                            readme_preview = readme_content[:3000]
                            if len(readme_content) > 3000:
                                readme_preview += "\n\n[... README truncated for brevity ...]"
                            
                            github_context_parts.append(f"README for {repo_owner}/{repo_name}:")
                            github_context_parts.append("-" * 50)
                            github_context_parts.append(readme_preview)
                            github_context_parts.append("")
                    except Exception as e:
                        # Silently fail - README might not exist or be accessible
                        pass
                
                # Fetch repositories if needed
                if needs_repos:
                    try:
                        repos = github_client.get_repositories(username, per_page=30)
                        github_context_parts.append(f"REPOSITORIES ({len(repos)} total):")
                        github_context_parts.append("-" * 50)
                        for i, repo in enumerate(repos, 1):
                            full_name = repo.get('full_name', 'Unknown')
                            description = repo.get('description', '') or 'No description'
                            stars = repo.get('stargazers_count', 0)
                            language = repo.get('language', 'N/A')
                            is_private = repo.get('private', False)
                            updated = repo.get('updated_at', '')
                            
                            repo_line = f"  {i}. {full_name}"
                            if is_private:
                                repo_line += " [PRIVATE]"
                            repo_line += f" | ⭐ {stars} | {language}"
                            github_context_parts.append(repo_line)
                            github_context_parts.append(f"     Description: {description[:100]}")
                            if updated:
                                try:
                                    updated_dt = datetime.fromisoformat(updated.replace('Z', '+00:00'))
                                    github_context_parts.append(f"     Last updated: {updated_dt.strftime('%Y-%m-%d')}")
                                except:
                                    pass
                            github_context_parts.append(f"     URL: {repo.get('html_url', '')}")
                            github_context_parts.append("")
                    except Exception as e:
                        github_context_parts.append(f"Error fetching repositories: {str(e)}")
                
                # Fetch issues if needed (for user's repos)
                if needs_issues:
                    try:
                        repos = github_client.get_repositories(username, per_page=10)
                        all_issues = []
                        for repo in repos[:5]:  # Check top 5 repos
                            owner = repo.get('owner', {}).get('login', username)
                            repo_name = repo.get('name', '')
                            try:
                                issues = github_client.get_issues(owner, repo_name, state='open', per_page=10)
                                for issue in issues:
                                    issue['repo'] = repo.get('full_name', 'Unknown')
                                all_issues.extend(issues)
                            except Exception:
                                continue
                        
                        if all_issues:
                            github_context_parts.append(f"OPEN ISSUES ({len(all_issues)} total):")
                            github_context_parts.append("-" * 50)
                            for i, issue in enumerate(all_issues[:20], 1):  # Limit to 20
                                title = issue.get('title', 'Untitled')
                                number = issue.get('number', '?')
                                repo_name = issue.get('repo', 'Unknown')
                                assignees = [a.get('login', '') for a in issue.get('assignees', [])]
                                labels = [l.get('name', '') for l in issue.get('labels', [])]
                                
                                github_context_parts.append(f"  {i}. #{number} in {repo_name}: {title}")
                                if assignees:
                                    github_context_parts.append(f"     Assignees: {', '.join(assignees)}")
                                if labels:
                                    github_context_parts.append(f"     Labels: {', '.join(labels)}")
                                github_context_parts.append("")
                    except Exception as e:
                        github_context_parts.append(f"Error fetching issues: {str(e)}")
                
                # Fetch PRs if needed
                if needs_prs:
                    try:
                        repos = github_client.get_repositories(username, per_page=10)
                        all_prs = []
                        for repo in repos[:5]:  # Check top 5 repos
                            owner = repo.get('owner', {}).get('login', username)
                            repo_name = repo.get('name', '')
                            try:
                                prs = github_client.get_pull_requests(owner, repo_name, state='open', per_page=10)
                                for pr in prs:
                                    pr['repo'] = repo.get('full_name', 'Unknown')
                                all_prs.extend(prs)
                            except Exception:
                                continue
                        
                        if all_prs:
                            github_context_parts.append(f"OPEN PULL REQUESTS ({len(all_prs)} total):")
                            github_context_parts.append("-" * 50)
                            for i, pr in enumerate(all_prs[:20], 1):  # Limit to 20
                                title = pr.get('title', 'Untitled')
                                number = pr.get('number', '?')
                                repo_name = pr.get('repo', 'Unknown')
                                author = pr.get('user', {}).get('login', 'unknown')
                                
                                github_context_parts.append(f"  {i}. #{number} in {repo_name}: {title}")
                                github_context_parts.append(f"     Author: {author}")
                                github_context_parts.append("")
                    except Exception as e:
                        github_context_parts.append(f"Error fetching pull requests: {str(e)}")
                
                # Fetch commits if needed
                if needs_commits:
                    try:
                        # Try to extract repository name from message
                        # Look for patterns like "repo-name show commits" or "owner/repo commits"
                        repo_match = None
                        
                        # Try to find owner/repo pattern
                        owner_repo_pattern = r'([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)'
                        match = re.search(owner_repo_pattern, message)
                        if match:
                            repo_owner = match.group(1)
                            repo_name = match.group(2)
                            repo_match = (repo_owner, repo_name)
                        else:
                            # Try to find just repo name (assume it's user's repo)
                            # Look for repo name patterns (words with hyphens/underscores, typically longer)
                            words = re.findall(r'\b[a-zA-Z0-9_-]{3,}\b', message)
                            # Filter out common words and look for repo-like names
                            common_words = {'show', 'me', 'last', 'recent', 'commits', 'commit', 'history', 
                                          'repo', 'repository', 'github', 'what', 'are', 'the', 'my'}
                            potential_repos = [w for w in words if w.lower() not in common_words and 
                                             ('-' in w or '_' in w or len(w) > 5)]
                            
                            if potential_repos:
                                # Use the first potential repo name
                                repo_name = potential_repos[0]
                                repo_match = (username, repo_name)
                        
                        if repo_match:
                            repo_owner, repo_name = repo_match
                            # Extract number of commits if specified (e.g., "last 10 commits")
                            num_commits = 10  # default
                            num_match = re.search(r'(\d+)\s*(?:commits?|commit)', message_lower)
                            if num_match:
                                num_commits = int(num_match.group(1))
                            
                            commits = github_client.get_commits(repo_owner, repo_name, per_page=num_commits)
                            
                            if commits:
                                github_context_parts.append(f"COMMITS for {repo_owner}/{repo_name} ({len(commits)} commits):")
                                github_context_parts.append("-" * 50)
                                for i, commit in enumerate(commits, 1):
                                    sha = commit.get('sha', '')[:7] if commit.get('sha') else 'unknown'
                                    message_text = commit.get('commit', {}).get('message', 'No message')
                                    # Get first line of commit message
                                    message_first_line = message_text.split('\n')[0][:80]
                                    author = commit.get('commit', {}).get('author', {}).get('name', 'unknown')
                                    date = commit.get('commit', {}).get('author', {}).get('date', '')
                                    
                                    github_context_parts.append(f"  {i}. {sha} - {message_first_line}")
                                    github_context_parts.append(f"     Author: {author}")
                                    if date:
                                        try:
                                            date_dt = datetime.fromisoformat(date.replace('Z', '+00:00'))
                                            github_context_parts.append(f"     Date: {date_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                                        except:
                                            pass
                                    github_context_parts.append(f"     URL: {commit.get('html_url', '')}")
                                    github_context_parts.append("")
                            else:
                                github_context_parts.append(f"No commits found for {repo_owner}/{repo_name}.")
                        else:
                            # Fetch commits from recent repos
                            repos = github_client.get_repositories(username, per_page=5)
                            all_commits = []
                            for repo in repos[:3]:  # Check top 3 repos
                                owner = repo.get('owner', {}).get('login', username)
                                repo_name = repo.get('name', '')
                                try:
                                    commits = github_client.get_commits(owner, repo_name, per_page=5)
                                    for commit in commits:
                                        commit['repo'] = repo.get('full_name', 'Unknown')
                                    all_commits.extend(commits)
                                except Exception:
                                    continue
                            
                            if all_commits:
                                github_context_parts.append(f"RECENT COMMITS ({len(all_commits)} total):")
                                github_context_parts.append("-" * 50)
                                for i, commit in enumerate(all_commits[:20], 1):  # Limit to 20
                                    sha = commit.get('sha', '')[:7] if commit.get('sha') else 'unknown'
                                    message_text = commit.get('commit', {}).get('message', 'No message')
                                    message_first_line = message_text.split('\n')[0][:80]
                                    repo_name = commit.get('repo', 'Unknown')
                                    author = commit.get('commit', {}).get('author', {}).get('name', 'unknown')
                                    
                                    github_context_parts.append(f"  {i}. {sha} in {repo_name}: {message_first_line}")
                                    github_context_parts.append(f"     Author: {author}")
                                    github_context_parts.append("")
                    except Exception as e:
                        github_context_parts.append(f"Error fetching commits: {str(e)}")
                
                # Fetch deployments if needed
                if needs_deployments:
                    try:
                        all_deployments = github_client.get_all_deployments(username, per_repo=10)
                        
                        if all_deployments:
                            total_deployments = sum(len(deploys) for deploys in all_deployments.values())
                            github_context_parts.append(f"DEPLOYMENTS ({total_deployments} total across {len(all_deployments)} repositories):")
                            github_context_parts.append("-" * 50)
                            
                            for repo_name, deployments in all_deployments.items():
                                github_context_parts.append(f"\n{repo_name}:")
                                for i, deployment in enumerate(deployments, 1):
                                    deployment_id = deployment.get('id', '?')
                                    environment = deployment.get('environment', 'unknown')
                                    ref = deployment.get('ref', 'unknown')
                                    sha = deployment.get('sha', '')[:7] if deployment.get('sha') else 'unknown'
                                    creator = deployment.get('creator', {}).get('login', 'unknown')
                                    created_at = deployment.get('created_at', '')
                                    
                                    # Get latest status
                                    latest_status = deployment.get('latest_status', {})
                                    status_state = latest_status.get('state', 'unknown') if latest_status else 'pending'
                                    
                                    # Status icons
                                    status_icons = {
                                        'success': '✅',
                                        'failure': '❌',
                                        'pending': '⏳',
                                        'in_progress': '🔄',
                                        'queued': '⏸️',
                                        'error': '⚠️'
                                    }
                                    status_icon = status_icons.get(status_state, '❓')
                                    
                                    github_context_parts.append(f"  {i}. Deployment #{deployment_id} - {status_icon} {status_state.upper()}")
                                    github_context_parts.append(f"     Environment: {environment}")
                                    github_context_parts.append(f"     Branch: {ref} (commit: {sha})")
                                    github_context_parts.append(f"     Created by: {creator}")
                                    if created_at:
                                        try:
                                            created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                            github_context_parts.append(f"     Created: {created_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                                        except:
                                            pass
                                    
                                    # Add deployment URL if available
                                    if deployment.get('url'):
                                        github_context_parts.append(f"     URL: {deployment.get('url')}")
                                    
                                    github_context_parts.append("")
                        else:
                            github_context_parts.append("No deployments found.")
                    except Exception as e:
                        github_context_parts.append(f"Error fetching deployments: {str(e)}")
                
                # If no specific data requested, provide summary
                if not (needs_repos or needs_issues or needs_prs or needs_commits or needs_deployments):
                    try:
                        activity = github_client.get_user_activity(days=7)
                        github_context_parts.append(f"GITHUB ACTIVITY SUMMARY:")
                        github_context_parts.append(f"Total Repositories: {activity.get('total_repositories', 0)}")
                        recent_repos = activity.get('recent_repositories', [])
                        if recent_repos:
                            github_context_parts.append(f"\nRecent Repositories ({len(recent_repos)}):")
                            for repo in recent_repos[:5]:
                                github_context_parts.append(f"  - {repo.get('full_name', 'Unknown')}: {repo.get('description', 'No description')[:80]}")
                    except Exception:
                        pass
                
                github_context = "\n".join(github_context_parts) if github_context_parts else "No GitHub data available."
            except Exception as e:
                github_context = f"Note: Could not fetch GitHub context: {str(e)}"
        
        # Fetch Slack context if requested
        if include_slack_context:
            try:
                initialize_slack_client()
                
                slack_context_parts = []
                
                # Get user info
                try:
                    user_info = slack_client.get_user_info()
                    user_name = user_info.get('user', 'Unknown')
                    team_name = user_info.get('team', 'Unknown')
                    slack_context_parts.append(f"SLACK USER: {user_name} (Team: {team_name})")
                    slack_context_parts.append("")
                except Exception:
                    pass
                
                # Check what type of Slack data is needed
                needs_channels = any(keyword in message_lower for keyword in 
                                   ['channel', 'channels', 'list channels'])
                needs_unread = any(keyword in message_lower for keyword in 
                                 ['unread', 'unread messages', 'unread channel'])
                needs_mentions = any(keyword in message_lower for keyword in 
                                   ['mention', 'mentions', 'mentioned', 'tagged'])
                
                # Get unread channels
                if needs_unread or not (needs_channels or needs_mentions):
                    try:
                        unread_channels = slack_client.get_unread_channels()
                        if unread_channels:
                            slack_context_parts.append(f"UNREAD CHANNELS ({len(unread_channels)} total):")
                            slack_context_parts.append("-" * 50)
                            for i, channel in enumerate(unread_channels[:10], 1):
                                name = channel.get('name', 'Unknown')
                                unread_count = channel.get('unread_count', 0)
                                slack_context_parts.append(f"  {i}. #{name} - {unread_count} unread message(s)")
                            slack_context_parts.append("")
                        else:
                            # Explicitly state if no unread channels found
                            slack_context_parts.append("UNREAD CHANNELS: No unread channels found.")
                            slack_context_parts.append("")
                    except Exception as e:
                        slack_context_parts.append(f"Note: Could not fetch unread channels: {str(e)}")
                        slack_context_parts.append("")
                
                # Get mentions
                if needs_mentions or not (needs_channels or needs_unread):
                    try:
                        mentions = slack_client.get_mentions(days=7, limit=10)
                        if mentions:
                            slack_context_parts.append(f"RECENT MENTIONS ({len(mentions)} total):")
                            slack_context_parts.append("-" * 50)
                            for i, mention in enumerate(mentions, 1):
                                channel_name = mention.get('channel_name', 'Unknown')
                                text = mention.get('text', '')[:150]
                                slack_context_parts.append(f"  {i}. In #{channel_name}: {text}")
                            slack_context_parts.append("")
                        else:
                            # Explicitly state if no mentions found
                            slack_context_parts.append("RECENT MENTIONS: No mentions found in the last 7 days.")
                            slack_context_parts.append("")
                    except Exception as e:
                        slack_context_parts.append(f"Note: Could not fetch mentions: {str(e)}")
                        slack_context_parts.append("")
                
                # Get channels list if specifically requested
                if needs_channels:
                    try:
                        channels = slack_client.get_channels()
                        if channels:
                            slack_context_parts.append(f"CHANNELS ({len(channels)} total):")
                            slack_context_parts.append("-" * 50)
                            for i, channel in enumerate(channels[:20], 1):
                                name = channel.get('name', 'Unknown')
                                is_private = channel.get('is_private', False)
                                num_members = channel.get('num_members', 0)
                                channel_line = f"  {i}. #{name}"
                                if is_private:
                                    channel_line += " [PRIVATE]"
                                channel_line += f" | {num_members} members"
                                slack_context_parts.append(channel_line)
                            slack_context_parts.append("")
                    except Exception as e:
                        pass
                
                # Get recent activity summary if nothing specific requested
                if not (needs_channels or needs_unread or needs_mentions):
                    try:
                        activity = slack_client.get_recent_activity(days=7, limit=10)
                        slack_context_parts.append("SLACK ACTIVITY SUMMARY:")
                        slack_context_parts.append(f"Unread Channels: {activity.get('unread_channels_count', 0)}")
                        slack_context_parts.append(f"Recent Mentions: {activity.get('mentions_count', 0)}")
                        slack_context_parts.append("")
                    except Exception:
                        pass
                
                slack_context = "\n".join(slack_context_parts) if slack_context_parts else "No Slack data available."
            except Exception as e:
                slack_context = f"Note: Could not fetch Slack context: {str(e)}"
        
        # Multi-source correlation (if calendar, GitHub, and/or Slack data available)
        if include_calendar_context and include_github_context and calendar_context and github_context:
            try:
                # Get raw data for correlation (use cached or fetch minimal set)
                time_min, time_max = query_analyzer.get_time_range_for_query(analysis)
                events = context_cache.get_calendar_events(time_min, time_max)
                if events is None:
                    # Fetch minimal set for correlation
                    initialize_calendar_client()
                    events = calendar_client.get_events_from_all_calendars(
                        time_min=time_min,
                        time_max=time_max,
                        max_results=50
                    )
                
                # Get GitHub data for correlation
                initialize_github_client()
                username = github_client.get_user_info().get('login', 'Unknown')
                repos = context_cache.get_github_data('repos', username=username)
                if repos is None:
                    repos = github_client.get_repositories(username, per_page=20)
                    context_cache.set_github_data('repos', repos, username=username)
                
                issues = []
                prs = []
                for repo in repos[:5]:
                    owner = repo.get('owner', {}).get('login', username)
                    repo_name = repo.get('name', '')
                    try:
                        repo_issues = github_client.get_issues(owner, repo_name, state='open', per_page=5)
                        repo_prs = github_client.get_pull_requests(owner, repo_name, state='open', per_page=5)
                        issues.extend(repo_issues)
                        prs.extend(repo_prs)
                    except:
                        continue
                
                # Correlate calendar and GitHub data
                correlations = context_correlator.correlate_calendar_github(
                    events, repos, issues, prs
                )
                correlation_context = context_correlator.format_correlations(correlations)
            except Exception as e:
                # Silently fail correlation - not critical
                correlation_context = None
        
        # Combine and compress contexts
        combined_context = None
        if calendar_context or github_context or slack_context or correlation_context:
            context_parts = []
            if calendar_context:
                context_parts.append(calendar_context)
            if github_context:
                context_parts.append(github_context)
            if slack_context:
                context_parts.append(slack_context)
            if correlation_context:
                context_parts.append(correlation_context)
            
            combined_context = "\n\n".join(context_parts)
            
            # Compress context if too long
            combined_context = context_summarizer.compress_context(
                combined_context,
                target_length=8000  # ~2000 tokens
            )
        
        # Get response from Gemini
        response = gemini_client.chat(message, calendar_context=combined_context)
        return response
    
    except Exception as e:
        logger.error(f"Error in chat: {e}", exc_info=True)
        return f"Error in chat: {str(e)}"


if __name__ == "__main__":
    # Ensure stdout is clean for JSON-RPC protocol
    # Any errors should go to stderr
    import sys
    # Run the MCP server
    # FastMCP handles stdio communication, so we shouldn't write to stdout
    try:
        mcp.run()
    except Exception as e:
        # Write errors to stderr, not stdout
        sys.stderr.write(f"Fatal error in MCP server: {e}\n")
        sys.exit(1)

