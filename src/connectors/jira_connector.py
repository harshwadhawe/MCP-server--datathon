"""
JIRA Connector - Wrapper for JIRA API client.
Provides a clean interface for JIRA operations.
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import the JIRA client
from ..jira_client import JiraClient


class JiraConnector:
    """
    Connector for JIRA operations.
    Handles initialization and provides a clean interface.
    """
    
    def __init__(self):
        """Initialize the JIRA connector."""
        self._client: Optional[JiraClient] = None
        self._initialized = False
    
    def initialize(self) -> JiraClient:
        """
        Initialize the JIRA client.
        
        Returns:
            JiraClient instance
        
        Raises:
            RuntimeError: If initialization fails
        """
        if self._client is None:
            try:
                self._client = JiraClient()
                self._initialized = True
            except Exception as e:
                raise RuntimeError(f"Failed to initialize JIRA connector: {e}")
        
        return self._client
    
    @property
    def client(self) -> JiraClient:
        """
        Get the JIRA client instance.
        Initializes if not already initialized.
        
        Returns:
            JiraClient instance
        """
        if not self._initialized:
            self.initialize()
        return self._client
    
    def is_available(self) -> bool:
        """
        Check if the JIRA connector is available.
        
        Returns:
            True if available, False otherwise
        """
        try:
            if self._client is None:
                self.initialize()
            return self._client is not None
        except Exception:
            return False

