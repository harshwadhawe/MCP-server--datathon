"""Slack API client for fetching channels, messages, and user activity."""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    SLACK_AVAILABLE = True
except ImportError:
    SLACK_AVAILABLE = False
    WebClient = None
    SlackApiError = None


class SlackClient:
    """
    Client for interacting with the Slack API.
    Handles authentication and provides methods for fetching channels, messages, and user activity.
    """
    
    def __init__(self, token: Optional[str] = None):
        """
        Initialize the Slack client.
        
        Args:
            token: Slack user token (defaults to SLACK_USER_TOKEN from env)
        """
        if not SLACK_AVAILABLE:
            raise RuntimeError(
                "Slack SDK not available. Install it with: pip install slack-sdk"
            )
        
        # Get token from parameter or environment (user token only)
        self.token = token or os.getenv("SLACK_USER_TOKEN")
        
        if not self.token:
            raise ValueError(
                "Slack token not found. Please set SLACK_USER_TOKEN in your .env file."
            )
        
        self.client = WebClient(token=self.token)
        self._user_info = None
    
    def get_user_info(self) -> Dict[str, Any]:
        """
        Get information about the authenticated user.
        
        Returns:
            Dictionary with user information
        """
        if self._user_info is None:
            try:
                response = self.client.auth_test()
                self._user_info = {
                    'user_id': response.get('user_id'),
                    'user': response.get('user'),
                    'team_id': response.get('team_id'),
                    'team': response.get('team'),
                    'bot_id': response.get('bot_id')
                }
            except SlackApiError as e:
                raise RuntimeError(f"Failed to authenticate with Slack: {e.response['error']}")
        
        return self._user_info
    
    def get_channels(self, types: str = "public_channel,private_channel", exclude_archived: bool = True) -> List[Dict]:
        """
        Get list of channels the user has access to.
        
        Args:
            types: Comma-separated list of channel types (public_channel, private_channel, mpim, im)
            exclude_archived: Whether to exclude archived channels
        
        Returns:
            List of channel dictionaries
        """
        try:
            channels = []
            cursor = None
            
            while True:
                params = {
                    "types": types,
                    "exclude_archived": exclude_archived,
                    "limit": 200
                }
                
                if cursor:
                    params["cursor"] = cursor
                
                response = self.client.conversations_list(**params)
                
                if response.get("ok"):
                    channels.extend(response.get("channels", []))
                    
                    # Check if there are more pages
                    cursor = response.get("response_metadata", {}).get("next_cursor")
                    if not cursor:
                        break
                else:
                    break
            
            return channels
        except SlackApiError as e:
            raise RuntimeError(f"Failed to fetch channels: {e.response['error']}")
    
    def get_channel_messages(
        self,
        channel_id: str,
        limit: int = 50,
        oldest: Optional[float] = None,
        latest: Optional[float] = None
    ) -> List[Dict]:
        """
        Get messages from a channel.
        
        Args:
            channel_id: Channel ID
            limit: Maximum number of messages to fetch
            oldest: Unix timestamp of oldest message (optional)
            latest: Unix timestamp of latest message (optional)
        
        Returns:
            List of message dictionaries
        """
        try:
            messages = []
            cursor = None
            
            while len(messages) < limit:
                params = {
                    "channel": channel_id,
                    "limit": min(limit - len(messages), 200)
                }
                
                if oldest:
                    params["oldest"] = str(oldest)
                if latest:
                    params["latest"] = str(latest)
                if cursor:
                    params["cursor"] = cursor
                
                response = self.client.conversations_history(**params)
                
                if response.get("ok"):
                    new_messages = response.get("messages", [])
                    messages.extend(new_messages)
                    
                    # Check if there are more pages
                    cursor = response.get("response_metadata", {}).get("next_cursor")
                    if not cursor or len(new_messages) == 0:
                        break
                else:
                    break
            
            return messages[:limit]
        except SlackApiError as e:
            raise RuntimeError(f"Failed to fetch messages from channel {channel_id}: {e.response['error']}")
    
    def get_unread_channels(self) -> List[Dict]:
        """
        Get channels with unread messages.
        
        Returns:
            List of channels with unread counts
        """
        try:
            # Get all channels
            channels = self.get_channels()
            
            # Get unread counts for each channel
            unread_channels = []
            user_info = self.get_user_info()
            user_id = user_info.get('user_id')
            
            for channel in channels:
                try:
                    # Get unread count
                    response = self.client.conversations_info(channel=channel['id'])
                    if response.get('ok'):
                        channel_info = response['channel']
                        unread_count = channel_info.get('unread_count', 0)
                        
                        if unread_count > 0:
                            channel['unread_count'] = unread_count
                            unread_channels.append(channel)
                except SlackApiError:
                    # Skip channels we can't access
                    continue
            
            return unread_channels
        except SlackApiError as e:
            raise RuntimeError(f"Failed to fetch unread channels: {e.response['error']}")
    
    def get_mentions(
        self,
        days: int = 7,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get messages where the user was mentioned.
        
        Args:
            days: Number of days to look back
            limit: Maximum number of mentions to return
        
        Returns:
            List of messages where user was mentioned
        """
        try:
            user_info = self.get_user_info()
            user_id = user_info.get('user_id')
            
            if not user_id:
                return []
            
            # Calculate time range
            now = datetime.now()
            oldest_timestamp = (now - timedelta(days=days)).timestamp()
            
            # Search for mentions
            mentions = []
            channels = self.get_channels()
            
            for channel in channels[:20]:  # Limit to top 20 channels to avoid rate limits
                try:
                    messages = self.get_channel_messages(
                        channel['id'],
                        limit=100,
                        oldest=oldest_timestamp
                    )
                    
                    # Filter messages that mention the user
                    for message in messages:
                        if user_id in message.get('text', '') or user_id in message.get('user', ''):
                            message['channel_name'] = channel.get('name', 'Unknown')
                            message['channel_id'] = channel['id']
                            mentions.append(message)
                            
                            if len(mentions) >= limit:
                                return mentions[:limit]
                except SlackApiError:
                    # Skip channels we can't access
                    continue
            
            return mentions[:limit]
        except SlackApiError as e:
            raise RuntimeError(f"Failed to fetch mentions: {e.response['error']}")
    
    def search_messages(
        self,
        query: str,
        count: int = 20
    ) -> List[Dict]:
        """
        Search for messages matching a query.
        
        Args:
            query: Search query
            count: Maximum number of results
        
        Returns:
            List of matching messages
        """
        try:
            response = self.client.search_messages(query=query, count=count)
            
            if response.get("ok"):
                matches = response.get("messages", {}).get("matches", [])
                return matches
            else:
                return []
        except SlackApiError as e:
            raise RuntimeError(f"Failed to search messages: {e.response['error']}")
    
    def get_recent_activity(
        self,
        days: int = 7,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Get recent Slack activity summary.
        
        Args:
            days: Number of days to look back
            limit: Maximum number of items per category
        
        Returns:
            Dictionary with activity summary
        """
        try:
            user_info = self.get_user_info()
            
            # Get unread channels
            unread_channels = self.get_unread_channels()
            
            # Get recent mentions
            mentions = self.get_mentions(days=days, limit=limit)
            
            # Get recent messages from active channels
            channels = self.get_channels()
            recent_messages = []
            
            for channel in channels[:10]:  # Top 10 channels
                try:
                    messages = self.get_channel_messages(channel['id'], limit=10)
                    for msg in messages:
                        msg['channel_name'] = channel.get('name', 'Unknown')
                    recent_messages.extend(messages)
                except SlackApiError:
                    continue
            
            return {
                'user': user_info.get('user', 'Unknown'),
                'team': user_info.get('team', 'Unknown'),
                'unread_channels_count': len(unread_channels),
                'unread_channels': unread_channels[:limit],
                'mentions_count': len(mentions),
                'recent_mentions': mentions[:limit],
                'recent_messages': recent_messages[:limit]
            }
        except SlackApiError as e:
            raise RuntimeError(f"Failed to fetch activity: {e.response['error']}")

