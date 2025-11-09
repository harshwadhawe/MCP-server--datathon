#!/usr/bin/env python3
import os
import sys
import getpass
from pathlib import Path
import requests

ENV_PATH = Path(".env")

def load_dotenv():
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k not in os.environ:
            os.environ[k] = v

def write_dotenv(values: dict):
    existing = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            existing[k] = v
    existing.update(values)
    with ENV_PATH.open("w", encoding="utf-8") as f:
        f.write("# Jira credentials - DO NOT COMMIT THIS FILE\n")
        for k, v in existing.items():
            f.write(f"{k}={v}\n")

def prompt_if_missing():
    base_url = os.environ.get("JIRA_BASE_URL", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    if not (base_url and email and token):
        print("First-time setup: I’ll save your Jira details into .env")
        if not base_url:
            base_url = input("Jira Cloud URL (e.g., https://your-domain.atlassian.net): ").strip()
        if not email:
            email = input("Jira email: ").strip()
        if not token:
            token = getpass.getpass("Jira API token (hidden): ").strip()
        if not base_url.startswith("http"):
            print("Error: Invalid Jira URL.")
            sys.exit(2)
        write_dotenv({"JIRA_BASE_URL": base_url, "JIRA_EMAIL": email, "JIRA_API_TOKEN": token})
        os.environ.update({"JIRA_BASE_URL": base_url, "JIRA_EMAIL": email, "JIRA_API_TOKEN": token})

def make_session():
    s = requests.Session()
    s.auth = (os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
    s.headers.update({"Accept": "application/json"})
    return s

def agile_get(session, base_url, endpoint, params=None, ok404=False):
    url = f"{base_url.rstrip('/')}/rest/agile/1.0/{endpoint}"
    r = session.get(url, params=params, timeout=30)
    if ok404 and r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise RuntimeError(f"Agile API {r.status_code}: {r.text}")
    return r.json()

def core_get(session, base_url, endpoint, params=None):
    # Core (Jira REST v3) for JQL search
    url = f"{base_url.rstrip('/')}/rest/api/3/{endpoint}"
    r = session.get(url, params=params, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Core API {r.status_code}: {r.text}")
    return r.json()

def get_all_boards(session, base_url):
    boards, start = [], 0
    while True:
        data = agile_get(session, base_url, "board", {"startAt": start, "maxResults": 50})
        values = data.get("values", [])
        boards.extend(values)
        if data.get("isLast") or not values:
            break
        start += len(values)
    return boards

def get_backlog_via_agile(session, base_url, board_id):
    issues, start = [], 0
    while True:
        data = agile_get(session, base_url, f"board/{board_id}/backlog",
                         {"startAt": start, "maxResults": 50})
        page = data.get("issues", [])
        issues.extend(page)
        total = data.get("total", 0)
        if start + len(page) >= total or not page:
            break
        start += len(page)
    return issues

def get_board_filter_id(session, base_url, board_id):
    cfg = agile_get(session, base_url, f"board/{board_id}/configuration")
    flt = (cfg or {}).get("filter")
    return (flt or {}).get("id")

def get_backlog_via_jql(session, base_url, filter_id):
    # Approximate backlog: issues in this board’s filter without a sprint or only in future sprints
    jql = f'filter = {filter_id} AND (sprint is EMPTY OR sprint in futureSprints()) ORDER BY created'
    issues, start = [], 0
    while True:
        data = core_get(session, base_url, "search",
                        {"jql": jql, "startAt": start, "maxResults": 50, "fields": "summary,status,assignee"})
        page = data.get("issues", [])
        issues.extend(page)
        if start + len(page) >= data.get("total", 0) or not page:
            break
        start += len(page)
    return issues

def print_boards(boards, base_url):
    print("\nAll Jira boards:")
    print("-" * 80)
    for b in boards:
        bid = b.get("id")
        name = b.get("name")
        btype = b.get("type")
        board_url = f"{base_url.rstrip('/')}/jira/boards/{bid}"
        loc = b.get("location", {}) or {}
        loc_type = loc.get("type")
        loc_name = loc.get("name")
        loc_suffix = f" | location: {loc_type} - {loc_name}" if (loc_type or loc_name) else ""
        print(f"[{bid}] {name} ({btype}) -> {board_url}{loc_suffix}")
    print("-" * 80)
    print(f"Total boards: {len(boards)}")

def print_issues(issues):
    if not issues:
        print("No backlog issues found.")
        return
    print("\nBacklog Items:")
    print("=" * 120)
    for issue in issues:
        key = issue.get("key")
        fields = issue.get("fields", {})
        summary = fields.get("summary", "No summary")
        status = (fields.get("status") or {}).get("name", "Unknown")
        assignee = ((fields.get("assignee") or {}) or {}).get("displayName", "Unassigned")
        print(f"{key:<12} | {status:<18} | {assignee:<28} | {summary}")
    print("=" * 120)
    print(f"Total backlog issues: {len(issues)}")

def main():
    load_dotenv()
    prompt_if_missing()

    base_url = os.environ["JIRA_BASE_URL"]
    session = make_session()

    # 1) Boards
    boards = get_all_boards(session, base_url)
    if not boards:
        print("No boards found.")
        return
    print_boards(boards, base_url)

    # 2) Backlog for first board
    first = boards[0]
    bid, bname, btype = first["id"], first.get("name"), first.get("type")
    print(f"\nFetching backlog for first board: {bname} (ID: {bid}, type: {btype})...")

    issues = []
    try:
        # Preferred: Agile backlog endpoint
        issues = get_backlog_via_agile(session, base_url, bid)
    except RuntimeError as e:
        # Fall through to JQL on errors like 403/404
        print(f"Backlog endpoint not available: {e}\nFalling back to JQL…")

    if not issues:
        # Fallback: JQL using board filter
        fid = get_board_filter_id(session, base_url, bid)
        if not fid:
            print("Could not resolve board filter; cannot fall back to JQL.")
        else:
            issues = get_backlog_via_jql(session, base_url, fid)

    print_issues(issues)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
