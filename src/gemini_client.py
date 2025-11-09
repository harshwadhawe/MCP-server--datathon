"""Google Gemini API client for chatbot functionality."""

import os
from datetime import datetime
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
        Send a chat message to Gemini with optional context (calendar, GitHub, Jira).
        
        Args:
            message: User's message/query
            calendar_context: Optional combined context (may include calendar, GitHub, and/or Jira data)
            conversation_history: Optional list of previous messages in format [{"role": "user", "content": "..."}, ...]
        
        Returns:
            Gemini's response as a string
        """
        try:
            # Build the prompt with context if provided
            prompt_parts = []
            
            if calendar_context:
                # Detect what types of data are in the context
                has_calendar = "CALENDAR" in calendar_context.upper() or "EVENT" in calendar_context.upper() or "MEETING" in calendar_context.upper()
                has_github = "GITHUB" in calendar_context.upper() or "REPOSITORY" in calendar_context.upper() or "COMMIT" in calendar_context.upper() or "PULL REQUEST" in calendar_context.upper()
                has_jira = "JIRA" in calendar_context.upper() or "ISSUE" in calendar_context.upper() or "TICKET" in calendar_context.upper() or "SPRINT" in calendar_context.upper()
                
                context_label = "=== CONTEXT DATA ==="
                if has_calendar and not has_github and not has_jira:
                    context_label = "=== CALENDAR DATA ==="
                elif has_github and not has_calendar and not has_jira:
                    context_label = "=== GITHUB DATA ==="
                elif has_jira and not has_calendar and not has_github:
                    context_label = "=== JIRA DATA ==="
                
                instructions = []
                if has_calendar:
                    instructions.append("• Calendar events: Read all calendar information carefully, including dates, times, and event details")
                if has_github:
                    instructions.append("• GitHub data: This includes repositories, commits, pull requests, and issues from GitHub")
                if has_jira:
                    instructions.append("• Jira data: This includes Jira issues, projects, and sprints. Jira status is based on issues created in Jira portal, NOT calendar data")
                
                prompt_parts.append(
                    f"{context_label}\n"
                    "Below is the user's information from various sources. "
                    "Please read and parse ALL of this data carefully.\n\n"
                )
                
                if instructions:
                    prompt_parts.append("IMPORTANT: This context contains:\n" + "\n".join(instructions) + "\n\n")
                
                prompt_parts.append(f"{calendar_context}\n\n")
                prompt_parts.append(f"=== END CONTEXT DATA ===\n\n")
            
            # Build assistant instructions based on what data is available
            assistant_role = "You are a helpful AI assistant that helps users manage their projects and schedule."
            instructions = []
            
            # Always add current date awareness
            current_date = datetime.now()
            instructions.append(f"0. CURRENT DATE AND TIME: Today is {current_date.strftime('%A, %B %d, %Y')} at {current_date.strftime('%I:%M %p')}. Use this for all date calculations, including days remaining, time until deadlines, etc.")
            
            if calendar_context:
                if "CALENDAR" in calendar_context.upper() or "EVENT" in calendar_context.upper():
                    instructions.extend([
                        "1. For calendar queries: Read and parse ALL calendar data provided",
                        "2. Group events by date when presenting information",
                        "3. Include event titles, times, and locations if available",
                        "4. Use exact dates and times from the calendar data"
                    ])
                if "GITHUB" in calendar_context.upper() or "REPOSITORY" in calendar_context.upper():
                    instructions.extend([
                        "5. For GitHub queries: Use repository data, commits, pull requests, and issues from GitHub",
                        "6. GitHub commits may reference Jira issues (look for issue keys like PROJ-123 in commit messages)"
                    ])
                if "JIRA" in calendar_context.upper() or "ISSUE" in calendar_context.upper() or "SPRINT" in calendar_context.upper():
                    instructions.extend([
                        "7. For Jira queries: Use Jira issue data from the Jira portal - this is the source of truth for Jira status",
                        "8. Jira issues are created and managed in Jira, NOT in calendar events",
                        "9. You can correlate GitHub commits with Jira issues if commit messages mention issue keys (e.g., 'PROJ-123')",
                        "10. DO NOT confuse calendar data with Jira data - they are separate sources",
                        "11. For sprint queries: Calculate days remaining using the CURRENT DATE provided above and the sprint end date",
                        "12. Always provide specific calculations (e.g., 'X days remaining', 'ends in Y days') when asked about time remaining"
                    ])
            
            if not instructions:
                instructions = [
                    "1. Read and parse ALL the data provided above",
                    "2. Be accurate and comprehensive",
                    "3. If no data is found, clearly state that",
                    f"4. Use the current date ({current_date.strftime('%A, %B %d, %Y')}) for all date calculations"
                ]
            
            prompt_parts.append(
                f"{assistant_role}\n"
                "IMPORTANT INSTRUCTIONS:\n" + "\n".join(instructions) + "\n\n"
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
            
            # Configure safety settings to be less restrictive for data queries
            # Note: BLOCK_NONE requires Google approval, so we use BLOCK_ONLY_HIGH
            # This helps avoid false positives when querying technical data like Jira issues
            try:
                from google.generativeai.types import HarmCategory, HarmBlockThreshold
                
                safety_settings = {
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                }
                
                # Generate response with relaxed safety settings
                generation_config = {
                    "temperature": 0.7,
                    "top_p": 0.95,
                    "top_k": 40,
                }
                
                response = self.model.generate_content(
                    full_prompt,
                    safety_settings=safety_settings,
                    generation_config=generation_config
                )
            except (ImportError, AttributeError, Exception) as safety_error:
                # If safety settings fail (e.g., enum not available or requires approval),
                # try with string-based format or without safety settings
                try:
                    # Try string-based format
                    safety_settings = [
                        {
                            "category": "HARM_CATEGORY_HARASSMENT",
                            "threshold": "BLOCK_ONLY_HIGH"
                        },
                        {
                            "category": "HARM_CATEGORY_HATE_SPEECH",
                            "threshold": "BLOCK_ONLY_HIGH"
                        },
                        {
                            "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                            "threshold": "BLOCK_ONLY_HIGH"
                        },
                        {
                            "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                            "threshold": "BLOCK_ONLY_HIGH"
                        }
                    ]
                    response = self.model.generate_content(
                        full_prompt,
                        safety_settings=safety_settings
                    )
                except Exception:
                    # Final fallback: generate without safety settings
                    response = self.model.generate_content(full_prompt)
            
            # Check if response was blocked or filtered
            if response.candidates:
                candidate = response.candidates[0]
                finish_reason = candidate.finish_reason
                
                # Handle blocked/filtered responses
                if finish_reason and finish_reason != 1:  # 1 = STOP (normal completion)
                    finish_reason_map = {
                        2: "MAX_TOKENS - Response was cut off due to token limit",
                        3: "SAFETY - Response was blocked by safety filters",
                        4: "RECITATION - Response was blocked due to recitation",
                        5: "OTHER - Response was blocked for other reasons",
                        12: "SAFETY - Response was blocked by safety filters (content policy violation)"
                    }
                    reason_text = finish_reason_map.get(finish_reason, f"Unknown reason ({finish_reason})")
                    
                    # Try to get safety ratings for more details
                    safety_ratings = []
                    if hasattr(candidate, 'safety_ratings') and candidate.safety_ratings:
                        for rating in candidate.safety_ratings:
                            if rating.probability > 1:  # 1 = NEGLIGIBLE, higher means more likely blocked
                                safety_ratings.append(f"{rating.category}: {rating.probability}")
                    
                    error_msg = f"Response was blocked: {reason_text}"
                    if safety_ratings:
                        error_msg += f"\nSafety ratings: {', '.join(safety_ratings)}"
                    
                    # If we have Jira data, try to return it directly instead of going through Gemini
                    if "JIRA" in str(calendar_context).upper() or "SPRINT" in str(calendar_context).upper():
                        # Format Jira data nicely
                        formatted_jira_data = self._format_jira_data_for_display(calendar_context)
                        return (
                            f"📊 **Jira Sprint Information**\n\n"
                            f"{formatted_jira_data}\n\n"
                            f"*Note: The AI response was blocked by safety filters, but here's your Jira data.*"
                        )
                    
                    return (
                        f"I apologize, but the AI response was blocked by safety filters. "
                        f"This might be due to the content or length of the data. "
                        f"Error details: {error_msg}"
                    )
            
            # Try to get response text
            try:
                if hasattr(response, 'text') and response.text:
                    return response.text
                elif response.candidates and response.candidates[0].content:
                    # Try to get content from parts
                    parts = response.candidates[0].content.parts
                    if parts:
                        return "".join(part.text for part in parts if hasattr(part, 'text'))
            except Exception as text_error:
                # If we can't get text, try to provide context data directly
                if calendar_context:
                    return (
                        f"I apologize, but I couldn't generate a formatted response. "
                        f"Here's the raw data I found:\n\n{calendar_context}\n\n"
                        f"Error accessing response: {str(text_error)}"
                    )
                return f"I apologize, but I couldn't generate a response. Error: {str(text_error)}"
            
            return "I apologize, but I couldn't generate a response."
        
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
            elif "finish_reason" in error_msg or "12" in error_msg or "Part" in error_msg:
                # Handle blocked response errors
                if "JIRA" in str(calendar_context).upper() if calendar_context else False:
                    formatted_jira_data = self._format_jira_data_for_display(calendar_context)
                    return (
                        f"📊 **Jira Information**\n\n"
                        f"{formatted_jira_data}\n\n"
                        f"*Note: The AI response was blocked by safety filters, but here's your Jira data.*"
                    )
                return (
                    f"Error: The AI response was blocked by safety filters. "
                    f"This might be due to content length or safety policies. "
                    f"Error details: {error_msg}"
                )
            else:
                return f"Error communicating with Gemini API: {error_msg}"
    
    def _format_jira_data_for_display(self, context: str) -> str:
        """
        Extract and format Jira data from context for better display.
        
        Args:
            context: Raw context string containing Jira data
            
        Returns:
            Formatted Jira data string
        """
        if not context:
            return "No Jira data available."
        
        import re
        from datetime import datetime
        
        lines = context.split('\n')
        formatted_parts = []
        in_sprint_section = False
        in_issue_section = False
        in_project_section = False
        skip_next_separator = False
        
        for i, line in enumerate(lines):
            line_upper = line.upper()
            line_stripped = line.strip()
            
            # Detect sections
            if "ACTIVE JIRA SPRINTS" in line_upper:
                in_sprint_section = True
                in_issue_section = False
                in_project_section = False
                # Extract count from line like "ACTIVE JIRA SPRINTS (1 total):"
                count_match = re.search(r'\((\d+)\s+total\)', line_upper)
                count = count_match.group(1) if count_match else ""
                formatted_parts.append(f"\n## 🚀 Active Jira Sprints ({count} total)\n\n")
                skip_next_separator = True
                continue
            elif "ASSIGNED JIRA ISSUES" in line_upper or "COMPLETED JIRA ISSUES" in line_upper:
                in_sprint_section = False
                in_issue_section = True
                in_project_section = False
                count_match = re.search(r'\((\d+)\s+total\)', line_upper)
                count = count_match.group(1) if count_match else ""
                formatted_parts.append(f"\n## 🎫 {line_stripped}\n\n")
                skip_next_separator = True
                continue
            elif "JIRA PROJECTS" in line_upper:
                in_sprint_section = False
                in_issue_section = False
                in_project_section = True
                count_match = re.search(r'\((\d+)\s+total\)', line_upper)
                count = count_match.group(1) if count_match else ""
                formatted_parts.append(f"\n## 📋 {line_stripped}\n\n")
                skip_next_separator = True
                continue
            elif line_stripped.startswith("---") or (line_stripped == "" and skip_next_separator):
                # Skip separator lines
                if skip_next_separator:
                    skip_next_separator = False
                continue
            elif "JIRA USER INFORMATION" in line_upper or "GITHUB USER" in line_upper:
                # Skip user info section for cleaner output
                in_sprint_section = False
                in_issue_section = False
                in_project_section = False
                continue
            elif line_stripped.startswith("(") and "account associated" in line.lower():
                # Skip metadata lines
                continue
            
            # Format sprint data
            if in_sprint_section:
                # Check if this is a sprint name line (has "ID:" or starts with number and "Sprint")
                if line_stripped and ("ID:" in line_stripped or (re.match(r'^\d+\.', line_stripped) and "Sprint" in line_stripped)):
                    # Extract sprint name and ID
                    if "(" in line_stripped and "ID:" in line_stripped:
                        # Remove leading number if present (e.g., "1. ")
                        sprint_line = re.sub(r'^\d+\.\s*', '', line_stripped)
                        parts = sprint_line.split("(")
                        sprint_name = parts[0].strip()
                        sprint_id = parts[1].replace("ID:", "").replace(")", "").strip()
                        formatted_parts.append(f"### {sprint_name}\n")
                        formatted_parts.append(f"  **Sprint ID:** {sprint_id}\n")
                    else:
                        sprint_name = re.sub(r'^\d+\.\s*', '', line_stripped)
                        formatted_parts.append(f"### {sprint_name}\n")
                # Sprint details - check original line for leading spaces
                elif line.startswith("     ") and ("State:" in line_stripped or "Period:" in line_stripped):
                    detail_line = line_stripped
                    if "State:" in detail_line:
                        # Format state line
                        formatted_parts.append(f"  {detail_line}\n")
                    elif "Period:" in detail_line:
                        # Format date range
                        if "T" in detail_line:
                            try:
                                # Extract dates - handle both with and without milliseconds
                                date_pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z)'
                                dates = re.findall(date_pattern, detail_line)
                                if len(dates) >= 2:
                                    start_date = datetime.fromisoformat(dates[0].replace('Z', '+00:00'))
                                    end_date = datetime.fromisoformat(dates[1].replace('Z', '+00:00'))
                                    formatted_start = start_date.strftime('%B %d, %Y')
                                    formatted_end = end_date.strftime('%B %d, %Y')
                                    formatted_parts.append(f"  **Period:** {formatted_start} to {formatted_end}\n")
                                else:
                                    formatted_parts.append(f"  {detail_line}\n")
                            except Exception as e:
                                formatted_parts.append(f"  {detail_line}\n")
                        else:
                            formatted_parts.append(f"  {detail_line}\n")
                elif line_stripped == "" and i < len(lines) - 1:
                    # Only add blank line if there's more content
                    if i + 1 < len(lines) and lines[i + 1].strip():
                        formatted_parts.append("\n")
            
            # Format issue data
            elif in_issue_section:
                if line.strip().startswith("  ") and not line.strip().startswith("     "):
                    # Issue key line
                    formatted_parts.append(f"**{line.strip()}**\n")
                elif line.strip().startswith("     "):
                    # Issue details
                    formatted_parts.append(f"  {line.strip()}\n")
                elif line.strip() == "":
                    formatted_parts.append("\n")
            
            # Format project data
            elif in_project_section:
                if line.strip().startswith("  "):
                    formatted_parts.append(f"  {line.strip()}\n")
                elif line.strip() == "":
                    formatted_parts.append("\n")
        
        # If no formatted parts were created, try a simpler extraction
        if not formatted_parts or (in_sprint_section and len([p for p in formatted_parts if "###" in p]) == 0):
            # Fallback: Extract sprint data more simply
            key_info = []
            found_sprint_header = False
            
            for line in lines:
                line_upper = line.upper()
                line_stripped = line.strip()
                
                if "ACTIVE JIRA SPRINTS" in line_upper:
                    found_sprint_header = True
                    count_match = re.search(r'\((\d+)\s+total\)', line_upper)
                    count = count_match.group(1) if count_match else ""
                    key_info.append(f"\n## 🚀 Active Jira Sprints ({count} total)\n\n")
                elif found_sprint_header and line_stripped:
                    # Capture all sprint-related lines
                    if line_stripped.startswith("(") and "account associated" in line_stripped.lower():
                        continue
                    elif "JIRA USER" in line_upper or "GITHUB USER" in line_upper:
                        continue
                    elif line_stripped.startswith("---"):
                        continue
                    elif "ASSIGNED" in line_upper or "COMPLETED" in line_upper or "PROJECTS" in line_upper:
                        # End of sprint section
                        break
                    else:
                        # Format the line
                        if "ID:" in line_stripped and "Sprint" in line_stripped:
                            # Sprint name line
                            sprint_line = re.sub(r'^\d+\.\s*', '', line_stripped)
                            if "(" in sprint_line and "ID:" in sprint_line:
                                parts = sprint_line.split("(")
                                sprint_name = parts[0].strip()
                                sprint_id = parts[1].replace("ID:", "").replace(")", "").strip()
                                key_info.append(f"### {sprint_name}\n")
                                key_info.append(f"  **Sprint ID:** {sprint_id}\n")
                            else:
                                key_info.append(f"### {sprint_line}\n")
                        elif "State:" in line_stripped or "Period:" in line_stripped:
                            # Sprint details
                            if "Period:" in line_stripped and "T" in line_stripped:
                                try:
                                    date_pattern = r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z)'
                                    dates = re.findall(date_pattern, line_stripped)
                                    if len(dates) >= 2:
                                        start_date = datetime.fromisoformat(dates[0].replace('Z', '+00:00'))
                                        end_date = datetime.fromisoformat(dates[1].replace('Z', '+00:00'))
                                        formatted_start = start_date.strftime('%B %d, %Y')
                                        formatted_end = end_date.strftime('%B %d, %Y')
                                        key_info.append(f"  **Period:** {formatted_start} to {formatted_end}\n")
                                    else:
                                        key_info.append(f"  {line_stripped}\n")
                                except:
                                    key_info.append(f"  {line_stripped}\n")
                            else:
                                key_info.append(f"  {line_stripped}\n")
            
            if key_info:
                return "".join(key_info)
        
        # If we have formatted parts, return them
        if formatted_parts:
            return "".join(formatted_parts)
        
        # Final fallback: Return a cleaned version of the context
        cleaned = "\n".join([l for l in lines if l.strip() and not l.strip().startswith("(") and "account associated" not in l.lower() and "JIRA USER" not in l.upper() and "GITHUB USER" not in l.upper()])
        return cleaned if cleaned else "No Jira data available."

