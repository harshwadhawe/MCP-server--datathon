"""
Slack Connector - Wrapper for Slack API client.
Provides a clean interface for Slack operations.
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import the Slack client
from ..slack_client import SlackClient


class SlackConnector:
    """
    Connector for Slack operations.
    Handles initialization and provides a clean interface.
    """
    
    def __init__(self):
        """Initialize the Slack connector."""
        self._client: Optional[SlackClient] = None
        self._initialized = False
    
    def initialize(self) -> SlackClient:
        """
        Initialize the Slack client.
        
        Returns:
            SlackClient instance
        
        Raises:
            RuntimeError: If initialization fails
        """
        if self._client is None:
            try:
                self._client = SlackClient()
                self._initialized = True
            except Exception as e:
                raise RuntimeError(f"Failed to initialize Slack connector: {e}")
        
        return self._client
    
    @property
    def client(self) -> SlackClient:
        """
        Get the Slack client instance.
        Initializes if not already initialized.
        
        Returns:
            SlackClient instance
        """
        if not self._initialized:
            self.initialize()
        return self._client
    
    def is_available(self) -> bool:
        """
        Check if the Slack connector is available.
        
        Returns:
            True if available, False otherwise
        """
        try:
            if self._client is None:
                self.initialize()
            return self._client is not None
        except Exception:
            return False

