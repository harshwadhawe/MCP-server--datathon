# Google Calendar MCP Server

A Model Context Protocol (MCP) server that intelligently integrates with Google Calendar to provide context-aware responses for AI models. This server analyzes user queries, fetches relevant calendar data, and formats it as concise context to enhance AI assistant capabilities.

## Overview

The Google Calendar MCP Server acts as a "smart context engine" that:

- **Intercepts** user queries about calendar information
- **Analyzes** queries to understand what calendar context is needed
- **Fetches** relevant data from Google Calendar API
- **Assembles** data into a formatted "context package"
- **Delivers** the context to AI models for hyper-relevant responses

## Features

### Query Analysis Capabilities
- Detects time references (today, tomorrow, next week, specific dates)
- Identifies intent types (availability check, schedule summary, conflict detection)
- Extracts date/time parameters from natural language

### Calendar Data Fetching
- Upcoming events (next N events, events on specific date)
- Event details (title, time, attendees, location, description)
- Availability windows
- Conflict detection
- Meeting summaries

### Context Formatting
- Concise event summaries
- Availability status
- Conflict alerts
- Time-aware formatting

## Data Source

This MCP server connects to the **Google Calendar API** to fetch calendar events and provide personalized context based on the user's schedule.

## Prerequisites

- Python 3.10 or later
- Google Cloud Project with Google Calendar API enabled
- OAuth 2.0 credentials from Google Cloud Console

## Installation

1. **Clone or download this repository**

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up Google Calendar API credentials**:
   
   a. Go to the [Google Cloud Console](https://console.cloud.google.com/)
   
   b. Create a new project or select an existing one
   
   c. Enable the Google Calendar API:
      - Navigate to "APIs & Services" > "Library"
      - Search for "Google Calendar API"
      - Click "Enable"
   
   d. Configure OAuth consent screen:
      - Go to "APIs & Services" > "OAuth consent screen"
      - Choose "External" (unless you have a Google Workspace account)
      - Fill in the required information
      - Add scopes: `https://www.googleapis.com/auth/calendar.readonly`
      - Add your email as a test user
   
   e. Create OAuth 2.0 credentials:
      - Go to "APIs & Services" > "Credentials"
      - Click "Create Credentials" > "OAuth client ID"
      - Choose "Desktop app" as the application type
      - Download the credentials JSON file
   
   f. Place the credentials file:
      - Rename the downloaded file to `credentials.json`
      - Place it in the `config/` directory
      - The file should be at: `config/credentials.json`

5. **Configure environment variables** (optional):
   ```bash
   cp .env.example .env
   # Edit .env if you need to customize paths
   ```

## Usage

### Running the Server

Start the MCP server:

```bash
python main.py
```

Or alternatively:

```bash
python -m src.server
```

On first run, the server will:
1. Open a browser window for Google OAuth authentication
2. Ask you to sign in and grant calendar access
3. Save the authentication token for future use

### MCP Tools

The server provides the following tools:

#### 1. `get_calendar_context`
Main tool that analyzes a query and returns formatted calendar context.

**Example prompts:**
- "Am I free tomorrow at 2 PM?"
- "What meetings do I have this week?"
- "Do I have any conflicts next Monday?"

#### 2. `check_availability`
Check if the user is available at a specific date and time.

**Parameters:**
- `date`: Date to check (YYYY-MM-DD format or natural language like "tomorrow")
- `time`: Time to check (HH:MM format or natural language like "2 PM") - optional
- `duration_hours`: Duration of the time slot in hours (default: 1.0)

**Example:**
```python
check_availability(date="2024-12-15", time="14:00", duration_hours=1.0)
```

#### 3. `get_upcoming_events`
Get upcoming calendar events.

**Parameters:**
- `days`: Number of days to look ahead (default: 7)
- `max_results`: Maximum number of events to return (default: 10)

**Example:**
```python
get_upcoming_events(days=7, max_results=10)
```

#### 4. `detect_conflicts`
Detect scheduling conflicts for a specific date.

**Parameters:**
- `date`: Date to check (YYYY-MM-DD format or natural language like "tomorrow")

**Example:**
```python
detect_conflicts(date="2024-12-15")
```

## Example Use Cases

### Example 1: Availability Check
**Query**: "Am I free tomorrow at 2 PM?"

**Context**: "User's calendar for tomorrow shows: 'Team Meeting' from 1:00-2:30 PM. User is NOT free at 2 PM."

**AI Response**: "No, it looks like you have a 'Team Meeting' scheduled from 1:00 to 2:30 PM tomorrow, so you're not free at 2 PM."

### Example 2: Schedule Summary
**Query**: "What meetings do I have this week?"

**Context**: "Schedule for the next 7 days: Monday, December 9 - 'Project Review' (10:00 AM - 11:00 AM), 'Client Call' (3:00 PM - 4:00 PM); Tuesday, December 10 - 'Standup' (9:00 AM - 9:30 AM)"

**AI Response**: "This week you have: Monday - 'Project Review' at 10 AM and 'Client Call' at 3 PM; Tuesday - 'Standup' at 9 AM."

### Example 3: Conflict Detection
**Query**: "Do I have any conflicts next Monday?"

**Context**: "No conflicts detected for Monday, December 16. You have 2 event(s) scheduled: 'Lunch Meeting' (12:00 PM - 1:00 PM); 'Code Review' (4:00 PM - 5:00 PM)"

**AI Response**: "No conflicts detected for next Monday. You have 2 events: 'Lunch Meeting' at 12 PM and 'Code Review' at 4 PM."

## Project Structure

```
mcp-server/
├── src/
│   ├── __init__.py
│   ├── server.py              # Main MCP server implementation
│   ├── query_analyzer.py      # Query parsing and intent detection
│   ├── calendar_client.py     # Google Calendar API wrapper
│   ├── context_formatter.py   # Data formatting and summarization
│   └── utils.py               # Helper functions
├── config/
│   ├── credentials.json       # Google OAuth credentials (not in repo)
│   └── credentials.json.example # Example credentials file
├── requirements.txt
├── README.md
├── .env.example               # Environment variables template
└── .gitignore
```

## Error Handling

The server includes comprehensive error handling for:

- **API Rate Limiting**: Detects and reports rate limit errors with helpful messages
- **Authentication Failures**: Provides clear guidance on re-authentication
- **Network Timeouts**: Handles connection issues gracefully
- **Invalid Date/Time Parsing**: Falls back to defaults when parsing fails
- **Missing Credentials**: Clear error messages for missing configuration files

## Security Notes

- **Never commit** `credentials.json` or `token.json` to version control
- The `.gitignore` file is configured to exclude sensitive files
- OAuth tokens are stored locally and refreshed automatically
- The server only requests read-only access to your calendar

## Troubleshooting

### Authentication Issues
- Ensure `credentials.json` is in the `config/` directory
- Delete `config/token.json` and re-authenticate if you see authentication errors
- Verify that the OAuth consent screen is properly configured

### API Errors
- Check that Google Calendar API is enabled in your Google Cloud project
- Verify that you've granted the necessary permissions
- Ensure your Google account has an active calendar

### Import Errors
- Make sure all dependencies are installed: `pip install -r requirements.txt`
- Verify you're using Python 3.10 or later
- Check that you're running from the project root directory

## Development

### Running Tests
```bash
# Add your test commands here when tests are implemented
python -m pytest tests/
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

This project is created for the Build-Your-Own-MCP Challenge.

## Acknowledgments

- Built using the [Model Context Protocol](https://modelcontextprotocol.io/)
- Google Calendar API integration
- MCP Python SDK

## Contact

For questions or issues, please open an issue in the repository.

