"""
GitHub Connector - Wrapper for GitHub API client.
Provides a clean interface for GitHub operations.
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import the GitHub client
from ..github_client import GitHubClient


class GitHubConnector:
    """
    Connector for GitHub operations.
    Handles initialization and provides a clean interface.
    """
    
    def __init__(self):
        """Initialize the GitHub connector."""
        self._client: Optional[GitHubClient] = None
        self._initialized = False
    
    def initialize(self) -> GitHubClient:
        """
        Initialize the GitHub client.
        
        Returns:
            GitHubClient instance
        
        Raises:
            RuntimeError: If initialization fails
        """
        if self._client is None:
            try:
                self._client = GitHubClient()
                self._initialized = True
            except Exception as e:
                raise RuntimeError(f"Failed to initialize GitHub connector: {e}")
        
        return self._client
    
    @property
    def client(self) -> GitHubClient:
        """
        Get the GitHub client instance.
        Initializes if not already initialized.
        
        Returns:
            GitHubClient instance
        """
        if not self._initialized:
            self.initialize()
        return self._client
    
    def is_available(self) -> bool:
        """
        Check if the GitHub connector is available.
        
        Returns:
            True if available, False otherwise
        """
        try:
            if self._client is None:
                self.initialize()
            return self._client is not None
        except Exception:
            return False

