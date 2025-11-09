# Jira Authentication Setup Guide

To use Jira features in this application, you need to set up Jira API credentials.

## Steps to Create a Jira API Token

1. **Go to Atlassian Account Settings**
   - Visit: https://id.atlassian.com/manage-profile/security/api-tokens
   - Or navigate: Atlassian Account → Security → API tokens

2. **Create API Token**
   - Click "Create API token"
   - Give it a label (e.g., "MCP Server Access")
   - Click "Create"
   - **IMPORTANT**: Copy the token immediately - you won't be able to see it again!
   - It will look like: `ATATT3xFfGF0...` (long string)

3. **Get Your Jira URL**
   
   **For Atlassian Cloud (most common):**
   - When you log into Jira, look at your browser's address bar
   - The URL will be in the format: `https://yourcompany.atlassian.net` or `https://yourcompany.atlassian.com`
   - Replace `yourcompany` with your organization's name
   - Example: If your company is "Acme Corp", your URL might be `https://acmecorp.atlassian.net`
   
   **For Self-Hosted Jira:**
   - Your IT team or Jira administrator will provide the URL
   - It's typically something like: `https://jira.yourcompany.com` or `https://jira.internal.company.com`
   - Check with your organization's Jira administrator if unsure
   
   **Quick Check:**
   - Open Jira in your browser
   - Copy the URL from the address bar (the base URL, not a specific page)
   - Remove any path after `.net` or `.com` (e.g., use `https://company.atlassian.net` not `https://company.atlassian.net/browse/PROJ-123`)

4. **Get Your Email**
   - The email address associated with your Jira account

5. **Add Credentials to .env File**
   - Create a `.env` file in the project root (if it doesn't exist)
   - Add the following lines:
     ```
     JIRA_URL=https://yourcompany.atlassian.net
     JIRA_EMAIL=your.email@example.com
     JIRA_API_TOKEN=ATATT3xFfGF0...
     ```
   - Replace with your actual values

## Example .env File

```env
# Jira Configuration
JIRA_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=your.email@example.com
JIRA_API_TOKEN=ATATT3xFfGF0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# GitHub Configuration (optional)
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Google Calendar Configuration (optional)
GOOGLE_CREDENTIALS_PATH=config/credentials.json
GOOGLE_TOKEN_PATH=config/token.json
```

## Security Notes

- **Never commit your `.env` file to version control**
- The `.gitignore` file should already exclude `.env` files
- If you accidentally commit a token, revoke it immediately and generate a new one
- Tokens can be revoked at: https://id.atlassian.com/manage-profile/security/api-tokens

## Verify Setup

After setting up your credentials, restart your application. The Jira features should now work properly!

## Available Jira Tools

Once configured, you can use these Jira endpoints:
- `get_jira_projects()` - Get all accessible Jira projects
- `get_jira_issues(jql, max_results)` - Get issues using JQL query
- `get_jira_issue_details(issue_key)` - Get details for a specific issue
- `get_jira_user_issues(email, limit)` - Get issues assigned to a user
- `get_jira_sprints(board_id)` - Get sprints for a board

