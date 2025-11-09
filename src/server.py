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

# Try to import Jira client (optional)
try:
    from .jira_client import JiraClient
    JIRA_AVAILABLE = True
except ImportError:
    JIRA_AVAILABLE = False
    JiraClient = None


# Initialize MCP server
mcp = FastMCP("Calendar, GitHub & Jira MCP Server")

# Initialize components
calendar_client: Optional[CalendarClient] = None
github_client: Optional[GitHubClient] = None
jira_client: Optional[JiraClient] = None
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


def initialize_jira_client():
    """Initialize the Jira client."""
    global jira_client
    if jira_client is None:
        if not JIRA_AVAILABLE:
            raise RuntimeError(
                "Jira client not available. Install requests package and set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN."
            )
        try:
            base_url = os.getenv("JIRA_URL")
            email = os.getenv("JIRA_EMAIL")
            api_token = os.getenv("JIRA_API_TOKEN")
            
            if not base_url or not email or not api_token:
                raise ValueError(
                    "Jira credentials not found. Please set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN in your .env file."
                )
            
            jira_client = JiraClient(
                base_url=base_url,
                email=email,
                api_token=api_token
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Jira client: {e}")


def _format_jira_response_directly(message: str, jira_context: str) -> str:
    """
    Format Jira data directly without going through Gemini.
    This bypasses safety filters for Jira queries.
    
    Args:
        message: User's query
        jira_context: Raw Jira context data
        
    Returns:
        Formatted response string
    """
    message_lower = message.lower()
    
    # Extract key information from context
    response_parts = []
    
    # Check for sprint queries
    if any(keyword in message_lower for keyword in ['sprint', 'sprints', 'active sprint']):
        if "ACTIVE JIRA SPRINTS" in jira_context.upper():
            sprint_lines = []
            in_sprint_section = False
            for line in jira_context.split('\n'):
                if "ACTIVE JIRA SPRINTS" in line.upper():
                    in_sprint_section = True
                    count_match = re.search(r'\((\d+)\s+total\)', line.upper())
                    count = count_match.group(1) if count_match else ""
                    sprint_lines.append(f"## 🚀 Active Jira Sprints ({count} total)\n")
                elif in_sprint_section:
                    if line.strip().startswith("---") or line.strip() == "":
                        continue
                    elif any(keyword in line.upper() for keyword in ["ASSIGNED", "COMPLETED", "PROJECTS", "JIRA USER"]):
                        break
                    elif line.strip():
                        # Format sprint line
                        if "ID:" in line and "Sprint" in line:
                            sprint_name = re.sub(r'^\d+\.\s*', '', line.strip())
                            if "(" in sprint_name and "ID:" in sprint_name:
                                parts = sprint_name.split("(")
                                name = parts[0].strip()
                                sprint_id = parts[1].replace("ID:", "").replace(")", "").strip()
                                sprint_lines.append(f"\n### {name}\n")
                                sprint_lines.append(f"  **Sprint ID:** {sprint_id}\n")
                            else:
                                sprint_lines.append(f"\n### {sprint_name}\n")
                        elif "State:" in line or "Period:" in line:
                            # Format dates and calculate days remaining
                            if "Period:" in line and "T" in line:
                                try:
                                    from datetime import datetime, timezone
                                    date_pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z)'
                                    dates = re.findall(date_pattern, line)
                                    if len(dates) >= 2:
                                        start = datetime.fromisoformat(dates[0].replace('Z', '+00:00'))
                                        end = datetime.fromisoformat(dates[1].replace('Z', '+00:00'))
                                        now = datetime.now(timezone.utc)
                                        
                                        # Calculate days remaining
                                        days_remaining = (end - now).days
                                        days_elapsed = (now - start).days
                                        total_days = (end - start).days
                                        
                                        sprint_lines.append(f"  **Period:** {start.strftime('%B %d, %Y')} to {end.strftime('%B %d, %Y')}\n")
                                        
                                        if days_remaining > 0:
                                            sprint_lines.append(f"  **Days Remaining:** {days_remaining} days\n")
                                            sprint_lines.append(f"  **Progress:** {days_elapsed}/{total_days} days elapsed ({int((days_elapsed/total_days)*100)}%)\n")
                                        elif days_remaining == 0:
                                            sprint_lines.append(f"  **Status:** Ends today!\n")
                                        else:
                                            sprint_lines.append(f"  **Status:** Ended {abs(days_remaining)} days ago\n")
                                    else:
                                        sprint_lines.append(f"  {line.strip()}\n")
                                except Exception as e:
                                    sprint_lines.append(f"  {line.strip()}\n")
                            else:
                                sprint_lines.append(f"  {line.strip()}\n")
            
            if sprint_lines:
                response_parts.append("".join(sprint_lines))
    
    # Check for issue queries
    if any(keyword in message_lower for keyword in ['issue', 'issues', 'assigned', 'my issues', 'completed']):
        if "ASSIGNED JIRA ISSUES" in jira_context.upper() or "COMPLETED JIRA ISSUES" in jira_context.upper():
            issue_lines = []
            in_issue_section = False
            for line in jira_context.split('\n'):
                if "ASSIGNED JIRA ISSUES" in line.upper() or "COMPLETED JIRA ISSUES" in line.upper():
                    in_issue_section = True
                    count_match = re.search(r'\((\d+)\s+total\)', line.upper())
                    count = count_match.group(1) if count_match else ""
                    issue_lines.append(f"## 🎫 {line.strip()}\n\n")
                elif in_issue_section:
                    if line.strip().startswith("---") or line.strip() == "":
                        continue
                    elif any(keyword in line.upper() for keyword in ["SPRINTS", "PROJECTS", "JIRA USER"]):
                        break
                    elif line.strip() and not line.strip().startswith("("):
                        if line.strip().startswith("  ") and not line.strip().startswith("     "):
                            issue_lines.append(f"**{line.strip()}**\n")
                        elif line.strip().startswith("     "):
                            issue_lines.append(f"  {line.strip()}\n")
            
            if issue_lines:
                response_parts.append("".join(issue_lines))
    
    # Check for project queries
    if any(keyword in message_lower for keyword in ['project', 'projects']):
        if "JIRA PROJECTS" in jira_context.upper():
            project_lines = []
            in_project_section = False
            for line in jira_context.split('\n'):
                if "JIRA PROJECTS" in line.upper():
                    in_project_section = True
                    count_match = re.search(r'\((\d+)\s+total\)', line.upper())
                    count = count_match.group(1) if count_match else ""
                    project_lines.append(f"## 📋 Jira Projects ({count} total)\n\n")
                elif in_project_section:
                    if line.strip().startswith("---") or line.strip() == "":
                        continue
                    elif any(keyword in line.upper() for keyword in ["SPRINTS", "ISSUES", "JIRA USER"]):
                        break
                    elif line.strip() and not line.strip().startswith("("):
                        project_lines.append(f"  {line.strip()}\n")
            
            if project_lines:
                response_parts.append("".join(project_lines))
    
    if response_parts:
        return "\n".join(response_parts)
    else:
        # Fallback: return formatted context
        return jira_context


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
def get_jira_projects() -> str:
    """
    Get all accessible Jira projects.
    
    Returns:
        Formatted list of Jira projects
    """
    try:
        initialize_jira_client()
        
        projects = jira_client.get_projects()
        
        if not projects:
            return "No Jira projects found."
        
        result_parts = [f"Jira Projects ({len(projects)} total):\n"]
        
        for i, project in enumerate(projects, 1):
            key = project.get('key', 'Unknown')
            name = project.get('name', 'Unknown')
            project_type = project.get('projectTypeKey', 'unknown')
            description = project.get('description', '') or 'No description'
            
            result_parts.append(f"{i}. {key}: {name}")
            result_parts.append(f"   Type: {project_type}")
            result_parts.append(f"   {description[:100]}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_jira_projects: {e}", exc_info=True)
        return f"Error fetching Jira projects: {str(e)}"


@mcp.tool()
def get_jira_issues(jql: str, max_results: int = 20) -> str:
    """
    Get Jira issues using a JQL (Jira Query Language) query.
    
    Args:
        jql: Jira Query Language string (e.g., "assignee=currentUser() AND status!=Done")
        max_results: Maximum number of issues to return (default: 20)
    
    Returns:
        Formatted list of Jira issues
    """
    try:
        initialize_jira_client()
        
        issues = jira_client.get_issues(jql=jql, max_results=max_results)
        
        if not issues:
            return f"No issues found matching JQL: {jql}"
        
        result_parts = [f"Jira Issues ({len(issues)} found):\n"]
        result_parts.append(f"JQL: {jql}\n")
        
        for i, issue in enumerate(issues, 1):
            key = issue.get('key', 'Unknown')
            fields = issue.get('fields', {})
            summary = fields.get('summary', 'No summary')
            status = fields.get('status', {}).get('name', 'Unknown')
            assignee = fields.get('assignee', {})
            assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'
            priority = fields.get('priority', {}).get('name', 'None')
            project = fields.get('project', {}).get('name', 'Unknown')
            
            result_parts.append(f"{i}. {key}: {summary}")
            result_parts.append(f"   Status: {status} | Priority: {priority}")
            result_parts.append(f"   Project: {project} | Assignee: {assignee_name}")
            result_parts.append(f"   URL: {jira_client.base_url}/browse/{key}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_jira_issues: {e}", exc_info=True)
        return f"Error fetching Jira issues: {str(e)}"


@mcp.tool()
def get_jira_issue_details(issue_key: str) -> str:
    """
    Get detailed information about a specific Jira issue.
    
    Args:
        issue_key: Jira issue key (e.g., "PROJ-123")
    
    Returns:
        Formatted details of the Jira issue
    """
    try:
        initialize_jira_client()
        
        issue = jira_client.get_issue_details(issue_key)
        
        fields = issue.get('fields', {})
        key = issue.get('key', issue_key)
        summary = fields.get('summary', 'No summary')
        description = fields.get('description', 'No description')
        status = fields.get('status', {}).get('name', 'Unknown')
        assignee = fields.get('assignee', {})
        assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'
        reporter = fields.get('reporter', {})
        reporter_name = reporter.get('displayName', 'Unknown') if reporter else 'Unknown'
        priority = fields.get('priority', {}).get('name', 'None')
        issue_type = fields.get('issuetype', {}).get('name', 'Unknown')
        project = fields.get('project', {}).get('name', 'Unknown')
        created = fields.get('created', '')
        updated = fields.get('updated', '')
        
        result_parts = [f"Jira Issue: {key}\n"]
        result_parts.append("=" * 50)
        result_parts.append(f"Summary: {summary}")
        result_parts.append(f"Type: {issue_type} | Status: {status} | Priority: {priority}")
        result_parts.append(f"Project: {project}")
        result_parts.append(f"Assignee: {assignee_name} | Reporter: {reporter_name}")
        if created:
            result_parts.append(f"Created: {created}")
        if updated:
            result_parts.append(f"Updated: {updated}")
        result_parts.append("")
        result_parts.append("Description:")
        result_parts.append(str(description)[:500])  # Limit description length
        result_parts.append("")
        result_parts.append(f"URL: {jira_client.base_url}/browse/{key}")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_jira_issue_details: {e}", exc_info=True)
        return f"Error fetching Jira issue details: {str(e)}"


@mcp.tool()
def test_jira_assignee_query(assignee: str) -> str:
    """
    Test Jira queries with a specific assignee value to debug why issues aren't found.
    This helps diagnose if the endpoint is working correctly.
    
    Args:
        assignee: The assignee value to test (username, email, etc.)
    
    Returns:
        Detailed test results showing what queries were tried and what was found
    """
    try:
        initialize_jira_client()
        
        # Get current user info for context
        try:
            current_user = jira_client.get_current_user()
            user_email = current_user.get('emailAddress', jira_client.email)
            user_name = current_user.get('displayName', user_email)
            account_id = current_user.get('accountId', 'unknown')
        except:
            user_email = jira_client.email
            user_name = user_email
            account_id = 'unknown'
        
        result_parts = [
            "Jira Assignee Query Test",
            "=" * 60,
            f"Testing assignee: {assignee}",
            "",
            f"Current User Context:",
            f"  Email: {user_email}",
            f"  Name: {user_name}",
            f"  Account ID: {account_id}",
            "",
        ]
        
        # Test the assignee value
        test_result = jira_client.test_assignee_query(assignee)
        
        result_parts.append(f"Queries Tried ({len(test_result['queries_tried'])}):")
        for jql in test_result['queries_tried']:
            result_parts.append(f"  - {jql}")
        
        result_parts.append("")
        
        if test_result.get('successful_query'):
            result_parts.append(f"✅ SUCCESS! Found {len(test_result['results'])} issue(s) with query:")
            result_parts.append(f"   {test_result['successful_query']}")
            result_parts.append("")
            result_parts.append("Issues Found:")
            for i, issue in enumerate(test_result['results'], 1):
                key = issue.get('key', 'Unknown')
                fields = issue.get('fields', {})
                summary = fields.get('summary', 'No summary')
                status = fields.get('status', {}).get('name', 'Unknown')
                assignee_field = fields.get('assignee', {})
                assignee_email = assignee_field.get('emailAddress', 'N/A') if assignee_field else 'Unassigned'
                assignee_name = assignee_field.get('displayName', 'N/A') if assignee_field else 'Unassigned'
                assignee_account = assignee_field.get('accountId', 'N/A') if assignee_field else 'N/A'
                
                result_parts.append(f"  {i}. {key}: {summary}")
                result_parts.append(f"     Status: {status}")
                result_parts.append(f"     Assignee Email: {assignee_email}")
                result_parts.append(f"     Assignee Name: {assignee_name}")
                result_parts.append(f"     Assignee Account ID: {assignee_account}")
                result_parts.append("")
        else:
            result_parts.append("❌ No issues found with any query format")
            result_parts.append("")
            
            if test_result['errors']:
                result_parts.append("Errors encountered:")
                for error in test_result['errors']:
                    result_parts.append(f"  - {error}")
                result_parts.append("")
            
            result_parts.append("💡 Possible reasons:")
            result_parts.append("  1. The assignee format in Jira is different (check in Jira UI)")
            result_parts.append("  2. The issue might be in a project you don't have API access to")
            result_parts.append("  3. The JQL syntax might need adjustment for your Jira version")
            result_parts.append("  4. Try querying by accountId instead: test_jira_assignee_query(account_id)")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in test_jira_assignee_query: {e}", exc_info=True)
        return f"Error testing assignee query: {str(e)}"


@mcp.tool()
def get_jira_current_user() -> str:
    """
    Get information about the currently authenticated Jira user.
    
    This shows "who you are" based on your API token authentication.
    The API token is tied to a specific Jira account, and Jira uses it
    to identify which account you are when making API calls.
    
    Returns:
        Information about the authenticated Jira user
    """
    try:
        initialize_jira_client()
        
        current_user = jira_client.get_current_user()
        
        email = current_user.get('emailAddress', jira_client.email)
        display_name = current_user.get('displayName', email)
        account_id = current_user.get('accountId', 'unknown')
        account_type = current_user.get('accountType', 'unknown')
        
        result_parts = [
            "Authenticated Jira User Information:",
            "=" * 50,
            f"Display Name: {display_name}",
            f"Email: {email}",
            f"Account ID: {account_id}",
            f"Account Type: {account_type}",
            "",
            "ℹ️ How 'you' is determined:",
            "1. Your JIRA_API_TOKEN is tied to a specific Jira account",
            "2. When you authenticate, Jira identifies you based on the token",
            "3. The system uses this identity to query 'your' assigned issues",
            "4. The email in your .env file (JIRA_EMAIL) should match this account",
        ]
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_jira_current_user: {e}", exc_info=True)
        return f"Error fetching current user info: {str(e)}"


@mcp.tool()
def get_jira_user_issues(email: Optional[str] = None, limit: int = 10) -> str:
    """
    Get issues assigned to a specific user (or current user if None).
    
    The "current user" is determined by the Jira API token you provided:
    - The API token is tied to a specific Jira account
    - Jira uses the token to identify which account you are
    - The system uses `currentUser()` in JQL queries or falls back to your email
    
    Args:
        email: User email (optional, defaults to authenticated user from API token)
        limit: Maximum number of issues to return (default: 10)
    
    Returns:
        Formatted list of assigned Jira issues
    """
    try:
        initialize_jira_client()
        
        # Get current user info to show who "you" are
        try:
            current_user = jira_client.get_current_user()
            authenticated_email = current_user.get('emailAddress', jira_client.email)
            authenticated_name = current_user.get('displayName', authenticated_email)
        except:
            authenticated_email = jira_client.email
            authenticated_name = authenticated_email
        
        # Try to get issues - first without resolved, then with all issues
        issues = jira_client.get_user_assigned_issues(email=email, limit=limit, include_resolved=False)
        
        # If no unresolved issues found, try including resolved issues
        if not issues:
            issues = jira_client.get_user_assigned_issues(email=email, limit=limit, include_resolved=True)
        
        if not issues:
            user = email or authenticated_name or authenticated_email
            target_email = email or authenticated_email
            
            # Try a direct query with the specific email to debug
            debug_info = [
                f"No issues found assigned to {user}.\n",
                f"ℹ️ Debugging Information:",
                f"   Authenticated Email: {authenticated_email}",
                f"   Authenticated Name: {authenticated_name}",
                f"   Email in .env (JIRA_EMAIL): {jira_client.email}",
                f"   Query Email Used: {target_email}",
                "",
                "💡 Troubleshooting:",
                f"1. Verify the issue is assigned to: {target_email}",
                "2. Check if the issue status is 'Done' or 'Resolved' (these are filtered by default)",
                "3. Try querying with: get_jira_issues('assignee = \"aupragathii@tamu.edu\"')",
                "4. Verify your JIRA_EMAIL in .env matches the email in your Jira account",
                "5. Check if the authenticated user email matches the assignee email",
            ]
            
            # If user provided specific email, add note
            if email and email != authenticated_email:
                debug_info.append(f"\n⚠️ Note: You queried for '{email}' but you're authenticated as '{authenticated_email}'")
                debug_info.append("   Make sure the email matches the account that has the issue assigned.")
            
            return "\n".join(debug_info)
        
        result_parts = [f"Assigned Jira Issues ({len(issues)} total):\n"]
        
        for i, issue in enumerate(issues, 1):
            key = issue.get('key', 'Unknown')
            fields = issue.get('fields', {})
            summary = fields.get('summary', 'No summary')
            status = fields.get('status', {}).get('name', 'Unknown')
            priority = fields.get('priority', {}).get('name', 'None')
            project = fields.get('project', {}).get('name', 'Unknown')
            
            result_parts.append(f"{i}. {key}: {summary}")
            result_parts.append(f"   Status: {status} | Priority: {priority} | Project: {project}")
            result_parts.append(f"   URL: {jira_client.base_url}/browse/{key}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_jira_user_issues: {e}", exc_info=True)
        error_msg = str(e)
        if "410" in error_msg or "Gone" in error_msg:
            return (
                f"Error: Jira API returned 410 Gone. This usually means:\n"
                f"1. The API endpoint is deprecated for your Jira version\n"
                f"2. Your Jira instance may need API v2 instead of v3\n"
                f"3. Check your Jira instance version and API compatibility\n\n"
                f"Original error: {error_msg}"
            )
        return f"Error fetching Jira user issues: {error_msg}"


@mcp.tool()
def get_my_assigned_jiras(limit: int = 20) -> str:
    """
    Get all issues assigned to you (the authenticated user).
    
    This uses the Jira API token to identify who you are, so it will return
    issues assigned to the account associated with your JIRA_API_TOKEN.
    
    Args:
        limit: Maximum number of issues to return (default: 20)
    
    Returns:
        Formatted list of assigned Jira issues
    """
    try:
        initialize_jira_client()
        
        # Get current user info to show who "you" are
        try:
            current_user = jira_client.get_current_user()
            authenticated_email = current_user.get('emailAddress', jira_client.email)
            authenticated_name = current_user.get('displayName', authenticated_email)
        except:
            authenticated_email = jira_client.email
            authenticated_name = authenticated_email
        
        # Get assigned issues (unresolved only)
        issues = jira_client.get_user_assigned_issues(email=None, limit=limit, include_resolved=False)
        
        if not issues:
            return (
                f"No active assigned Jira issues found for {authenticated_name} ({authenticated_email}).\n\n"
                f"This means you currently have no unresolved issues assigned to you.\n"
                f"To see completed issues, use get_completed_jiras()."
            )
        
        result_parts = [f"My Assigned Jira Issues ({len(issues)} total):\n"]
        result_parts.append(f"User: {authenticated_name} ({authenticated_email})\n")
        
        for i, issue in enumerate(issues, 1):
            key = issue.get('key', 'Unknown')
            fields = issue.get('fields', {})
            summary = fields.get('summary', 'No summary')
            status = fields.get('status', {}).get('name', 'Unknown')
            priority = fields.get('priority', {}).get('name', 'None')
            project = fields.get('project', {}).get('name', 'Unknown')
            assignee = fields.get('assignee', {})
            assignee_name = assignee.get('displayName', 'Unassigned') if assignee else 'Unassigned'
            
            result_parts.append(f"{i}. {key}: {summary}")
            result_parts.append(f"   Status: {status} | Priority: {priority} | Project: {project}")
            result_parts.append(f"   Assignee: {assignee_name}")
            result_parts.append(f"   URL: {jira_client.base_url}/browse/{key}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_my_assigned_jiras: {e}", exc_info=True)
        error_msg = str(e)
        if "410" in error_msg or "Gone" in error_msg:
            return (
                f"Error: Jira API returned 410 Gone. This usually means:\n"
                f"1. The API endpoint is deprecated for your Jira version\n"
                f"2. Your Jira instance may need API v2 instead of v3\n"
                f"3. Check your Jira instance version and API compatibility\n\n"
                f"Original error: {error_msg}"
            )
        return f"Error fetching my assigned Jira issues: {error_msg}"


@mcp.tool()
def get_completed_jiras(limit: int = 20) -> str:
    """
    Get all completed/resolved issues assigned to you (the authenticated user).
    
    This uses the Jira API token to identify who you are, so it will return
    completed issues assigned to the account associated with your JIRA_API_TOKEN.
    
    Args:
        limit: Maximum number of issues to return (default: 20)
    
    Returns:
        Formatted list of completed Jira issues
    """
    try:
        initialize_jira_client()
        
        # Get current user info to show who "you" are
        try:
            current_user = jira_client.get_current_user()
            authenticated_email = current_user.get('emailAddress', jira_client.email)
            authenticated_name = current_user.get('displayName', authenticated_email)
        except:
            authenticated_email = jira_client.email
            authenticated_name = authenticated_email
        
        # Get completed issues
        issues = jira_client.get_completed_issues(email=None, limit=limit)
        
        if not issues:
            return (
                f"No completed Jira issues found for {authenticated_name} ({authenticated_email}).\n\n"
                f"This means you have no resolved/completed issues assigned to you.\n"
                f"To see active issues, use get_my_assigned_jiras()."
            )
        
        result_parts = [f"My Completed Jira Issues ({len(issues)} total):\n"]
        result_parts.append(f"User: {authenticated_name} ({authenticated_email})\n")
        
        for i, issue in enumerate(issues, 1):
            key = issue.get('key', 'Unknown')
            fields = issue.get('fields', {})
            summary = fields.get('summary', 'No summary')
            status = fields.get('status', {}).get('name', 'Unknown')
            priority = fields.get('priority', {}).get('name', 'None')
            project = fields.get('project', {}).get('name', 'Unknown')
            resolution = fields.get('resolution', {})
            resolution_name = resolution.get('name', 'Resolved') if resolution else 'Resolved'
            resolved_date = fields.get('resolutiondate', 'Unknown')
            
            result_parts.append(f"{i}. {key}: {summary}")
            result_parts.append(f"   Status: {status} | Priority: {priority} | Project: {project}")
            result_parts.append(f"   Resolution: {resolution_name} | Resolved: {resolved_date}")
            result_parts.append(f"   URL: {jira_client.base_url}/browse/{key}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_completed_jiras: {e}", exc_info=True)
        error_msg = str(e)
        if "410" in error_msg or "Gone" in error_msg:
            return (
                f"Error: Jira API returned 410 Gone. This usually means:\n"
                f"1. The API endpoint is deprecated for your Jira version\n"
                f"2. Your Jira instance may need API v2 instead of v3\n"
                f"3. Check your Jira instance version and API compatibility\n\n"
                f"Original error: {error_msg}"
            )
        return f"Error fetching completed Jira issues: {error_msg}"


@mcp.tool()
def get_jira_boards() -> str:
    """
    Get all accessible Jira boards (Kanban/Scrum boards).
    
    Returns:
        Formatted list of Jira boards
    """
    try:
        initialize_jira_client()
        
        boards = jira_client.get_boards()
        
        if not boards:
            return "No Jira boards found."
        
        result_parts = [f"Jira Boards ({len(boards)} total):\n"]
        
        for i, board in enumerate(boards, 1):
            board_id = board.get('id', 'Unknown')
            name = board.get('name', 'Unknown')
            board_type = board.get('type', 'Unknown')
            location = board.get('location', {})
            project_name = location.get('projectName', 'Unknown') if location else 'Unknown'
            
            result_parts.append(f"{i}. {name} (ID: {board_id})")
            result_parts.append(f"   Type: {board_type} | Project: {project_name}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_jira_boards: {e}", exc_info=True)
        return f"Error fetching Jira boards: {str(e)}"


@mcp.tool()
def get_active_sprints(board_id: Optional[str] = None) -> str:
    """
    Get all active sprints from Jira.
    
    If board_id is provided, only returns active sprints for that board.
    If board_id is None, searches all boards for active sprints.
    
    Args:
        board_id: ID of the Jira board (optional, if None searches all boards)
    
    Returns:
        Formatted list of active sprints
    """
    try:
        initialize_jira_client()
        
        active_sprints = jira_client.get_active_sprints(board_id=board_id)
        
        if not active_sprints:
            if board_id:
                return f"No active sprints found for board {board_id}."
            else:
                return "No active sprints found across all boards."
        
        result_parts = [f"Active Jira Sprints ({len(active_sprints)} total):\n"]
        if board_id:
            result_parts.append(f"Board ID: {board_id}\n")
        
        for i, sprint in enumerate(active_sprints, 1):
            sprint_id = sprint.get('id', 'Unknown')
            name = sprint.get('name', 'Unknown')
            state = sprint.get('state', 'Unknown')
            start_date = sprint.get('startDate', 'Not started')
            end_date = sprint.get('endDate', 'Not ended')
            board_name = sprint.get('board_name', 'Unknown')
            
            result_parts.append(f"{i}. {name} (ID: {sprint_id})")
            result_parts.append(f"   State: {state} | Board: {board_name}")
            result_parts.append(f"   Period: {start_date} to {end_date}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_active_sprints: {e}", exc_info=True)
        return f"Error fetching active sprints: {str(e)}"


@mcp.tool()
def get_jira_sprints(board_id: str) -> str:
    """
    Get all sprints for a Jira board.
    
    Args:
        board_id: ID of the Jira board (Kanban/Scrum)
    
    Returns:
        Formatted list of sprints
    """
    try:
        initialize_jira_client()
        
        sprints = jira_client.get_sprints(board_id)
        
        if not sprints:
            return f"No sprints found for board {board_id}."
        
        result_parts = [f"Jira Sprints for Board {board_id} ({len(sprints)} total):\n"]
        
        for i, sprint in enumerate(sprints, 1):
            sprint_id = sprint.get('id', 'Unknown')
            name = sprint.get('name', 'Unknown')
            state = sprint.get('state', 'Unknown')
            start_date = sprint.get('startDate', 'Not started')
            end_date = sprint.get('endDate', 'Not ended')
            
            result_parts.append(f"{i}. {name} (ID: {sprint_id})")
            result_parts.append(f"   State: {state}")
            result_parts.append(f"   Period: {start_date} to {end_date}")
            result_parts.append("")
        
        return "\n".join(result_parts)
    
    except Exception as e:
        logger.error(f"Error in get_jira_sprints: {e}", exc_info=True)
        return f"Error fetching Jira sprints: {str(e)}"


@mcp.tool()
def chat(message: str, include_calendar_context: bool = True, include_github_context: bool = False, include_jira_context: bool = False, force_refresh_calendar: bool = False) -> str:
    """
    Chat with the AI assistant about your calendar, GitHub, and Jira. This is a conversational interface
    that uses Gemini AI to answer questions about your schedule, availability, events, GitHub activity, and Jira issues.
    
    Args:
        message: Your message or question
        include_calendar_context: Whether to include calendar context in the response (default: True)
        include_github_context: Whether to include GitHub context in the response (default: False)
        include_jira_context: Whether to include Jira context in the response (default: False)
        force_refresh_calendar: Force refresh calendar data, bypassing cache (default: False)
    
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
        
        # Detect if user is asking about their identity in Jira
        is_identity_query = any(keyword in message_lower for keyword in 
                               ['who am i', 'who are you', 'my account', 'my user', 'my identity', 
                                'authenticated', 'current user', 'who is', 'what is my'])
        
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
        
        # If asking about identity and Jira is mentioned, include Jira context
        if is_identity_query and ('jira' in message_lower or not include_jira_context):
            include_jira_context = True
        
        calendar_context = None
        github_context = None
        jira_context = None
        correlation_context = None
        
        # Fetch calendar context (with caching, ranking, and summarization)
        if include_calendar_context:
            # Get relevant calendar context for the query (with caching)
            try:
                initialize_calendar_client()
                
                time_min, time_max = query_analyzer.get_time_range_for_query(analysis)
                
                # Detect if user wants fresh data (keywords suggesting recent updates)
                refresh_keywords = ['updated', 'just', 'recently', 'new', 'latest', 'refresh', 'reload', 'current']
                needs_refresh = force_refresh_calendar or any(keyword in message_lower for keyword in refresh_keywords)
                
                # Check cache first (unless force refresh is needed)
                events = context_cache.get_calendar_events(time_min, time_max, force_refresh=needs_refresh)
                
                if events is None:
                    # Cache miss or force refresh - fetch from API
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
                username = None  # Initialize to avoid UnboundLocalError
                try:
                    user_info = github_client.get_user_info()
                    username = user_info.get('login', 'Unknown')
                    github_context_parts.append(f"GITHUB USER: {username}")
                    github_context_parts.append("")
                except Exception as e:
                    # If we can't get user info, we'll try to continue but may have limited functionality
                    logger.warning(f"Could not get GitHub user info: {e}")
                    username = None
                
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
                        if not username:
                            github_context_parts.append("Error: Could not determine GitHub username. Please ensure GitHub authentication is configured.")
                        else:
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
                        if not username:
                            github_context_parts.append("Error: Could not determine GitHub username. Please ensure GitHub authentication is configured.")
                        else:
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
                        if not username:
                            github_context_parts.append("Error: Could not determine GitHub username. Please ensure GitHub authentication is configured.")
                        else:
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
                            
                        if potential_repos and username:
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
                            if not username:
                                github_context_parts.append("Error: Could not determine GitHub username. Please ensure GitHub authentication is configured.")
                            else:
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
                        if not username:
                            github_context_parts.append("Error: Could not determine GitHub username. Please ensure GitHub authentication is configured.")
                        else:
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
        
        # Fetch Jira context if requested
        if include_jira_context:
            try:
                initialize_jira_client()
                jira_context_parts = []
                
                # Always include current date and time for date calculations
                current_date = datetime.now()
                jira_context_parts.append("CURRENT DATE AND TIME:")
                jira_context_parts.append("-" * 50)
                jira_context_parts.append(f"Current Date: {current_date.strftime('%A, %B %d, %Y')}")
                jira_context_parts.append(f"Current Time: {current_date.strftime('%I:%M %p %Z')}")
                jira_context_parts.append(f"Current DateTime (ISO): {current_date.isoformat()}")
                jira_context_parts.append("")
                jira_context_parts.append("IMPORTANT: Use this current date to calculate days remaining, time until deadlines, etc.")
                jira_context_parts.append("")
                
                # Always include current user info in Jira context (so AI knows "who you are")
                try:
                    current_user = jira_client.get_current_user()
                    user_email = current_user.get('emailAddress', jira_client.email)
                    user_name = current_user.get('displayName', user_email)
                    user_account_id = current_user.get('accountId', 'unknown')
                    
                    jira_context_parts.append("JIRA USER INFORMATION:")
                    jira_context_parts.append("-" * 50)
                    jira_context_parts.append(f"Authenticated User: {user_name}")
                    jira_context_parts.append(f"Email: {user_email}")
                    jira_context_parts.append(f"Account ID: {user_account_id}")
                    jira_context_parts.append("")
                    jira_context_parts.append("(This is the account associated with your JIRA_API_TOKEN)")
                    jira_context_parts.append("When querying for 'your' issues, this is the user being checked.")
                    jira_context_parts.append("")
                except Exception as e:
                    # If we can't get user info, use email from config
                    jira_context_parts.append("JIRA USER INFORMATION:")
                    jira_context_parts.append("-" * 50)
                    jira_context_parts.append(f"Email (from config): {jira_client.email}")
                    jira_context_parts.append("(Could not fetch full user info from Jira API)")
                    jira_context_parts.append("")
                
                # Check what type of Jira data is needed
                needs_jira_issues = any(keyword in message_lower for keyword in 
                                      ['jira', 'issue', 'issues', 'ticket', 'tickets', 'task', 'tasks', 'bug', 'bugs',
                                       'assigned', 'my issues', 'my jira', 'jira issues'])
                needs_jira_projects = any(keyword in message_lower for keyword in 
                                        ['project', 'projects', 'jira project'])
                needs_jira_sprints = any(keyword in message_lower for keyword in 
                                       ['sprint', 'sprints', 'agile', 'active sprint', 'jira sprint'])
                needs_completed_issues = any(keyword in message_lower for keyword in 
                                           ['completed', 'resolved', 'done', 'finished', 'closed', 'completed tasks',
                                            'completed issues', 'resolved issues'])
                needs_user_info = any(keyword in message_lower for keyword in 
                                     ['who am i', 'who are you', 'my account', 'my user', 'my identity', 'authenticated', 'current user', 'who is'])
                
                # Fetch user assigned issues
                if needs_jira_issues:
                    try:
                        issues = None
                        # Extract username from email (e.g., "aupragathii@tamu.edu" -> "aupragathii")
                        username = user_email.split('@')[0] if '@' in user_email else user_email
                        
                        # Try multiple approaches in order of reliability:
                        # 1. Try with accountId first (most reliable - unique identifier)
                        if user_account_id and user_account_id != 'unknown':
                            try:
                                issues = jira_client.get_user_assigned_issues_by_account_id(user_account_id, limit=10)
                                if issues:
                                    jira_context_parts.append(f"✅ Found issues using accountId: {user_account_id}")
                            except Exception as e:
                                logger.debug(f"AccountId query failed: {e}")
                        
                        # 2. Try with username (since Jira stores assignee as username)
                        if not issues:
                            issues = jira_client.get_user_assigned_issues(email=username, limit=10, include_resolved=False)
                        
                        # 3. If no unresolved, try with username including resolved
                        if not issues:
                            issues = jira_client.get_user_assigned_issues(email=username, limit=10, include_resolved=True)
                        
                        # 4. Try with full email
                        if not issues:
                            issues = jira_client.get_user_assigned_issues(email=user_email, limit=10, include_resolved=True)
                        
                        # 5. Try with currentUser() (might work better)
                        if not issues:
                            issues = jira_client.get_user_assigned_issues(limit=10, include_resolved=True)
                        
                        # 6. Last resort: Direct JQL queries with different formats
                        if not issues:
                            test_queries = [
                                f'assignee = "{username}" ORDER BY updated DESC',
                                f'assignee = "{user_email}" ORDER BY updated DESC',
                                f'assignee = {username} ORDER BY updated DESC',  # Without quotes
                            ]
                            if user_account_id and user_account_id != 'unknown':
                                test_queries.extend([
                                    f'assignee = "{user_account_id}" ORDER BY updated DESC',
                                    f'assignee = {user_account_id} ORDER BY updated DESC',
                                ])
                            
                            for jql in test_queries:
                                try:
                                    issues = jira_client.get_issues(jql, max_results=10)
                                    if issues:
                                        break
                                except:
                                    continue
                        
                        if issues:
                            jira_context_parts.append(f"ASSIGNED JIRA ISSUES ({len(issues)} total):")
                            jira_context_parts.append("-" * 50)
                            for i, issue in enumerate(issues[:10], 1):
                                key = issue.get('key', 'Unknown')
                                fields = issue.get('fields', {})
                                summary = fields.get('summary', 'No summary')
                                status = fields.get('status', {}).get('name', 'Unknown')
                                priority = fields.get('priority', {}).get('name', 'None')
                                project = fields.get('project', {}).get('name', 'Unknown')
                                assignee = fields.get('assignee', {})
                                assignee_email = assignee.get('emailAddress', 'Unknown') if assignee else 'Unassigned'
                                
                                jira_context_parts.append(f"  {i}. {key}: {summary}")
                                jira_context_parts.append(f"     Status: {status} | Priority: {priority} | Project: {project}")
                                jira_context_parts.append(f"     Assignee Email: {assignee_email}")
                                jira_context_parts.append("")
                        else:
                            # No issues found - provide detailed debugging
                            debug_info = jira_client.get_query_debug_info()
                            username = user_email.split('@')[0] if '@' in user_email else user_email
                            
                            jira_context_parts.append("ASSIGNED JIRA ISSUES: No issues found.")
                            jira_context_parts.append("")
                            jira_context_parts.append("🔍 Debugging Information:")
                            jira_context_parts.append(f"   Authenticated Email: {user_email}")
                            jira_context_parts.append(f"   Username Extracted: {username}")
                            jira_context_parts.append(f"   Queries Tried: Both username ('{username}') and email ('{user_email}') formats")
                            
                            if debug_info.get('successful_but_empty'):
                                jira_context_parts.append(f"   Queries Executed: {len(debug_info.get('successful_but_empty', []))} queries ran successfully but returned no results")
                                jira_context_parts.append("   This suggests:")
                                jira_context_parts.append("   1. The issue might be assigned to a different username/email")
                                jira_context_parts.append("   2. The issue might have a status that was filtered out")
                                jira_context_parts.append("   3. There might be a case-sensitivity issue")
                            
                            jira_context_parts.append("")
                            jira_context_parts.append("💡 Try These Solutions:")
                            jira_context_parts.append(f"   1. Query with username: get_jira_issues('assignee = \"{username}\"')")
                            jira_context_parts.append(f"   2. Query with email: get_jira_issues('assignee = \"{user_email}\"')")
                            jira_context_parts.append(f"   3. Try with currentUser(): get_jira_issues('assignee = currentUser()')")
                            jira_context_parts.append("   4. Check the issue in Jira - verify the exact assignee format (username vs email)")
                            jira_context_parts.append(f"   5. Note: Jira often stores assignee as username ('{username}') not email")
                    except Exception as e:
                        error_msg = str(e)
                        jira_context_parts.append(f"❌ Error fetching assigned issues: {error_msg}")
                        logger.error(f"Error fetching Jira assigned issues: {e}", exc_info=True)
                        if "410" in error_msg or "Gone" in error_msg:
                            jira_context_parts.append("💡 This is a 410 Gone error. See JIRA_TROUBLESHOOTING.md for help.")
                
                # Fetch completed issues if needed
                if needs_completed_issues:
                    try:
                        completed_issues = jira_client.get_completed_issues(limit=20)
                        if completed_issues:
                            jira_context_parts.append(f"COMPLETED JIRA ISSUES ({len(completed_issues)} total):")
                            jira_context_parts.append("-" * 50)
                            for i, issue in enumerate(completed_issues[:10], 1):
                                key = issue.get('key', 'Unknown')
                                fields = issue.get('fields', {})
                                summary = fields.get('summary', 'No summary')
                                status = fields.get('status', {}).get('name', 'Unknown')
                                priority = fields.get('priority', {}).get('name', 'None')
                                project = fields.get('project', {}).get('name', 'Unknown')
                                resolution = fields.get('resolution', {})
                                resolution_name = resolution.get('name', 'Resolved') if resolution else 'Resolved'
                                resolved_date = fields.get('resolutiondate', 'Unknown')
                                jira_context_parts.append(f"  {i}. {key}: {summary}")
                                jira_context_parts.append(f"     Status: {status} | Priority: {priority} | Project: {project}")
                                jira_context_parts.append(f"     Resolution: {resolution_name} | Resolved: {resolved_date}")
                                jira_context_parts.append("")
                        else:
                            jira_context_parts.append("COMPLETED JIRA ISSUES: No completed issues found.")
                    except Exception as e:
                        error_msg = str(e)
                        jira_context_parts.append(f"❌ Error fetching completed issues: {error_msg}")
                        logger.error(f"Error fetching Jira completed issues: {e}", exc_info=True)
                        if "410" in error_msg or "Gone" in error_msg:
                            jira_context_parts.append("💡 This is a 410 Gone error. See JIRA_TROUBLESHOOTING.md for help.")
                
                # Fetch projects if needed
                if needs_jira_projects:
                    try:
                        projects = jira_client.get_projects()
                        if projects:
                            jira_context_parts.append(f"JIRA PROJECTS ({len(projects)} total):")
                            jira_context_parts.append("-" * 50)
                            for i, project in enumerate(projects[:10], 1):
                                key = project.get('key', 'Unknown')
                                name = project.get('name', 'Unknown')
                                jira_context_parts.append(f"  {i}. {key}: {name}")
                                jira_context_parts.append("")
                        else:
                            jira_context_parts.append("JIRA PROJECTS: No projects found.")
                    except Exception as e:
                        error_msg = str(e)
                        jira_context_parts.append(f"❌ Error fetching projects: {error_msg}")
                        logger.error(f"Error fetching Jira projects: {e}", exc_info=True)
                        if "410" in error_msg or "Gone" in error_msg:
                            jira_context_parts.append("💡 This is a 410 Gone error. See JIRA_TROUBLESHOOTING.md for help.")
                
                # Fetch sprints if needed
                if needs_jira_sprints:
                    try:
                        # Try to get active sprints (searches all boards)
                        active_sprints = jira_client.get_active_sprints()
                        if active_sprints:
                            jira_context_parts.append(f"ACTIVE JIRA SPRINTS ({len(active_sprints)} total):")
                            jira_context_parts.append("-" * 50)
                            for i, sprint in enumerate(active_sprints[:10], 1):
                                sprint_id = sprint.get('id', 'Unknown')
                                name = sprint.get('name', 'Unknown')
                                state = sprint.get('state', 'Unknown')
                                start_date = sprint.get('startDate', 'Not started')
                                end_date = sprint.get('endDate', 'Not ended')
                                board_name = sprint.get('board_name', 'Unknown')
                                jira_context_parts.append(f"  {i}. {name} (ID: {sprint_id})")
                                jira_context_parts.append(f"     State: {state} | Board: {board_name}")
                                jira_context_parts.append(f"     Period: {start_date} to {end_date}")
                                jira_context_parts.append("")
                        else:
                            jira_context_parts.append("ACTIVE JIRA SPRINTS: No active sprints found.")
                            jira_context_parts.append("💡 Tip: Active sprints are currently running sprints. Check if any sprints are in 'active' state.")
                    except Exception as e:
                        error_msg = str(e)
                        jira_context_parts.append(f"❌ Error fetching sprints: {error_msg}")
                        logger.error(f"Error fetching Jira sprints: {e}", exc_info=True)
                        if "410" in error_msg or "Gone" in error_msg:
                            jira_context_parts.append("💡 This is a 410 Gone error. See JIRA_TROUBLESHOOTING.md for help.")
                
                # If no specific data requested, fetch assigned issues by default
                if not needs_jira_issues and not needs_jira_projects and not needs_jira_sprints:
                    try:
                        # Extract username from email (e.g., "aupragathii@tamu.edu" -> "aupragathii")
                        username = user_email.split('@')[0] if '@' in user_email else user_email
                        
                        # Try with username first (since Jira stores assignee as username)
                        issues = jira_client.get_user_assigned_issues(email=username, limit=5, include_resolved=False)
                        if not issues:
                            issues = jira_client.get_user_assigned_issues(email=username, limit=5, include_resolved=True)
                        # Try with full email
                        if not issues:
                            issues = jira_client.get_user_assigned_issues(email=user_email, limit=5, include_resolved=True)
                        # Try with currentUser()
                        if not issues:
                            issues = jira_client.get_user_assigned_issues(limit=5, include_resolved=True)
                        # Last resort: Direct JQL query
                        if not issues:
                            try:
                                direct_jql = f'assignee = "{username}" ORDER BY updated DESC'
                                issues = jira_client.get_issues(direct_jql, max_results=5)
                            except:
                                pass
                        
                        if issues:
                            jira_context_parts.append(f"ASSIGNED JIRA ISSUES ({len(issues)} total):")
                            jira_context_parts.append("-" * 50)
                            for i, issue in enumerate(issues[:5], 1):
                                key = issue.get('key', 'Unknown')
                                fields = issue.get('fields', {})
                                summary = fields.get('summary', 'No summary')
                                status = fields.get('status', {}).get('name', 'Unknown')
                                assignee = fields.get('assignee', {})
                                assignee_email = assignee.get('emailAddress', 'Unknown') if assignee else 'Unassigned'
                                jira_context_parts.append(f"  {i}. {key}: {summary} [{status}]")
                                jira_context_parts.append(f"     Assignee: {assignee_email}")
                                jira_context_parts.append("")
                        else:
                            # Get current user info for debugging
                            try:
                                current_user = jira_client.get_current_user()
                                auth_email = current_user.get('emailAddress', jira_client.email)
                            except:
                                auth_email = jira_client.email
                            
                            jira_context_parts.append("ASSIGNED JIRA ISSUES: No issues found.")
                            jira_context_parts.append(f"   (Checked for: {auth_email})")
                            jira_context_parts.append("   💡 Tip: If you have issues assigned to a different email,")
                            jira_context_parts.append("      try querying with that specific email address.")
                    except Exception as e:
                        error_msg = str(e)
                        jira_context_parts.append(f"Error fetching assigned issues: {error_msg}")
                        logger.error(f"Error fetching Jira assigned issues (default): {e}", exc_info=True)
                
                if jira_context_parts:
                    jira_context = "\n".join(jira_context_parts)
                else:
                    jira_context = "No Jira data available. This may indicate:\n1. Jira connection issue (check credentials)\n2. No issues found\n3. API endpoint errors\n\n💡 TIP: Run 'python test_jira_connection.py' to diagnose."
                    
            except Exception as e:
                jira_context = f"Note: Could not fetch Jira context: {str(e)}"
        
        # Multi-source correlation
        correlation_context = None
        
        # GitHub-Jira correlation (commits mentioning Jira issues)
        if include_github_context and include_jira_context and github_context and jira_context:
            try:
                initialize_github_client()
                initialize_jira_client()
                
                username = None
                try:
                    user_info = github_client.get_user_info()
                    username = user_info.get('login', 'Unknown')
                except:
                    pass
                
                if username:
                    # Get recent commits to find Jira issue references
                    repos = context_cache.get_github_data('repos', username=username)
                    if repos is None:
                        repos = github_client.get_repositories(username, per_page=10)
                        context_cache.set_github_data('repos', repos, username=username)
                    
                    # Extract Jira issue keys from Jira context
                    jira_keys = re.findall(r'\b([A-Z]+-\d+)\b', jira_context)
                    
                    # Get commits and check for Jira references
                    commit_jira_links = []
                    for repo in repos[:5]:
                        owner = repo.get('owner', {}).get('login', username)
                        repo_name = repo.get('name', '')
                        try:
                            commits = github_client.get_commits(owner, repo_name, per_page=10)
                            for commit in commits:
                                commit_msg = commit.get('commit', {}).get('message', '')
                                # Look for Jira issue keys in commit message
                                commit_keys = re.findall(r'\b([A-Z]+-\d+)\b', commit_msg)
                                if commit_keys:
                                    for key in commit_keys:
                                        if key in jira_keys:
                                            commit_jira_links.append({
                                                'commit': commit.get('sha', '')[:7],
                                                'message': commit_msg[:100],
                                                'jira_key': key,
                                                'repo': f"{owner}/{repo_name}",
                                                'date': commit.get('commit', {}).get('author', {}).get('date', '')
                                            })
                        except:
                            continue
                    
                    if commit_jira_links:
                        correlation_parts = ["GITHUB-JIRA CORRELATION:"]
                        correlation_parts.append("-" * 50)
                        correlation_parts.append("Commits referencing Jira issues:")
                        for link in commit_jira_links[:10]:
                            correlation_parts.append(f"  • {link['jira_key']}: Commit {link['commit']} in {link['repo']}")
                            correlation_parts.append(f"    Message: {link['message']}")
                        correlation_context = "\n".join(correlation_parts)
            except Exception as e:
                logger.debug(f"GitHub-Jira correlation failed: {e}")
        
        # Calendar-GitHub correlation (if both available)
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
                calendar_github_correlation = context_correlator.format_correlations(correlations)
                
                # Combine with existing correlation context
                if correlation_context and calendar_github_correlation:
                    correlation_context = correlation_context + "\n\n" + calendar_github_correlation
                elif calendar_github_correlation:
                    correlation_context = calendar_github_correlation
            except Exception as e:
                # Silently fail correlation - not critical
                logger.debug(f"Calendar-GitHub correlation failed: {e}")
        
        # Combine and compress contexts
        combined_context = None
        if calendar_context or github_context or jira_context or correlation_context:
            context_parts = []
            if calendar_context:
                context_parts.append(calendar_context)
            if github_context:
                context_parts.append(github_context)
            if jira_context:
                context_parts.append(jira_context)
            if correlation_context:
                context_parts.append(correlation_context)
            
            combined_context = "\n\n".join(context_parts)
            
            # Compress context if too long
            combined_context = context_summarizer.compress_context(
                combined_context,
                target_length=8000  # ~2000 tokens
            )
        
        # For Jira-only queries, bypass Gemini and format response directly
        # This avoids safety filter issues with technical data
        is_jira_only_query = (
            include_jira_context and 
            not include_calendar_context and 
            not include_github_context and
            jira_context and
            any(keyword in message_lower for keyword in [
                'sprint', 'sprints', 'jira', 'issue', 'issues', 'ticket', 'tickets',
                'assigned', 'completed', 'resolved', 'board', 'boards', 'project', 'projects'
            ])
        )
        
        if is_jira_only_query:
            # Format Jira data directly without going through Gemini
            # This bypasses safety filters entirely
            try:
                formatted_response = _format_jira_response_directly(message, jira_context)
                return formatted_response
            except Exception as e:
                logger.debug(f"Direct Jira formatting failed, falling back to Gemini: {e}")
                # Fall through to Gemini
        
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

