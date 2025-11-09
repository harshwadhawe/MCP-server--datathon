#!/usr/bin/env python3
"""Entry point for the Calendar & GitHub MCP Server."""

import sys
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Configure logging to stderr (stdout is reserved for JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr,
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

def main():
    """Main entry point for the MCP server."""
    try:
        logger.info("=" * 60)
        logger.info("Calendar, GitHub & Jira MCP Server")
        logger.info("=" * 60)
        logger.info(f"Starting server at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("Server is ready and listening for JSON-RPC messages on stdin/stdout")
        logger.info("Available tools:")
        logger.info("Calendar Tools:")
        logger.info("  - get_calendar_context: Get calendar context for queries")
        logger.info("  - check_availability: Check availability at specific times")
        logger.info("  - get_upcoming_events: Get upcoming calendar events")
        logger.info("  - detect_conflicts: Detect scheduling conflicts")
        logger.info("GitHub Tools:")
        logger.info("  - get_github_issues: Get issues for a repository")
        logger.info("  - get_github_pull_requests: Get pull requests for a repository")
        logger.info("  - get_github_repositories: Get repositories for a user")
        logger.info("  - get_github_deployments: Get deployments for repositories")
        logger.info("Jira Tools:")
        logger.info("  - get_jira_current_user: Get information about authenticated user")
        logger.info("  - test_jira_assignee_query: Test assignee queries to debug issues")
        logger.info("  - get_jira_projects: Get all accessible Jira projects")
        logger.info("  - get_jira_issues: Get issues using JQL query")
        logger.info("  - get_jira_issue_details: Get details for a specific issue")
        logger.info("  - get_jira_user_issues: Get issues assigned to a user")
        logger.info("  - get_jira_sprints: Get sprints for a board")
        logger.info("AI Assistant:")
        logger.info("  - chat: Chat with AI assistant about calendar, GitHub, and Jira")
        logger.info("=" * 60)
        logger.info("Waiting for client connections...")
        logger.info("(Press Ctrl+C to stop)")
        logger.info("")
        
        from src.server import mcp
        mcp.run()
        
    except KeyboardInterrupt:
        logger.info("\nServer shutdown requested by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error in MCP server: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()

