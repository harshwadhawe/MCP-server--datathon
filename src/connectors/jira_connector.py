"""
Jira Connector - Wrapper for Jira API client.
Provides a clean interface for Jira operations.
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import the Jira client
from ..jira_client import JiraClient


class JiraConnector:
    """
    Connector for Jira operations.
    Handles initialization and provides a clean interface.
    """
    
    def __init__(self):
        """Initialize the Jira connector."""
        self._client: Optional[JiraClient] = None
        self._initialized = False
    
    def initialize(self) -> JiraClient:
        """
        Initialize the Jira client.
        
        Returns:
            JiraClient instance
        
        Raises:
            RuntimeError: If initialization fails
        """
        if self._client is None:
            try:
                base_url = os.getenv("JIRA_URL")
                email = os.getenv("JIRA_EMAIL")
                api_token = os.getenv("JIRA_API_TOKEN")
                
                if not base_url or not email or not api_token:
                    raise ValueError(
                        "Jira credentials not found. Please set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN in your .env file."
                    )
                
                self._client = JiraClient(
                    base_url=base_url,
                    email=email,
                    api_token=api_token
                )
                self._initialized = True
            except Exception as e:
                raise RuntimeError(f"Failed to initialize Jira connector: {e}")
        
        return self._client
    
    @property
    def client(self) -> JiraClient:
        """
        Get the Jira client instance.
        Initializes if not already initialized.
        
        Returns:
            JiraClient instance
        """
        if not self._initialized:
            self.initialize()
        return self._client
    
    def is_available(self) -> bool:
        """
        Check if the Jira connector is available.
        
        Returns:
            True if available, False otherwise
        """
        try:
            if self._client is None:
                self.initialize()
            return self._client is not None
        except Exception:
            return False



