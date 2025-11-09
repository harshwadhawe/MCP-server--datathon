#!/usr/bin/env python3
"""
Direct chat interface for the Calendar & GitHub MCP Server.
Starts immediately in chat mode with AI assistant.
"""

import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.server import chat

def main():
    """Main chat interface."""
    print("\n" + "=" * 70)
    print(" " * 20 + "Calendar & GitHub AI Assistant")
    print("=" * 70)
    print("\nWelcome! I'm your AI assistant for Calendar and GitHub.")
    print("Ask me anything about your schedule, availability, events, or GitHub activity.")
    print("\nCalendar Examples:")
    print("  - 'What meetings do I have this week?'")
    print("  - 'Am I free tomorrow at 2 PM?'")
    print("  - 'When am I free next week?'")
    print("  - 'Summarize my schedule for Monday'")
    print("\nGitHub Examples:")
    print("  - 'What are my open issues?'")
    print("  - 'Show me my recent repositories'")
    print("  - 'What PRs are open in my repo?'")
    print("  - 'Show current deployments setup on GitHub'")
    print("  - 'What deployments are live in production?'")
    print("\nType 'exit' or 'quit' to end the conversation.")
    print("=" * 70)
    
    while True:
        try:
            print()
            message = input("You: ").strip()
            
            if not message:
                continue
            
            if message.lower() in ['exit', 'quit', 'bye']:
                print("\n" + "=" * 70)
                print("Thank you for using Calendar & GitHub AI Assistant!")
                print("=" * 70)
                break
            
            # Get AI response
            print("\nAssistant: ", end="", flush=True)
            try:
                # Automatically include GitHub context if message mentions GitHub/repo/issue/PR/deployment
                message_lower = message.lower()
                include_github = any(keyword in message_lower for keyword in 
                                   ['github', 'repo', 'repository', 'issue', 'pr', 'pull request', 'commit',
                                    'deployment', 'deploy', 'deployed', 'deploying', 'production', 'staging'])
                
                result = chat(message, include_calendar_context=True, include_github_context=include_github)
                print(result)
            except Exception as e:
                print(f"Error: {e}")
            
        except KeyboardInterrupt:
            print("\n\nInterrupted by user. Goodbye!")
            break
        except EOFError:
            print("\n\nGoodbye!")
            break

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nFatal error: {e}")
        sys.exit(1)

