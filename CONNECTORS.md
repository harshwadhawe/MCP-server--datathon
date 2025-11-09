# Connectors Architecture

This document explains the connector architecture for Calendar and GitHub integrations.

## Structure

The codebase now has a clear separation between Calendar and GitHub connectors:

```
src/
├── connectors/
│   ├── __init__.py              # Exports connectors
│   ├── calendar_connector.py    # Calendar connector wrapper
│   └── github_connector.py      # GitHub connector wrapper
├── calendar_client.py           # Google Calendar API client
├── github_client.py             # GitHub API client
└── server.py                    # MCP server (uses both)
```

## Connector Pattern

Connectors provide a clean interface for initializing and accessing service clients:

### Calendar Connector

```python
from src.connectors.calendar_connector import CalendarConnector

connector = CalendarConnector()
calendar_client = connector.client  # Auto-initializes if needed

# Check availability
if connector.is_available():
    events = calendar_client.get_events_from_all_calendars(...)
```

### GitHub Connector

```python
from src.connectors.github_connector import GitHubConnector

connector = GitHubConnector()
github_client = connector.client  # Auto-initializes if needed

# Check availability
if connector.is_available():
    repos = github_client.get_repositories()
```

## Environment Variables

All connectors automatically load environment variables from `.env` file:

- **Calendar**: Uses OAuth credentials from `config/credentials.json` and `config/token.json`
- **GitHub**: Requires `GITHUB_TOKEN` in `.env` file
- **Gemini**: Requires `GEMINI_API_KEY` in `.env` file

## Usage Examples

### Direct Client Usage (Current Server Implementation)

```python
from src.calendar_client import CalendarClient
from src.github_client import GitHubClient

# Direct initialization
calendar_client = CalendarClient()
github_client = GitHubClient()
```

### Connector Usage (Recommended for New Code)

```python
from src.connectors import CalendarConnector, GitHubConnector

# Using connectors
calendar_connector = CalendarConnector()
github_connector = GitHubConnector()

# Access clients
calendar_client = calendar_connector.client
github_client = github_connector.client
```

## Benefits of Connector Pattern

1. **Separation of Concerns**: Clear separation between Calendar and GitHub
2. **Lazy Initialization**: Clients only initialize when needed
3. **Error Handling**: Centralized error handling in connectors
4. **Availability Checking**: Easy to check if a service is available
5. **Consistent Interface**: Same pattern for all service connectors

## Files Updated

- ✅ `src/github_client.py` - Added `load_dotenv()` for .env loading
- ✅ `src/server.py` - Added `load_dotenv()` at top level
- ✅ `src/connectors/` - New connector modules created
- ✅ `interactive_client.py` - Added .env loading
- ✅ `main.py` - Added .env loading
- ✅ `github_test.py` - Updated to use GitHub connector

## Testing

Test files demonstrate connector usage:

- `github_test.py` - Tests GitHub connector and prints all repos, issues, PRs
- Can create `calendar_test.py` following the same pattern

