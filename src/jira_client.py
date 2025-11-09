"""
Jira API client for fetching issues, projects, and sprint details.
"""

import os
import sys
import json
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional


class JiraClient:
    """Client for interacting with the Jira REST API."""

    def __init__(self, base_url: str, email: str, api_token: str, verify_ssl: bool = True):
        """
        Initialize the Jira client.

        Args:
            base_url: Base URL of the Jira instance (e.g., "https://yourdomain.atlassian.net")
            email: User email associated with the Jira account
            api_token: Jira API token generated from https://id.atlassian.com/manage/api-tokens
            verify_ssl: Whether to verify SSL certificates (default True)
        """
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.verify_ssl = verify_ssl
        self._authenticated_user = None  # Will be set during connection validation

        # Session setup for connection reuse
        self.session = requests.Session()
        # Use Basic Auth with email and API token
        # The API token is tied to a specific Jira account, so authentication
        # identifies "who you are" based on the account associated with the token
        self.session.auth = (self.email, self.api_token)
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Atlassian-Token": "no-check"  # Some Jira instances require this
        })

        # Validate connection on startup
        try:
            self._validate_connection()
        except Exception as e:
            sys.stderr.write(f"[JiraClient] ⚠️ Connection validation failed: {e}\n")

    def _validate_connection(self):
        """Validate Jira connection by fetching the current user."""
        # Try API v3 first, then v2 as fallback
        api_versions = [3, 2]
        last_error = None
        
        for api_version in api_versions:
            try:
                url = f"{self.base_url}/rest/api/{api_version}/myself"
                response = self.session.get(url, verify=self.verify_ssl)
                
                if response.status_code == 200:
                    # Store the authenticated user info for later use
                    user_data = response.json()
                    self._authenticated_user = user_data
                    return  # Success - connection validated
                elif response.status_code == 410:
                    # Try next API version
                    continue
                else:
                    error_msg = response.text
                    raise RuntimeError(f"Authentication failed ({response.status_code}): {error_msg}")
            except requests.exceptions.RequestException as e:
                last_error = e
                if api_version == api_versions[-1]:
                    # Last version failed, raise error
                    if "410" in str(e) or "Gone" in str(e):
                        raise RuntimeError(
                            f"Jira authentication endpoints returned 410 Gone for both API v3 and v2. "
                            f"Please verify:\n"
                            f"1. Your Jira URL is correct: {self.base_url}\n"
                            f"2. Your email and API token are valid\n"
                            f"3. Your Jira instance supports REST API\n"
                            f"Error: {str(e)}"
                        )
                    raise RuntimeError(f"Authentication failed: {str(e)}")
                continue
        
        # If we get here, all versions returned 410
        raise RuntimeError(
            f"Jira authentication failed - all API versions returned 410 Gone. "
            f"Please check your Jira instance configuration or contact your administrator."
        )
    
    def get_current_user(self) -> Dict:
        """
        Get information about the currently authenticated user.
        
        Returns:
            Dictionary with user information (email, displayName, accountId, etc.)
        """
        if hasattr(self, '_authenticated_user') and self._authenticated_user:
            return self._authenticated_user
        
        # Fetch current user info
        api_versions = [3, 2]
        for api_version in api_versions:
            try:
                url = f"{self.base_url}/rest/api/{api_version}/myself"
                response = self.session.get(url, verify=self.verify_ssl)
                if response.status_code == 200:
                    user_data = response.json()
                    self._authenticated_user = user_data
                    return user_data
            except:
                continue
        
        # Fallback: return email-based info
        return {
            'emailAddress': self.email,
            'displayName': self.email,
            'accountId': 'unknown'
        }
    
    def test_assignee_query(self, assignee_value: str) -> Dict:
        """
        Test a JQL query with a specific assignee value and return detailed results.
        Useful for debugging why issues aren't being found.
        
        Args:
            assignee_value: The value to query (username, email, accountId, etc.)
        
        Returns:
            Dictionary with query results and debugging info
        """
        result = {
            'assignee_value': assignee_value,
            'queries_tried': [],
            'results': [],
            'errors': []
        }
        
        # Try different JQL formats
        jql_variations = [
            f'assignee = "{assignee_value}"',
            f'assignee = {assignee_value}',  # Without quotes
            f'assignee ~ "{assignee_value}"',  # Contains
        ]
        
        for jql in jql_variations:
            try:
                result['queries_tried'].append(jql)
                issues = self.get_issues(jql, max_results=10)
                if issues:
                    result['results'].extend(issues)
                    result['successful_query'] = jql
            except Exception as e:
                result['errors'].append(f"{jql}: {str(e)}")
        
        return result
    
    def get_user_assigned_issues_by_account_id(self, account_id: str, limit: int = 10) -> List[Dict]:
        """
        Get issues assigned to a user by their account ID.
        This is often more reliable than email/username queries.
        
        Args:
            account_id: Jira account ID
            limit: Maximum number of issues to return
        
        Returns:
            List of issue dictionaries
        """
        jql = f'assignee = "{account_id}" ORDER BY updated DESC'
        try:
            return self.get_issues(jql, max_results=limit)
        except:
            # Try without quotes
            jql = f'assignee = {account_id} ORDER BY updated DESC'
            return self.get_issues(jql, max_results=limit)

    def get_projects(self) -> List[Dict]:
        """List all accessible Jira projects."""
        url = f"{self.base_url}/rest/api/3/project/search"
        try:
            response = self.session.get(url, verify=self.verify_ssl)
            
            # Handle 410 Gone error - try API v2 as fallback
            if response.status_code == 410:
                url_v2 = f"{self.base_url}/rest/api/2/project"
                response = self.session.get(url_v2, verify=self.verify_ssl)
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, list) else []
            else:
                response.raise_for_status()
                data = response.json()
                return data.get("values", [])
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 410:
                raise RuntimeError(
                    "Jira API endpoint returned 410 Gone. The project search endpoint may be deprecated. "
                    "Please check your Jira instance version and API compatibility."
                )
            raise RuntimeError(f"Error fetching Jira projects: {str(e)}")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Error fetching Jira projects: {str(e)}")

    def get_issues(
        self,
        jql: str,
        max_results: int = 20,
        fields: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Fetch issues using a JQL query.

        Args:
            jql: Jira Query Language (JQL) string (e.g., "assignee=currentUser() AND status!=Done")
            max_results: Maximum number of issues to return
            fields: List of fields to include in the response

        Returns:
            List of issue dictionaries
        """
        url = f"{self.base_url}/rest/api/3/search"
        params = {
            "jql": jql,
            "maxResults": max_results,
        }
        if fields:
            params["fields"] = ",".join(fields)

        # Try API v3 first, then fallback to v2 if needed
        api_versions = [3, 2]
        last_error = None
        
        for api_version in api_versions:
            try:
                url = f"{self.base_url}/rest/api/{api_version}/search"
                response = self.session.get(url, params=params, verify=self.verify_ssl)
                
                if response.status_code == 410:
                    # Try next API version
                    continue
                
                response.raise_for_status()
                data = response.json()
                return data.get("issues", [])
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 410:
                    # Try next API version
                    last_error = e
                    continue
                raise RuntimeError(f"Error fetching Jira issues: {str(e)}")
            except requests.exceptions.RequestException as e:
                # For non-HTTP errors, try next version once, then raise
                if api_version == api_versions[-1]:
                    raise RuntimeError(f"Error fetching Jira issues: {str(e)}")
                last_error = e
                continue
        
        # If all API versions failed with 410
        if last_error:
            raise RuntimeError(
                f"Jira API endpoints returned 410 Gone for both API v3 and v2. "
                f"This may indicate:\n"
                f"1. Your Jira instance version is very old and uses different endpoints\n"
                f"2. The REST API is disabled on your Jira instance\n"
                f"3. Your Jira URL is incorrect: {self.base_url}\n"
                f"Please check your Jira instance configuration or contact your Jira administrator."
            )
        
        return []

    def get_issue_details(self, issue_key: str) -> Dict:
        """Fetch detailed information about a specific issue."""
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        try:
            response = self.session.get(url, verify=self.verify_ssl)
            
            # Handle 410 Gone error - try API v2 as fallback
            if response.status_code == 410:
                url_v2 = f"{self.base_url}/rest/api/2/issue/{issue_key}"
                response = self.session.get(url_v2, verify=self.verify_ssl)
                response.raise_for_status()
            else:
                response.raise_for_status()
            
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 410:
                raise RuntimeError(
                    f"Jira API endpoint returned 410 Gone for issue '{issue_key}'. "
                    "Please check your Jira instance version and API compatibility."
                )
            raise RuntimeError(f"Error fetching Jira issue '{issue_key}': {str(e)}")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Error fetching Jira issue '{issue_key}': {str(e)}")

    def get_query_debug_info(self) -> Dict:
        """Get debugging information about the last query attempt."""
        return getattr(self, '_last_query_debug', {})
    
    def get_user_assigned_issues(self, email: Optional[str] = None, limit: int = 10, include_resolved: bool = False) -> List[Dict]:
        """
        Get issues assigned to a specific user (or current user if None).

        Args:
            email: User email (optional, defaults to authenticated user)
            limit: Maximum number of issues to return
            include_resolved: If True, include resolved/completed issues (default: False)
        """
        # Extract username from email if provided (e.g., "aupragathii@tamu.edu" -> "aupragathii")
        username = None
        if email and '@' in email:
            username = email.split('@')[0]
        
        # Try multiple JQL query variations to handle different Jira versions
        jql_queries = []
        
        if email:
            # Use provided email - try with and without status filters
            # Also try username format (Jira might store assignee as username, not email)
            email_variations = [email]
            if username:
                email_variations.append(username)
            
            for email_var in email_variations:
                if include_resolved:
                    # Get ALL issues (including resolved)
                    jql_queries.append(f'assignee = "{email_var}" ORDER BY updated DESC')
                else:
                    # Only unresolved issues
                    jql_queries.extend([
                        f'assignee = "{email_var}" AND resolution = Unresolved ORDER BY updated DESC',
                        f'assignee = "{email_var}" AND status != Done ORDER BY updated DESC',
                        f'assignee = "{email_var}" AND status != "Done" ORDER BY updated DESC',
                        f'assignee = "{email_var}" AND statusCategory != Done ORDER BY updated DESC',
                    ])
        else:
            # Try currentUser() first, then fallback to email and username
            email_to_try = self.email
            username_to_try = email_to_try.split('@')[0] if '@' in email_to_try else None
            
            if include_resolved:
                jql_queries = [
                    "assignee = currentUser() ORDER BY updated DESC",
                    f'assignee = "{email_to_try}" ORDER BY updated DESC',
                ]
                if username_to_try:
                    jql_queries.append(f'assignee = "{username_to_try}" ORDER BY updated DESC')
            else:
                jql_queries = [
                    "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC",
                    "assignee = currentUser() AND status != Done ORDER BY updated DESC",
                    "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC",
                    f'assignee = "{email_to_try}" AND resolution = Unresolved ORDER BY updated DESC',
                    f'assignee = "{email_to_try}" AND status != Done ORDER BY updated DESC',
                ]
                if username_to_try:
                    jql_queries.extend([
                        f'assignee = "{username_to_try}" AND resolution = Unresolved ORDER BY updated DESC',
                        f'assignee = "{username_to_try}" AND status != Done ORDER BY updated DESC',
                    ])
        
        # Try each JQL query until one works
        last_error = None
        last_jql = None
        successful_queries = []  # Track which queries succeeded but returned empty
        
        for jql in jql_queries:
            try:
                last_jql = jql
                issues = self.get_issues(jql, max_results=limit)
                if issues:
                    # Success! Return the issues
                    return issues
                else:
                    # Query succeeded but returned no results
                    successful_queries.append(jql)
                    # Continue to try next query (might be a status filter issue)
                    continue
            except Exception as e:
                last_error = e
                # If it's not a 410 error, don't try other queries
                if "410" not in str(e) and "Gone" not in str(e):
                    raise
                # Continue to next query if it's a 410 error
                continue
        
        # If all queries returned empty or failed, try a simple query without filters
        if not include_resolved:
            try:
                target_email = email or self.email
                # Try multiple formats: email, username, and case variations
                email_variations = [
                    target_email,
                    target_email.lower(),
                    target_email.upper(),
                ]
                
                # Add username if email format
                if '@' in target_email:
                    username = target_email.split('@')[0]
                    email_variations.extend([username, username.lower(), username.upper()])
                
                for email_var in email_variations:
                    simple_jql = f'assignee = "{email_var}" ORDER BY updated DESC'
                    try:
                        issues = self.get_issues(simple_jql, max_results=limit)
                        if issues:
                            return issues
                    except:
                        continue
            except:
                pass
        
        # If we got here, all queries succeeded but returned no results
        # Store this info for debugging
        self._last_query_debug = {
            'queries_tried': jql_queries,
            'successful_but_empty': successful_queries,
            'target_email': email or self.email,
            'last_jql': last_jql,
            'last_error': str(last_error) if last_error else None
        }
        
        # If all queries failed with 410, raise a helpful error
        if last_error and ("410" in str(last_error) or "Gone" in str(last_error)):
            raise RuntimeError(
                f"All JQL query attempts failed with 410 Gone error. "
                f"This suggests your Jira instance may not support the REST API endpoints being used. "
                f"Please check:\n"
                f"1. Your Jira instance version (may need API v2 instead of v3)\n"
                f"2. Your Jira URL is correct: {self.base_url}\n"
                f"3. Your authentication credentials are valid\n"
                f"Last error: {str(last_error)}\n"
                f"Last JQL tried: {last_jql}"
            )
        
        return []

    def get_recent_activity(self, hours: int = 24) -> List[Dict]:
        """
        Get issues updated in the past N hours.

        Args:
            hours: Time range in hours
        """
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
        jql = f"updated >= \"{since}\" ORDER BY updated DESC"
        return self.get_issues(jql, max_results=20)

    def get_completed_issues(self, email: Optional[str] = None, limit: int = 20) -> List[Dict]:
        """
        Get completed/resolved issues assigned to a specific user (or current user if None).

        Args:
            email: User email (optional, defaults to authenticated user)
            limit: Maximum number of issues to return
        """
        # Extract username from email if provided
        username = None
        if email and '@' in email:
            username = email.split('@')[0]
        
        # Try multiple JQL query variations to handle different Jira versions
        jql_queries = []
        
        if email:
            email_variations = [email]
            if username:
                email_variations.append(username)
            
            for email_var in email_variations:
                jql_queries.extend([
                    f'assignee = "{email_var}" AND resolution != Unresolved ORDER BY updated DESC',
                    f'assignee = "{email_var}" AND status = Done ORDER BY updated DESC',
                    f'assignee = "{email_var}" AND statusCategory = Done ORDER BY updated DESC',
                    f'assignee = "{email_var}" AND resolution IS NOT EMPTY ORDER BY updated DESC',
                ])
        else:
            # Try currentUser() first, then fallback to email and username
            email_to_try = self.email
            username_to_try = email_to_try.split('@')[0] if '@' in email_to_try else None
            
            jql_queries = [
                "assignee = currentUser() AND resolution != Unresolved ORDER BY updated DESC",
                "assignee = currentUser() AND status = Done ORDER BY updated DESC",
                "assignee = currentUser() AND statusCategory = Done ORDER BY updated DESC",
                "assignee = currentUser() AND resolution IS NOT EMPTY ORDER BY updated DESC",
                f'assignee = "{email_to_try}" AND resolution != Unresolved ORDER BY updated DESC',
                f'assignee = "{email_to_try}" AND status = Done ORDER BY updated DESC',
            ]
            if username_to_try:
                jql_queries.extend([
                    f'assignee = "{username_to_try}" AND resolution != Unresolved ORDER BY updated DESC',
                    f'assignee = "{username_to_try}" AND status = Done ORDER BY updated DESC',
                ])
        
        # Try each JQL query until one works
        for jql in jql_queries:
            try:
                issues = self.get_issues(jql, max_results=limit)
                if issues:
                    return issues
            except Exception as e:
                # If it's not a 410 error, don't try other queries
                if "410" not in str(e) and "Gone" not in str(e):
                    raise
                continue
        
        return []

    def get_boards(self) -> List[Dict]:
        """
        Fetch all accessible Jira boards (Kanban/Scrum).

        Returns:
            List of board dictionaries
        """
        url = f"{self.base_url}/rest/agile/1.0/board"
        try:
            response = self.session.get(url, verify=self.verify_ssl)
            response.raise_for_status()
            data = response.json()
            return data.get("values", [])
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Error fetching Jira boards: {str(e)}")

    def get_active_sprints(self, board_id: Optional[str] = None) -> List[Dict]:
        """
        Fetch active sprints for a given board or all boards.

        Args:
            board_id: ID of the Jira board (optional, if None, searches all boards)
        
        Returns:
            List of active sprint dictionaries
        """
        active_sprints = []
        
        if board_id:
            # Get sprints for specific board
            sprints = self.get_sprints(board_id)
            active_sprints = [s for s in sprints if s.get('state', '').lower() == 'active']
        else:
            # Get all boards and find active sprints
            boards = self.get_boards()
            for board in boards:
                try:
                    board_id = board.get('id')
                    if board_id:
                        sprints = self.get_sprints(str(board_id))
                        active = [s for s in sprints if s.get('state', '').lower() == 'active']
                        # Add board info to each sprint
                        for sprint in active:
                            sprint['board_id'] = board_id
                            sprint['board_name'] = board.get('name', 'Unknown')
                        active_sprints.extend(active)
                except Exception:
                    # Skip boards that fail
                    continue
        
        return active_sprints

    def get_sprints(self, board_id: str) -> List[Dict]:
        """
        Fetch all sprints for a given board.

        Args:
            board_id: ID of the Jira board (Kanban/Scrum)
        """
        url = f"{self.base_url}/rest/agile/1.0/board/{board_id}/sprint"
        try:
            response = self.session.get(url, verify=self.verify_ssl)
            response.raise_for_status()
            data = response.json()
            return data.get("values", [])
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Error fetching sprints for board {board_id}: {str(e)}")

    def get_sprint_issues(self, sprint_id: str, max_results: int = 50) -> List[Dict]:
        """
        Fetch issues belonging to a sprint.

        Args:
            sprint_id: ID of the sprint
            max_results: Maximum number of issues
        """
        url = f"{self.base_url}/rest/agile/1.0/sprint/{sprint_id}/issue"
        params = {"maxResults": max_results}
        try:
            response = self.session.get(url, params=params, verify=self.verify_ssl)
            response.raise_for_status()
            data = response.json()
            return data.get("issues", [])
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Error fetching sprint issues: {str(e)}")

    def summarize_issues(self, issues: List[Dict]) -> str:
        """Create a short human-readable summary of issues."""
        if not issues:
            return "No active Jira issues found."

        summaries = []
        for issue in issues:
            key = issue.get("key", "UNKNOWN")
            fields = issue.get("fields", {})
            summary = fields.get("summary", "No summary")
            status = fields.get("status", {}).get("name", "Unknown")
            project = fields.get("project", {}).get("name", "Unknown")
            summaries.append(f"{key} ({project}) - {summary} [{status}]")

        return " ; ".join(summaries[:10])  # limit for brevity


if __name__ == "__main__":
    # Example usage for manual testing
    try:
        jira = JiraClient(
            base_url=os.getenv("JIRA_URL", "https://yourdomain.atlassian.net"),
            email=os.getenv("JIRA_EMAIL", "you@example.com"),
            api_token=os.getenv("JIRA_API_TOKEN", "your_api_token")
        )

        print("✅ Connected to Jira successfully.")
        issues = jira.get_user_assigned_issues(limit=5)
        print("🔍 Assigned Issues Summary:")
        print(jira.summarize_issues(issues))

    except Exception as e:
        print(f"❌ Error: {e}")