# How Jira Authentication Works - "Who Am I?"

## Quick Answer

**Yes, "who you are" is determined by your API token!**

When you provide a Jira API token, it's tied to a specific Jira account. Jira uses this token to identify which account you are when making API calls.

## How It Works

### 1. **API Token = Your Identity**

- Your `JIRA_API_TOKEN` is generated from your Jira account
- Each token is uniquely tied to the account that created it
- When you authenticate with the token, Jira knows exactly which account you are

### 2. **Authentication Process**

When the system connects to Jira:

1. **Basic Authentication**: Uses your email + API token
   ```python
   session.auth = (email, api_token)
   ```

2. **Jira Identifies You**: Calls `/rest/api/3/myself` endpoint
   - This returns your account information
   - Email, display name, account ID, etc.

3. **Querying "Your" Issues**: Uses one of these methods:
   - `currentUser()` in JQL (recommended) - Jira automatically uses the authenticated user
   - Falls back to your email if `currentUser()` doesn't work

### 3. **Example Flow**

```
Your .env file:
  JIRA_EMAIL=john.doe@company.com
  JIRA_API_TOKEN=ATATT3xFfGF0...

System connects:
  1. Authenticates with email + token
  2. Jira says: "This token belongs to John Doe (john.doe@company.com)"
  3. System queries: "assignee = currentUser()" 
  4. Jira returns: Issues assigned to John Doe
```

## How to Check "Who You Are"

You can use the `get_jira_current_user` tool to see exactly which account is authenticated:

```python
# In your code or via MCP
get_jira_current_user()
```

This will show:
- Your display name
- Your email address
- Your account ID
- How the system determines "you"

## Important Notes

### Email vs Token

- **`JIRA_EMAIL`**: Should match the email of the account that created the token
- **`JIRA_API_TOKEN`**: The actual identifier - this is what Jira uses to know "who you are"
- If they don't match, authentication might fail

### Multiple Accounts

If you have multiple Jira accounts:
- Each account has its own API token
- Use the token from the account whose issues you want to see
- The token determines which account's issues you'll get

### Token Security

- **Never share your API token** - it's like a password
- If compromised, revoke it and create a new one
- Store it securely in your `.env` file (never commit to git)

## Troubleshooting

### "No issues found" but you know you have issues?

1. **Check who you are**:
   ```bash
   # Use the get_jira_current_user tool
   ```

2. **Verify token matches account**:
   - Make sure `JIRA_EMAIL` matches the account that created the token
   - Check if the token is for the correct Jira instance

3. **Check Jira permissions**:
   - Make sure your account has permission to view assigned issues
   - Some Jira instances restrict API access

### "Authentication failed"

1. **Token might be revoked**: Generate a new token
2. **Email mismatch**: Ensure `JIRA_EMAIL` matches the token's account
3. **Wrong Jira URL**: Verify `JIRA_URL` is correct

## Summary

- ✅ **API token determines "who you are"**
- ✅ **Jira identifies you based on the token**
- ✅ **`currentUser()` in JQL refers to the authenticated account**
- ✅ **Email in .env should match the token's account**

The system doesn't guess - it uses the account associated with your API token!


