"""GitHub API client for fetching repository information, issues, PRs, and commits."""

import os
import sys
import base64
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from urllib.parse import quote
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class GitHubClient:
    """Client for interacting with GitHub API."""
    
    def __init__(self, token: Optional[str] = None):
        """
        Initialize the GitHub client.
        
        Args:
            token: GitHub personal access token (defaults to GITHUB_TOKEN env var)
        """
        if not REQUESTS_AVAILABLE:
            raise ImportError(
                "requests package not installed. Install it with: pip install requests"
            )
        
        self.token = token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise ValueError(
                "GITHUB_TOKEN not found. Please set it in your .env file or pass it as a parameter."
            )
        
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "MCP-Server"
        }
    
    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a request to the GitHub API."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"GitHub API error: {str(e)}")
    
    def get_user_info(self) -> Dict:
        """Get authenticated user information."""
        return self._make_request("/user")
    
    def get_repositories(self, username: Optional[str] = None, per_page: int = 30) -> List[Dict]:
        """
        Get repositories for a user.
        
        Args:
            username: GitHub username (defaults to authenticated user)
            per_page: Number of repositories per page (max 100)
        
        Returns:
            List of repository dictionaries
        """
        if username:
            endpoint = f"/users/{username}/repos"
        else:
            endpoint = "/user/repos"
        
        repos = []
        page = 1
        
        while True:
            params = {"per_page": min(per_page, 100), "page": page, "sort": "updated"}
            data = self._make_request(endpoint, params)
            
            if not data:
                break
            
            repos.extend(data)
            
            if len(data) < per_page:
                break
            
            page += 1
            if len(repos) >= per_page:
                break
        
        return repos[:per_page]
    
    def get_repository(self, owner: str, repo: str) -> Dict:
        """Get information about a specific repository."""
        return self._make_request(f"/repos/{owner}/{repo}")
    
    def get_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        labels: Optional[List[str]] = None,
        assignee: Optional[str] = None,
        per_page: int = 30
    ) -> List[Dict]:
        """
        Get issues for a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            state: Issue state (open, closed, all)
            labels: List of label names to filter by
            assignee: Filter by assignee (username or "none" or "*")
            per_page: Number of issues per page
        
        Returns:
            List of issue dictionaries
        """
        endpoint = f"/repos/{owner}/{repo}/issues"
        params = {
            "state": state,
            "per_page": min(per_page, 100),
            "sort": "updated"
        }
        
        if labels:
            params["labels"] = ",".join(labels)
        if assignee:
            params["assignee"] = assignee
        
        issues = []
        page = 1
        
        while True:
            params["page"] = page
            data = self._make_request(endpoint, params)
            
            if not data:
                break
            
            issues.extend(data)
            
            if len(data) < per_page:
                break
            
            page += 1
            if len(issues) >= per_page:
                break
        
        return issues[:per_page]
    
    def get_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        per_page: int = 30
    ) -> List[Dict]:
        """
        Get pull requests for a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            state: PR state (open, closed, all)
            per_page: Number of PRs per page
        
        Returns:
            List of pull request dictionaries
        """
        endpoint = f"/repos/{owner}/{repo}/pulls"
        params = {
            "state": state,
            "per_page": min(per_page, 100),
            "sort": "updated"
        }
        
        prs = []
        page = 1
        
        while True:
            params["page"] = page
            data = self._make_request(endpoint, params)
            
            if not data:
                break
            
            prs.extend(data)
            
            if len(data) < per_page:
                break
            
            page += 1
            if len(prs) >= per_page:
                break
        
        return prs[:per_page]
    
    def get_commits(
        self,
        owner: str,
        repo: str,
        branch: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        per_page: int = 30
    ) -> List[Dict]:
        """
        Get commits for a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            branch: Branch name (defaults to default branch)
            since: Only show commits after this date
            until: Only show commits before this date
            per_page: Number of commits per page
        
        Returns:
            List of commit dictionaries
        """
        endpoint = f"/repos/{owner}/{repo}/commits"
        params = {
            "per_page": min(per_page, 100)
        }
        
        if branch:
            params["sha"] = branch
        if since:
            params["since"] = since.isoformat()
        if until:
            params["until"] = until.isoformat()
        
        commits = []
        page = 1
        
        while True:
            params["page"] = page
            data = self._make_request(endpoint, params)
            
            if not data:
                break
            
            commits.extend(data)
            
            if len(data) < per_page:
                break
            
            page += 1
            if len(commits) >= per_page:
                break
        
        return commits[:per_page]
    
    def search_repositories(self, query: str, per_page: int = 30) -> List[Dict]:
        """
        Search for repositories.
        
        Args:
            query: Search query (e.g., "language:python stars:>100")
            per_page: Number of results per page
        
        Returns:
            List of repository dictionaries
        """
        endpoint = "/search/repositories"
        params = {
            "q": query,
            "per_page": min(per_page, 100),
            "sort": "updated"
        }
        
        data = self._make_request(endpoint, params)
        return data.get("items", [])[:per_page]
    
    def get_user_activity(
        self,
        username: Optional[str] = None,
        days: int = 7
    ) -> Dict:
        """
        Get user activity summary (recent repos, issues, PRs).
        
        Args:
            username: GitHub username (defaults to authenticated user)
            days: Number of days to look back
        
        Returns:
            Dictionary with activity summary
        """
        if not username:
            user_info = self.get_user_info()
            username = user_info.get("login")
        
        since = datetime.now() - timedelta(days=days)
        
        # Get recent repositories
        repos = self.get_repositories(username, per_page=10)
        recent_repos = []
        for r in repos:
            updated_at = r.get("updated_at")
            if updated_at:
                try:
                    # Parse ISO format datetime
                    dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    if dt.replace(tzinfo=None) > since:
                        recent_repos.append(r)
                except (ValueError, AttributeError):
                    # Skip repos with invalid date formats
                    continue
        
        activity = {
            "username": username,
            "recent_repositories": recent_repos[:5],
            "total_repositories": len(repos)
        }
        
        return activity
    
    def get_deployments(
        self,
        owner: str,
        repo: str,
        environment: Optional[str] = None,
        per_page: int = 30
    ) -> List[Dict]:
        """
        Get deployments for a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            environment: Filter by environment (e.g., 'production', 'staging')
            per_page: Number of deployments per page
        
        Returns:
            List of deployment dictionaries
        """
        endpoint = f"/repos/{owner}/{repo}/deployments"
        params = {
            "per_page": min(per_page, 100)
        }
        
        if environment:
            params["environment"] = environment
        
        deployments = []
        page = 1
        
        while True:
            params["page"] = page
            try:
                data = self._make_request(endpoint, params)
            except RuntimeError as e:
                # Deployments API might not be available for all repos
                if "404" in str(e) or "Not Found" in str(e):
                    return []
                raise
            
            if not data:
                break
            
            # GitHub deployments API returns a list
            if isinstance(data, list):
                deployments.extend(data)
            else:
                # If it's not a list, something unexpected happened
                break
            
            if len(data) < per_page:
                break
            
            page += 1
            if len(deployments) >= per_page:
                break
        
        return deployments[:per_page]
    
    def get_deployment_statuses(
        self,
        owner: str,
        repo: str,
        deployment_id: int
    ) -> List[Dict]:
        """
        Get statuses for a specific deployment.
        
        Args:
            owner: Repository owner
            repo: Repository name
            deployment_id: Deployment ID
        
        Returns:
            List of deployment status dictionaries
        """
        endpoint = f"/repos/{owner}/{repo}/deployments/{deployment_id}/statuses"
        
        try:
            data = self._make_request(endpoint, {"per_page": 100})
            return data if isinstance(data, list) else []
        except RuntimeError as e:
            if "404" in str(e) or "Not Found" in str(e):
                return []
            raise
    
    def get_all_deployments(
        self,
        username: Optional[str] = None,
        per_repo: int = 10
    ) -> Dict[str, List[Dict]]:
        """
        Get deployments across all user repositories.
        
        Args:
            username: GitHub username (defaults to authenticated user)
            per_repo: Maximum deployments to fetch per repository
        
        Returns:
            Dictionary mapping repo names to their deployments
        """
        if not username:
            user_info = self.get_user_info()
            username = user_info.get("login")
        
        repos = self.get_repositories(username, per_page=30)
        all_deployments = {}
        
        for repo in repos:
            owner = repo.get('owner', {}).get('login', username)
            repo_name = repo.get('name', '')
            full_name = repo.get('full_name', '')
            
            try:
                deployments = self.get_deployments(owner, repo_name, per_page=per_repo)
                if deployments:
                    # Enrich deployments with status information
                    enriched_deployments = []
                    for deployment in deployments:
                        deployment_id = deployment.get('id')
                        if deployment_id:
                            statuses = self.get_deployment_statuses(owner, repo_name, deployment_id)
                            deployment['statuses'] = statuses
                            # Get the latest status
                            if statuses:
                                deployment['latest_status'] = statuses[0]
                        enriched_deployments.append(deployment)
                    
                    all_deployments[full_name] = enriched_deployments
            except Exception:
                # Skip repos that don't have deployments or have errors
                continue
        
        return all_deployments
    
    def get_readme(self, owner: str, repo: str) -> Optional[str]:
        """
        Get README.md content from a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
        
        Returns:
            README content as string, or None if not found
        """
        endpoint = f"/repos/{owner}/{repo}/readme"
        
        try:
            data = self._make_request(endpoint)
            
            # GitHub API returns file content as base64 encoded string
            if data.get('content'):
                # Decode base64 content
                content = base64.b64decode(data['content']).decode('utf-8')
                return content
            return None
        except RuntimeError as e:
            # README might not exist or might not be accessible
            if "404" in str(e) or "Not Found" in str(e):
                return None
            raise

