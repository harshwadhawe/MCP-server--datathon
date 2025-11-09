"""
Calendar Connector - Wrapper for Google Calendar API client.
Provides a clean interface for calendar operations.
"""

import os
import sys
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import the calendar client
from ..calendar_client import CalendarClient


class CalendarConnector:
    """
    Connector for Google Calendar operations.
    Handles initialization and provides a clean interface.
    """
    
    def __init__(self):
        """Initialize the Calendar connector."""
        self._client: Optional[CalendarClient] = None
        self._initialized = False
    
    def initialize(self) -> CalendarClient:
        """
        Initialize the calendar client.
        
        Returns:
            CalendarClient instance
        
        Raises:
            RuntimeError: If initialization fails
        """
        if self._client is None:
            try:
                credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "config/credentials.json")
                token_path = os.getenv("GOOGLE_TOKEN_PATH", "config/token.json")
                
                # Suppress stdout during initialization to avoid breaking JSON-RPC
                original_stdout = sys.stdout
                try:
                    sys.stdout = sys.stderr
                    self._client = CalendarClient(credentials_path, token_path)
                finally:
                    sys.stdout = original_stdout
                
                self._initialized = True
            except Exception as e:
                raise RuntimeError(f"Failed to initialize Calendar connector: {e}")
        
        return self._client
    
    @property
    def client(self) -> CalendarClient:
        """
        Get the calendar client instance.
        Initializes if not already initialized.
        
        Returns:
            CalendarClient instance
        """
        if not self._initialized:
            self.initialize()
        return self._client
    
    def is_available(self) -> bool:
        """
        Check if the calendar connector is available.
        
        Returns:
            True if available, False otherwise
        """
        try:
            if self._client is None:
                self.initialize()
            return self._client is not None
        except Exception:
            return False

