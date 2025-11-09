"""JIRA API client for fetching boards, issues, sprints, and project information."""

import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class JiraClient:
    """Client for interacting with JIRA API."""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None
    ):
        """
        Initialize the JIRA client.
        
        Args:
            base_url: JIRA base URL (e.g., https://your-domain.atlassian.net)
            email: JIRA email (defaults to JIRA_EMAIL env var)
            api_token: JIRA API token (defaults to JIRA_API_TOKEN env var)
        """
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests package not installed. Install it with: pip install requests"
            )
        
        self.base_url = (base_url or os.getenv("JIRA_BASE_URL", "")).rstrip("/")
        self.email = email or os.getenv("JIRA_EMAIL")
        self.api_token = api_token or os.getenv("JIRA_API_TOKEN")
        
        if not self.base_url:
            raise ValueError(
                "JIRA_BASE_URL not found. Please set it in your .env file or pass it as a parameter."
            )
        if not self.email:
            raise ValueError(
                "JIRA_EMAIL not found. Please set it in your .env file or pass it as a parameter."
            )
        if not self.api_token:
            raise ValueError(
                "JIRA_API_TOKEN not found. Please set it in your .env file or pass it as a parameter."
            )
        
        # Create session with authentication
        self.session = requests.Session()
        self.session.auth = (self.email, self.api_token)
        self.session.headers.update({"Accept": "application/json"})
    
    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict] = None,
        method: str = "GET"
    ) -> Dict:
        """
        Make a request to the JIRA API.
        
        Args:
            endpoint: API endpoint (e.g., "/rest/agile/1.0/board")
            params: Query parameters
            method: HTTP method (GET, POST, etc.)
        
        Returns:
            JSON response as dictionary
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method == "GET":
                response = self.session.get(url, params=params, timeout=30)
            else:
                response = self.session.request(method, url, json=params, timeout=30)
            
            if response.status_code == 401:
                raise RuntimeError(
                    "JIRA authentication failed (401). Check your email/token and permissions."
                )
            if response.status_code == 410:
                # API endpoint has been removed or deprecated
                error_text = response.text
                try:
                    error_json = response.json()
                    if isinstance(error_json, dict):
                        error_messages = error_json.get("errorMessages", [])
                        if error_messages:
                            error_text = "; ".join(error_messages)
                except:
                    pass
                # Don't assume it's about the endpoint - it might be about the query or parameters
                raise RuntimeError(
                    f"JIRA API error (410): {error_text}"
                )
            if response.status_code >= 400:
                error_text = response.text
                try:
                    error_json = response.json()
                    error_messages = []
                    if isinstance(error_json, dict):
                        if "errorMessages" in error_json:
                            error_messages.extend(error_json["errorMessages"])
                        if "errors" in error_json:
                            error_messages.append(str(error_json["errors"]))
                    if error_messages:
                        error_text = "; ".join(error_messages)
                except:
                    pass
                raise RuntimeError(
                    f"JIRA API error {response.status_code}: {error_text}"
                )
            
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"JIRA API request error: {str(e)}")
    
    def get_boards(self, max_results: int = 50) -> List[Dict]:
        """
        Get all JIRA boards.
        
        Args:
            max_results: Maximum number of boards to return
        
        Returns:
            List of board dictionaries
        """
        boards = []
        start_at = 0
        page_size = min(max_results, 50)
        
        while True:
            params = {"startAt": start_at, "maxResults": page_size}
            data = self._make_request("/rest/agile/1.0/board", params)
            
            values = data.get("values", [])
            boards.extend(values)
            
            total = data.get("total", 0)
            is_last = data.get("isLast", False)
            
            if is_last or not values or len(boards) >= max_results:
                break
            
            if total and start_at + len(values) >= total:
                break
            
            start_at += len(values)
        
        return boards[:max_results]
    
    def get_board_issues(
        self,
        board_id: int,
        jql: Optional[str] = None,
        max_results: int = 50
    ) -> List[Dict]:
        """
        Get issues for a specific board.
        
        Args:
            board_id: Board ID
            jql: Optional JQL query to filter issues
            max_results: Maximum number of issues to return
        
        Returns:
            List of issue dictionaries
        """
        endpoint = f"/rest/agile/1.0/board/{board_id}/issue"
        params = {"maxResults": min(max_results, 100)}
        
        if jql:
            params["jql"] = jql
        
        issues = []
        start_at = 0
        
        while True:
            params["startAt"] = start_at
            data = self._make_request(endpoint, params)
            
            issues_data = data.get("issues", [])
            issues.extend(issues_data)
            
            total = data.get("total", 0)
            is_last = data.get("isLast", False)
            
            if is_last or not issues_data or len(issues) >= max_results:
                break
            
            if total and start_at + len(issues_data) >= total:
                break
            
            start_at += len(issues_data)
        
        return issues[:max_results]
    
    def get_board_backlog(
        self,
        board_id: int,
        max_results: int = 50
    ) -> List[Dict]:
        """
        Get backlog items for a specific board.
        Tries the Agile API backlog endpoint first, falls back to JQL if needed.
        
        Args:
            board_id: Board ID
            max_results: Maximum number of backlog items to return
        
        Returns:
            List of issue dictionaries from the backlog
        """
        # Try Agile API backlog endpoint first
        endpoint = f"/rest/agile/1.0/board/{board_id}/backlog"
        issues = []
        start_at = 0
        
        try:
            while True:
                params = {"startAt": start_at, "maxResults": min(max_results, 100)}
                data = self._make_request(endpoint, params)
                
                issues_data = data.get("issues", [])
                issues.extend(issues_data)
                
                total = data.get("total", 0)
                is_last = data.get("isLast", False)
                
                if is_last or not issues_data or len(issues) >= max_results:
                    break
                
                if total and start_at + len(issues_data) >= total:
                    break
                
                start_at += len(issues_data)
            
            return issues[:max_results]
        except RuntimeError as e:
            # If backlog endpoint fails (403/404), try fallback via JQL
            error_msg = str(e)
            if "403" in error_msg or "404" in error_msg or "410" in error_msg:
                # Fallback: Get board filter and use JQL
                try:
                    config = self._make_request(f"/rest/agile/1.0/board/{board_id}/configuration")
                    filter_id = config.get("filter", {}).get("id")
                    
                    if filter_id:
                        # Use JQL to approximate backlog: issues in board filter without sprint or in future sprints
                        jql = f'filter = {filter_id} AND (sprint is EMPTY OR sprint in futureSprints()) ORDER BY created'
                        return self.search_issues(jql, max_results)
                except Exception:
                    pass
            
            # Re-raise if we can't handle it
            raise RuntimeError(f"Could not fetch backlog for board {board_id}: {error_msg}")
    
    def get_sprints(
        self,
        board_id: int,
        state: Optional[str] = None
    ) -> List[Dict]:
        """
        Get sprints for a board.
        
        Args:
            board_id: Board ID
            state: Filter by sprint state (active, closed, future)
        
        Returns:
            List of sprint dictionaries
        """
        endpoint = f"/rest/agile/1.0/board/{board_id}/sprint"
        params = {}
        
        if state:
            params["state"] = state
        
        data = self._make_request(endpoint, params)
        return data.get("values", [])
    
    def get_issue(self, issue_key: str) -> Dict:
        """
        Get details for a specific issue.
        
        Args:
            issue_key: Issue key (e.g., "PROJ-123")
        
        Returns:
            Issue dictionary
        """
        endpoint = f"/rest/api/3/issue/{issue_key}"
        return self._make_request(endpoint)
    
    def search_issues(
        self,
        jql: str,
        max_results: int = 50
    ) -> List[Dict]:
        """
        Search for issues using JQL.
        
        Args:
            jql: JQL query string
            max_results: Maximum number of issues to return
        
        Returns:
            List of issue dictionaries
        """
        # Use the standard search endpoint (not /search/jql which doesn't exist)
        endpoint = "/rest/api/3/search"
        params = {
            "jql": jql,
            "maxResults": min(max_results, 100),
            "fields": "summary,status,assignee,reporter,created,updated,priority,issuetype,project"
        }
        
        issues = []
        start_at = 0
        
        while True:
            params["startAt"] = start_at
            try:
                data = self._make_request(endpoint, params)
            except RuntimeError as e:
                # If we get an error, try different approaches
                error_msg = str(e)
                error_code = None
                if "410" in error_msg:
                    error_code = 410
                elif "400" in error_msg or "403" in error_msg or "404" in error_msg:
                    # Try different field configurations for other errors too
                    error_code = "4xx"
                
                if error_code:
                    # Try with minimal fields first
                    params_minimal = {
                        "jql": jql,
                        "maxResults": min(max_results, 100),
                        "startAt": start_at,
                        "fields": "key,summary,status"
                    }
                    try:
                        data = self._make_request(endpoint, params_minimal)
                    except RuntimeError:
                        # Try with no fields specified (get all default fields)
                        params_no_fields = {
                            "jql": jql,
                            "maxResults": min(max_results, 100),
                            "startAt": start_at
                        }
                        try:
                            data = self._make_request(endpoint, params_no_fields)
                        except RuntimeError as e2:
                            # If all fallbacks fail, provide a clearer error message
                            raise RuntimeError(
                                f"JIRA search failed. JQL query: {jql}. "
                                f"Original error: {error_msg}. "
                                f"Fallback error: {str(e2)}. "
                                f"Please check your JQL syntax and permissions."
                            )
                else:
                    raise
            
            issues_data = data.get("issues", [])
            issues.extend(issues_data)
            
            total = data.get("total", 0)
            
            if not issues_data or len(issues) >= max_results or start_at + len(issues_data) >= total:
                break
            
            start_at += len(issues_data)
        
        return issues[:max_results]
    
    def get_my_issues(
        self,
        status: Optional[str] = None,
        max_results: int = 50
    ) -> List[Dict]:
        """
        Get issues assigned to the current user.
        
        Args:
            status: Filter by status (e.g., "In Progress", "To Do")
            max_results: Maximum number of issues to return
        
        Returns:
            List of issue dictionaries
        """
        # Use currentUser() function for JQL - this is the standard way
        jql = "assignee = currentUser()"
        if status:
            # Escape status name if it contains special characters
            status_escaped = status.replace('"', '\\"')
            jql += f' AND status = "{status_escaped}"'
        
        # Order by updated date (most recent first)
        jql += " ORDER BY updated DESC"
        
        try:
            return self.search_issues(jql, max_results)
        except RuntimeError as e:
            # If currentUser() doesn't work, try getting user info first and use accountId
            error_msg = str(e)
            if "410" in error_msg or "currentUser" in error_msg.lower() or "removed" in error_msg.lower():
                try:
                    user_info = self.get_user_info()
                    # Try accountId first (modern JIRA Cloud), then accountId from key, then name
                    account_id = user_info.get("accountId")
                    if not account_id:
                        # Some JIRA instances might have accountId in a different format
                        account_id = user_info.get("key")  # Fallback to key
                    if account_id:
                        # Try different JQL syntaxes for accountId
                        # First try with quotes
                        jql_variants = [
                            f'assignee = "{account_id}"',
                            f'assignee = {account_id}',  # Without quotes
                            f'assignee.accountId = "{account_id}"',  # Explicit accountId field
                            f'assignee.accountId = {account_id}'
                        ]
                        
                        if status:
                            status_escaped = status.replace('"', '\\"')
                            jql_variants = [jql + f' AND status = "{status_escaped}"' for jql in jql_variants]
                        
                        # Add ORDER BY to all variants
                        jql_variants = [jql + " ORDER BY updated DESC" for jql in jql_variants]
                        
                        # Try each variant until one works
                        last_error = None
                        for jql_variant in jql_variants:
                            try:
                                return self.search_issues(jql_variant, max_results)
                            except RuntimeError as variant_error:
                                last_error = variant_error
                                continue
                        
                        # If all variants fail, try email as last resort
                        if last_error:
                            email = user_info.get("emailAddress")
                            if email:
                                try:
                                    jql_email = f'assignee = "{email}"'
                                    if status:
                                        status_escaped = status.replace('"', '\\"')
                                        jql_email += f' AND status = "{status_escaped}"'
                                    jql_email += " ORDER BY updated DESC"
                                    return self.search_issues(jql_email, max_results)
                                except:
                                    pass
                            
                            # If everything fails, try getting issues from boards instead
                            try:
                                boards = self.get_boards(max_results=5)
                                all_issues = []
                                for board in boards:
                                    try:
                                        board_issues = self.get_board_issues(board.get("id"), max_results=50)
                                        # Filter to only issues assigned to current user
                                        for issue in board_issues:
                                            fields = issue.get("fields", {}) if "fields" in issue else issue
                                            assignee = fields.get("assignee", {}) if isinstance(fields, dict) else {}
                                            if isinstance(assignee, dict):
                                                assignee_id = assignee.get("accountId") or assignee.get("key")
                                                if assignee_id == account_id:
                                                    all_issues.append(issue)
                                    except:
                                        continue
                                
                                if all_issues:
                                    # Sort by updated date
                                    all_issues.sort(key=lambda x: (
                                        x.get("fields", {}).get("updated") or x.get("updated", ""),
                                    ), reverse=True)
                                    return all_issues[:max_results]
                            except:
                                pass
                            
                            # If all fallbacks fail, raise the error
                            raise last_error
                    else:
                        # Last resort: try using email or username
                        email = user_info.get("emailAddress")
                        if email:
                            jql = f'assignee = "{email}"'
                            if status:
                                status_escaped = status.replace('"', '\\"')
                                jql += f' AND status = "{status_escaped}"'
                            jql += " ORDER BY updated DESC"
                            return self.search_issues(jql, max_results)
                except Exception as fallback_error:
                    # If fallback also fails, include both errors in the message
                    raise RuntimeError(
                        f"Failed to get assigned issues. Original error: {error_msg}. Fallback error: {str(fallback_error)}"
                    )
            # Re-raise the original error if we can't work around it
            raise
    
    def get_projects(self) -> List[Dict]:
        """
        Get all projects.
        
        Returns:
            List of project dictionaries
        """
        endpoint = "/rest/api/3/project"
        data = self._make_request(endpoint)
        return data if isinstance(data, list) else []
    
    def get_user_info(self) -> Dict:
        """
        Get information about the authenticated user.
        
        Returns:
            User information dictionary
        """
        endpoint = "/rest/api/3/myself"
        return self._make_request(endpoint)
    
    def get_recent_activity(
        self,
        days: int = 7,
        max_results: int = 50
    ) -> Dict:
        """
        Get recent JIRA activity summary.
        
        Args:
            days: Number of days to look back
            max_results: Maximum number of issues to return
        
        Returns:
            Dictionary with activity summary
        """
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        jql = f"updated >= {cutoff_date} ORDER BY updated DESC"
        
        issues = self.search_issues(jql, max_results)
        
        # Get my assigned issues
        my_issues = self.get_my_issues(max_results=20)
        
        return {
            "recent_issues_count": len(issues),
            "my_assigned_issues_count": len(my_issues),
            "recent_issues": issues[:10],
            "my_assigned_issues": my_issues[:10]
        }

