"""Google Gemini API client for chatbot functionality."""

import os
from typing import Optional, List, Dict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


class GeminiClient:
    """Client for interacting with Google Gemini API."""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the Gemini client.
        
        Args:
            api_key: Gemini API key (defaults to GEMINI_API_KEY env var)
        """
        if not GEMINI_AVAILABLE:
            raise ImportError(
                "google-generativeai package not installed. "
                "Install it with: pip install google-generativeai"
            )
        
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY not found. Please set it in your .env file or pass it as a parameter."
            )
        
        genai.configure(api_key=self.api_key)
        
        # Try to find an available model
        # Prefer newer 2.5 models, fallback to older versions
        model_names = [
            'gemini-2.5-flash',  # Latest fast model
            'gemini-2.5-pro',    # Latest capable model
            'gemini-1.5-flash',  # Fallback to 1.5 versions
            'gemini-1.5-pro',
            'gemini-pro',        # Legacy fallback
        ]
        
        self.model = None
        last_error = None
        
        for model_name in model_names:
            try:
                # Create model - errors will be caught on first use if model is unavailable
                self.model = genai.GenerativeModel(model_name)
                break
            except Exception as e:
                last_error = e
                continue
        
        if self.model is None:
            # If all predefined models fail, try to list available models
            try:
                models = genai.list_models()
                available_models = [
                    m.name.split('/')[-1]  # Extract model name
                    for m in models 
                    if 'generateContent' in m.supported_generation_methods
                ]
                if available_models:
                    # Use the first available model
                    model_name = available_models[0]
                    self.model = genai.GenerativeModel(model_name)
                else:
                    raise ValueError(
                        "No available Gemini models found. Please check your API key and permissions."
                    )
            except Exception as list_error:
                raise ValueError(
                    f"Could not initialize any Gemini model. "
                    f"Last error: {last_error}. List models error: {list_error}. "
                    f"Please check your API key and available models."
                )
    
    def chat(
        self,
        message: str,
        calendar_context: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """
        Send a chat message to Gemini with optional context (Calendar, GitHub, Slack).
        
        Args:
            message: User's message/query
            calendar_context: Optional context string that may contain Calendar, GitHub, and/or Slack data
            conversation_history: Optional list of previous messages in format [{"role": "user", "content": "..."}, ...]
        
        Returns:
            Gemini's response as a string
        """
        try:
            # Build the prompt with context if provided
            prompt_parts = []
            
            if calendar_context:
                prompt_parts.append(
                    "=== USER DATA (Calendar, GitHub, Slack, JIRA) ===\n"
                    "Below is the user's information from various sources (Calendar, GitHub, Slack, JIRA). "
                    "Please read and parse ALL of this data carefully, then provide a comprehensive answer based on what's available.\n\n"
                    f"{calendar_context}\n\n"
                    "=== END USER DATA ===\n\n"
                )
            
            prompt_parts.append(
                "You are a helpful AI assistant that helps users manage their calendar, GitHub repositories, Slack messages, and JIRA issues. "
                "IMPORTANT INSTRUCTIONS:\n"
                "1. Read and parse ALL the data provided above (Calendar, GitHub, Slack, JIRA, or any combination)\n"
                "2. Answer questions based on the relevant data source:\n"
                "   - For calendar questions: Use calendar data to answer about schedule, events, availability\n"
                "   - For GitHub questions: Use GitHub data to answer about repositories, issues, PRs, commits, deployments\n"
                "   - For Slack questions: Use Slack data to answer about messages, channels, mentions, unread messages\n"
                "   - For JIRA questions: Use JIRA data to answer about boards, issues, tickets, sprints, assigned tasks\n"
                "3. If the user asks about Slack messages/channels/mentions, look for SLACK data in the context above\n"
                "4. If the user asks about GitHub repos/issues/PRs, look for GITHUB data in the context above\n"
                "5. If the user asks about calendar/events/schedule, look for CALENDAR data in the context above\n"
                "6. If the user asks about JIRA issues/boards/tickets, look for JIRA data in the context above\n"
                "7. If no relevant data is found for a question, clearly state that the data is not available\n"
                "8. Be accurate and comprehensive - use ALL available data from the context\n"
                "9. For calendar queries: Group events by date, include titles, times, and locations\n"
                "10. For GitHub queries: Include repository names, issue/PR numbers, commit SHAs, deployment statuses\n"
                "11. For Slack queries: Include channel names, message counts, mention details\n"
                "12. For JIRA queries: Include issue keys, summaries, statuses, priorities, assignees, and board information\n\n"
            )
            
            # Add conversation history if provided
            if conversation_history:
                for msg in conversation_history:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if role == "user":
                        prompt_parts.append(f"User: {content}\n")
                    elif role == "assistant":
                        prompt_parts.append(f"Assistant: {content}\n")
            
            # Add current message
            prompt_parts.append(f"User: {message}\nAssistant:")
            
            full_prompt = "\n".join(prompt_parts)
            
            # Generate response
            response = self.model.generate_content(full_prompt)
            
            return response.text if response.text else "I apologize, but I couldn't generate a response."
        
        except Exception as e:
            error_msg = str(e)
            # Provide more helpful error messages
            if "404" in error_msg or "not found" in error_msg.lower():
                return (
                    f"Error: The Gemini model is not available. "
                    f"This might be due to API version or model availability. "
                    f"Please check your API key and try again. "
                    f"Error details: {error_msg}"
                )
            elif "403" in error_msg or "permission" in error_msg.lower():
                return (
                    f"Error: Permission denied. Please check your API key permissions. "
                    f"Error details: {error_msg}"
                )
            else:
                return f"Error communicating with Gemini API: {error_msg}"

