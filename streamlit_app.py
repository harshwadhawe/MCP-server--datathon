#!/usr/bin/env python3
"""
Project Management Assistant Dashboard
A lightweight dashboard integrating GitHub, Google Calendar, and Jira for project management.
"""

import streamlit as st
import sys
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pytz

# Load environment variables
load_dotenv()

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.server import chat
from src.calendar_client import CalendarClient
from src.github_client import GitHubClient
from src.jira_client import JiraClient
from src.query_analyzer import QueryAnalyzer

# Page configuration
st.set_page_config(
    page_title="Project Management Assistant",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern UI
st.markdown("""
    <style>
    .main-header {
        font-size: 3rem;
        font-weight: 700;
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .mcp-highlight {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
    }
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border-left: 4px solid #667eea;
    }
    .event-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 0.5rem;
        border-left: 3px solid #667eea;
    }
    .repo-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 0.5rem;
        border-left: 3px solid #28a745;
    }
    .jira-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 0.5rem;
        border-left: 3px solid #0052CC;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 10px 20px;
    }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if "calendar_client" not in st.session_state:
    st.session_state.calendar_client = None

if "github_client" not in st.session_state:
    st.session_state.github_client = None

if "jira_client" not in st.session_state:
    st.session_state.jira_client = None

if "last_processed_query" not in st.session_state:
    st.session_state.last_processed_query = None

if "response" not in st.session_state:
    st.session_state.response = None

def initialize_clients():
    """Initialize calendar, GitHub, and Jira clients."""
    try:
        if st.session_state.calendar_client is None:
            credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/credentials.json")
            token_path = os.getenv("GOOGLE_TOKEN_PATH", "config/token.json")
            # Redirect stdout during initialization to avoid interfering with Streamlit
            import sys
            original_stdout = sys.stdout
            try:
                sys.stdout = sys.stderr
                st.session_state.calendar_client = CalendarClient(credentials_path, token_path)
            finally:
                sys.stdout = original_stdout
    except Exception as e:
        st.session_state.calendar_client = None
        # Don't show error to user, just silently fail
    
    try:
        if st.session_state.github_client is None:
            st.session_state.github_client = GitHubClient()
    except Exception as e:
        st.session_state.github_client = None
        # Don't show error to user, just silently fail
    
    try:
        if st.session_state.jira_client is None:
            base_url = os.getenv("JIRA_URL")
            email = os.getenv("JIRA_EMAIL")
            api_token = os.getenv("JIRA_API_TOKEN")
            
            if base_url and email and api_token:
                st.session_state.jira_client = JiraClient(
                    base_url=base_url,
                    email=email,
                    api_token=api_token
                )
    except Exception as e:
        st.session_state.jira_client = None
        # Don't show error to user, just silently fail

def format_time(dt_str):
    """Format datetime string for display."""
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt.strftime('%I:%M %p')
    except:
        return dt_str

def format_date(dt_str):
    """Format date string for display."""
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt.strftime('%b %d, %Y')
    except:
        return dt_str

def get_calendar_summary():
    """Get calendar summary for today and upcoming week."""
    if st.session_state.calendar_client is None:
        return [], []
    
    try:
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = today_start + timedelta(days=7)
        
        events = st.session_state.calendar_client.get_events_from_all_calendars(
            time_min=today_start,
            time_max=week_end,
            max_results=50
        )
        
        today_events = []
        upcoming_events = []
        
        for event in events:
            start = event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')
            if start:
                try:
                    event_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    event['parsed_start'] = event_dt
                    
                    if event_dt.date() == now.date():
                        today_events.append(event)
                    elif event_dt.date() > now.date():
                        upcoming_events.append(event)
                except:
                    pass
        
        # Sort events by time
        today_events.sort(key=lambda x: x.get('parsed_start', datetime.min))
        upcoming_events.sort(key=lambda x: x.get('parsed_start', datetime.min))
        
        return today_events, upcoming_events[:10]
    except Exception as e:
        return [], []

def get_github_summary():
    """Get GitHub activity summary."""
    if st.session_state.github_client is None:
        return None
    
    try:
        user_info = st.session_state.github_client.get_user_info()
        repos = st.session_state.github_client.get_repositories(per_page=10)
        
        # Get issues and PRs
        all_issues = []
        all_prs = []
        
        for repo in repos[:5]:
            owner = repo.get('owner', {}).get('login', user_info.get('login'))
            repo_name = repo.get('name', '')
            try:
                issues = st.session_state.github_client.get_issues(owner, repo_name, state='open', per_page=5)
                all_issues.extend(issues)
            except:
                pass
            
            try:
                prs = st.session_state.github_client.get_pull_requests(owner, repo_name, state='open', per_page=5)
                all_prs.extend(prs)
            except:
                pass
        
        return {
            'user_info': user_info,
            'repos': repos,
            'open_issues': all_issues[:10],
            'open_prs': all_prs[:10]
        }
    except Exception as e:
        return None

def get_jira_summary():
    """Get Jira activity summary."""
    if st.session_state.jira_client is None:
        return None
    
    try:
        # Get assigned issues
        issues = st.session_state.jira_client.get_user_assigned_issues(limit=10)
        
        # Get projects
        projects = st.session_state.jira_client.get_projects()
        
        return {
            'assigned_issues': issues,
            'projects': projects[:10] if projects else []
        }
    except Exception as e:
        return None

def main():
    # Header
    st.markdown('<h1 class="main-header">📊 Project Management <span class="mcp-highlight">MCP Server</span> Assistant</h1>', unsafe_allow_html=True)
    
    # Initialize clients
    initialize_clients()
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.session_state.calendar_client = None
            st.session_state.github_client = None
            st.session_state.jira_client = None
            initialize_clients()
            st.rerun()
        
        st.divider()
        
        # Status indicators
        st.subheader("🔌 Connections")
        calendar_status = "✅ Connected" if st.session_state.calendar_client else "❌ Not Connected"
        github_status = "✅ Connected" if st.session_state.github_client else "❌ Not Connected"
        jira_status = "✅ Connected" if st.session_state.jira_client else "❌ Not Connected"
        
        st.write(f"**Calendar:** {calendar_status}")
        st.write(f"**GitHub:** {github_status}")
        st.write(f"**Jira:** {jira_status}")
        
        if not st.session_state.calendar_client:
            st.info("💡 Configure Google Calendar credentials to enable calendar features.")
        if not st.session_state.github_client:
            st.info("💡 Set GITHUB_TOKEN in .env to enable GitHub features.")
        if not st.session_state.jira_client:
            st.info("💡 Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN in .env to enable Jira features.")
        
        st.divider()
        
        st.subheader("💬 AI Assistant")
        st.caption("Ask questions about your projects, schedule, GitHub activity, or Jira issues")
    
    # Main content - AI Assistant only
    st.header("💬 AI Assistant")
    st.caption("Ask me anything about your projects, schedule, GitHub activity, or Jira issues")
    
    # Predefined queries organized by category
    st.subheader("📋 Predefined Queries")
    
    # Calendar queries
    st.markdown("#### 📅 Calendar & Schedule")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📅 What's my schedule today?", use_container_width=True):
            st.session_state.quick_query = "What's my schedule today?"
            st.rerun()
        if st.button("📆 What meetings do I have this week?", use_container_width=True):
            st.session_state.quick_query = "What meetings do I have this week?"
            st.rerun()
        if st.button("⏰ When am I free tomorrow?", use_container_width=True):
            st.session_state.quick_query = "When am I free tomorrow?"
            st.rerun()
    
    with col2:
        if st.button("📋 Summarize my schedule for Monday", use_container_width=True):
            st.session_state.quick_query = "Summarize my schedule for Monday"
            st.rerun()
        if st.button("🔍 Am I free next week?", use_container_width=True):
            st.session_state.quick_query = "Am I free next week?"
            st.rerun()
        if st.button("📊 Show upcoming events", use_container_width=True):
            st.session_state.quick_query = "Show me my upcoming events"
            st.rerun()
    
    with col3:
        if st.button("⏳ Check availability at 2 PM", use_container_width=True):
            st.session_state.quick_query = "Am I available tomorrow at 2 PM?"
            st.rerun()
        if st.button("📅 What's on my calendar next week?", use_container_width=True):
            st.session_state.quick_query = "What's on my calendar next week?"
            st.rerun()
        if st.button("🔎 Detect scheduling conflicts", use_container_width=True):
            st.session_state.quick_query = "Are there any scheduling conflicts this week?"
            st.rerun()
    
    st.divider()
    
    # GitHub queries
    st.markdown("#### 🐙 GitHub & Repositories")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("📦 Show my repositories", use_container_width=True):
            st.session_state.quick_query = "Show me my recent repositories"
            st.rerun()
        if st.button("🐛 What issues need attention?", use_container_width=True):
            st.session_state.quick_query = "What are my open issues?"
            st.rerun()
        if st.button("🔀 Show open pull requests", use_container_width=True):
            st.session_state.quick_query = "What PRs are open in my repos?"
            st.rerun()
    
    with col2:
        if st.button("🚀 Show current deployments", use_container_width=True):
            st.session_state.quick_query = "Show current deployments setup on GitHub"
            st.rerun()
        if st.button("📝 Recent commits", use_container_width=True):
            st.session_state.quick_query = "Show me my recent commits"
            st.rerun()
        if st.button("📊 GitHub activity summary", use_container_width=True):
            st.session_state.quick_query = "Give me a summary of my GitHub activity"
            st.rerun()
    
    with col3:
        if st.button("🔍 Search repositories", use_container_width=True):
            st.session_state.quick_query = "What repositories do I have?"
            st.rerun()
        if st.button("📈 Production deployments", use_container_width=True):
            st.session_state.quick_query = "What deployments are live in production?"
            st.rerun()
        if st.button("📚 Repository details", use_container_width=True):
            st.session_state.quick_query = "Tell me about my repositories"
            st.rerun()
    
    st.divider()
    
    # Jira queries
    st.markdown("#### 🎯 Jira & Issues")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🎫 My assigned issues", use_container_width=True):
            if st.session_state.jira_client:
                try:
                    with st.spinner("Fetching your assigned issues..."):
                        issues = st.session_state.jira_client.get_user_assigned_issues(limit=20, include_resolved=False)
                        if not issues:
                            result = "No active assigned Jira issues found."
                        else:
                            result_parts = [f"My Assigned Jira Issues ({len(issues)} total):\n"]
                            for i, issue in enumerate(issues, 1):
                                key = issue.get('key', 'Unknown')
                                fields = issue.get('fields', {})
                                summary = fields.get('summary', 'No summary')
                                status = fields.get('status', {}).get('name', 'Unknown')
                                priority = fields.get('priority', {}).get('name', 'None')
                                project = fields.get('project', {}).get('name', 'Unknown')
                                result_parts.append(f"{i}. {key}: {summary}")
                                result_parts.append(f"   Status: {status} | Priority: {priority} | Project: {project}")
                                result_parts.append(f"   URL: {st.session_state.jira_client.base_url}/browse/{key}")
                                result_parts.append("")
                            result = "\n".join(result_parts)
                        st.session_state.response = result
                        st.rerun()
                except Exception as e:
                    st.session_state.response = f"Error: {str(e)}"
                    st.rerun()
            else:
                st.session_state.quick_query = "What Jira issues are assigned to me?"
                st.rerun()
        if st.button("📋 Show all projects", use_container_width=True):
            st.session_state.quick_query = "Show me all my Jira projects"
            st.rerun()
        if st.button("🔍 Search issues", use_container_width=True):
            st.session_state.quick_query = "What are my open Jira issues?"
            st.rerun()
    
    with col2:
        if st.button("📊 Issue summary", use_container_width=True):
            st.session_state.quick_query = "Give me a summary of my Jira issues"
            st.rerun()
        if st.button("🚀 Active sprints", use_container_width=True):
            if st.session_state.jira_client:
                try:
                    with st.spinner("Fetching active sprints..."):
                        active_sprints = st.session_state.jira_client.get_active_sprints()
                        if not active_sprints:
                            result = "No active sprints found across all boards."
                        else:
                            result_parts = [f"Active Jira Sprints ({len(active_sprints)} total):\n"]
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
                            result = "\n".join(result_parts)
                        st.session_state.response = result
                        st.rerun()
                except Exception as e:
                    st.session_state.response = f"Error: {str(e)}"
                    st.rerun()
            else:
                st.session_state.quick_query = "What are my active Jira sprints?"
                st.rerun()
        if st.button("⏰ Recent activity", use_container_width=True):
            st.session_state.quick_query = "Show me recent Jira activity"
            st.rerun()
    
    with col3:
        if st.button("📈 Project overview", use_container_width=True):
            st.session_state.quick_query = "Tell me about my Jira projects"
            st.rerun()
        if st.button("🐛 High priority issues", use_container_width=True):
            st.session_state.quick_query = "What are my high priority Jira issues?"
            st.rerun()
        if st.button("✅ Completed tasks", use_container_width=True):
            if st.session_state.jira_client:
                try:
                    with st.spinner("Fetching completed issues..."):
                        issues = st.session_state.jira_client.get_completed_issues(limit=20)
                        if not issues:
                            result = "No completed Jira issues found."
                        else:
                            result_parts = [f"My Completed Jira Issues ({len(issues)} total):\n"]
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
                                result_parts.append(f"   URL: {st.session_state.jira_client.base_url}/browse/{key}")
                                result_parts.append("")
                            result = "\n".join(result_parts)
                        st.session_state.response = result
                        st.rerun()
                except Exception as e:
                    st.session_state.response = f"Error: {str(e)}"
                    st.rerun()
            else:
                st.session_state.quick_query = "Show me my completed Jira issues"
                st.rerun()
    
    # Add a button for boards
    st.markdown("#### 📊 Jira Boards & Sprints")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📋 Show all boards", use_container_width=True):
            if st.session_state.jira_client:
                try:
                    with st.spinner("Fetching Jira boards..."):
                        boards = st.session_state.jira_client.get_boards()
                        if not boards:
                            result = "No Jira boards found."
                        else:
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
                            result = "\n".join(result_parts)
                        st.session_state.response = result
                        st.rerun()
                except Exception as e:
                    st.session_state.response = f"Error: {str(e)}"
                    st.rerun()
            else:
                st.session_state.quick_query = "Show me all my Jira boards"
                st.rerun()
    
    st.divider()
    
    # Custom query input
    st.subheader("💭 Custom Query")
    
    # Use a form to prevent infinite loops
    with st.form("custom_query_form", clear_on_submit=True):
        user_input = st.text_input("Enter your question:", placeholder="e.g., What meetings do I have today?", key="user_query_input")
        submitted = st.form_submit_button("Submit", use_container_width=True)
        
        if submitted and user_input:
            # Only process if this is a new query
            if user_input != st.session_state.last_processed_query:
                st.session_state.last_processed_query = user_input
                st.session_state.pending_query = user_input
                st.rerun()
    
    # Process pending query outside the form to avoid spinner issues
    if hasattr(st.session_state, 'pending_query') and st.session_state.pending_query:
        query = st.session_state.pending_query
        st.session_state.pending_query = None  # Clear it immediately
        
        with st.spinner("Thinking..."):
            try:
                # Auto-detect GitHub and Jira queries
                message_lower = query.lower()
                include_github = any(keyword in message_lower for keyword in 
                                   ['github', 'repo', 'repository', 'issue', 'pr', 'pull request', 'commit',
                                    'deployment', 'deploy', 'deployed', 'deploying', 'production', 'staging'])
                # Enhanced Jira keyword detection - includes more variations
                include_jira = any(keyword in message_lower for keyword in 
                                 ['jira', 'ticket', 'tickets', 'task', 'tasks', 'bug', 'bugs', 'sprint', 'sprints',
                                  'jql', 'project', 'projects', 'assignee', 'assign', 'assigned', 'completed',
                                  'resolved', 'board', 'boards', 'active sprint', 'my issues', 'my jira',
                                  'jira issues', 'jira project', 'jira sprint'])
                
                response = chat(
                    message=query,
                    include_calendar_context=True,
                    include_github_context=include_github,
                    include_jira_context=include_jira
                )
                
                st.session_state.response = response
                st.rerun()
            except Exception as e:
                st.session_state.response = f"Error: {str(e)}"
                st.rerun()
    
    # Handle quick query
    if hasattr(st.session_state, 'quick_query') and st.session_state.quick_query:
        query = st.session_state.quick_query
        st.session_state.quick_query = None  # Clear it immediately
        st.session_state.last_processed_query = query  # Track it
        
        with st.spinner("Thinking..."):
            try:
                message_lower = query.lower()
                include_github = any(keyword in message_lower for keyword in 
                                   ['github', 'repo', 'repository', 'issue', 'pr', 'pull request', 'commit',
                                    'deployment', 'deploy', 'deployed', 'deploying', 'production', 'staging'])
                include_jira = any(keyword in message_lower for keyword in 
                                 ['jira', 'ticket', 'tickets', 'task', 'tasks', 'bug', 'bugs', 'sprint', 'sprints',
                                  'jql', 'project', 'projects', 'assignee', 'assign'])
                
                response = chat(
                    message=query,
                    include_calendar_context=True,
                    include_github_context=include_github,
                    include_jira_context=include_jira
                )
                
                st.session_state.response = response
                st.rerun()
            except Exception as e:
                st.session_state.response = f"Error: {str(e)}"
                st.rerun()
    
    # Display response section (single unified section for all outputs)
    if hasattr(st.session_state, 'response') and st.session_state.response:
        st.markdown("### Response:")
        st.write(st.session_state.response)

if __name__ == "__main__":
    main()
