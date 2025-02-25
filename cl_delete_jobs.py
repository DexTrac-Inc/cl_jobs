#!/usr/bin/env python3
import os
import json
import requests
import urllib3
import argparse
import re
import time
import random
from dotenv import load_dotenv
from requests.exceptions import RequestException, SSLError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables from .env
load_dotenv()

# Retry decorator for API calls
def retry_on_connection_error(max_retries=3, base_delay=1, max_delay=10):
    """
    Decorator to retry functions on connection errors with exponential backoff.
    
    Parameters:
    - max_retries: Maximum number of retry attempts
    - base_delay: Initial delay in seconds
    - max_delay: Maximum delay in seconds
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            retries = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except (RequestException, SSLError) as e:
                    retries += 1
                    if retries > max_retries:
                        print(f"❌ Max retries exceeded. Last error: {e}")
                        raise
                    
                    # Calculate delay with exponential backoff and jitter
                    delay = min(base_delay * (2 ** (retries - 1)) + random.uniform(0, 1), max_delay)
                    print(f"⚠️ Connection error: {e}")
                    print(f"⏳ Retrying in {delay:.2f} seconds... (Attempt {retries}/{max_retries})")
                    time.sleep(delay)
        return wrapper
    return decorator

# Parse command line arguments
parser = argparse.ArgumentParser(description='Cancel Chainlink jobs matching specific patterns')
parser.add_argument('--service', required=True, help='Service name (e.g. bootstrap, ocr)')
parser.add_argument('--node', required=True, help='Node name (e.g. arbitrum, ethereum)')
parser.add_argument('--execute', action='store_true', help='Execute cancellations (default: dry run)')
parser.add_argument('--config', default='cl_hosts.json', help='Path to config file (default: cl_hosts.json)')
parser.add_argument('--feed-ids-file', help='Path to file containing feed IDs to cancel (one per line)')
parser.add_argument('--name-pattern', help='Cancel jobs with names matching this pattern (e.g. "cron-capabilities")')
parser.add_argument('--job-id', help='Cancel job with specific ID')
args = parser.parse_args()

# Validate arguments - need at least one way to identify jobs
if not args.feed_ids_file and not args.name_pattern and not args.job_id:
    print("❌ Error: You must specify either --feed-ids-file, --name-pattern, or --job-id")
    exit(1)

# Environment Variables
EMAIL = os.getenv("EMAIL")
if not EMAIL:
    print("❌ Error: Missing required environment variable (EMAIL).")
    exit(1)

# Load configuration from JSON file
CONFIG_FILE = args.config
try:
    with open(CONFIG_FILE, "r") as file:
        config_data = json.load(file)
        
    # Get node URL and password index from config
    try:
        service_config = config_data["services"][args.service]
        node_config = service_config[args.node]
        NODE_URL = node_config["url"]
        PASSWORD_INDEX = node_config["password"]
        PASSWORD = os.getenv(f"PASSWORD_{PASSWORD_INDEX}")
        
        if not PASSWORD:
            print(f"❌ Error: Missing PASSWORD_{PASSWORD_INDEX} environment variable.")
            exit(1)
            
    except KeyError:
        print(f"❌ Error: Service '{args.service}' or node '{args.node}' not found in {CONFIG_FILE}")
        exit(1)
        
except Exception as e:
    print(f"❌ Error: Failed to load {CONFIG_FILE}: {e}")
    exit(1)

EXECUTE = args.execute

# Load Feed IDs from file
def load_feed_ids(feed_ids_file):
    if not feed_ids_file:
        return []
    
    try:
        # Extract feed IDs from the file
        feed_ids = []
        non_hex_patterns = []
        
        with open(feed_ids_file, 'r') as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue  # Skip empty lines and comments
                
                # Look for 0x pattern followed by hexadecimal characters
                matches = re.findall(r'(0x[0-9a-fA-F]+)', line)
                if matches:
                    feed_ids.extend(matches)
                else:
                    # If no hex pattern, use the line as a regular text pattern
                    non_hex_patterns.append(line)
        
        # Check for duplicates
        feed_id_count = {}
        for feed_id in feed_ids:
            feed_id_count[feed_id] = feed_id_count.get(feed_id, 0) + 1
        
        duplicate_feed_ids = {feed_id: count for feed_id, count in feed_id_count.items() if count > 1}
        
        if duplicate_feed_ids:
            print(f"⚠️ Warning: Found {len(duplicate_feed_ids)} duplicate feed IDs in the input file:")
            for feed_id, count in duplicate_feed_ids.items():
                print(f"  - {feed_id} (appears {count} times)")
        
        # Use only unique feed IDs
        unique_feed_ids = list(feed_id_count.keys())
        
        # Summary
        if unique_feed_ids or non_hex_patterns:
            if unique_feed_ids:
                print(f"✅ Loaded {len(unique_feed_ids)} unique feed IDs from {feed_ids_file}")
            if non_hex_patterns:
                print(f"✅ Loaded {len(non_hex_patterns)} non-hex patterns from {feed_ids_file}")
            return unique_feed_ids, non_hex_patterns
        else:
            print(f"⚠️ Warning: No valid identifiers found in {feed_ids_file}")
            return [], []
        
    except Exception as e:
        print(f"❌ Error reading feed IDs file: {e}")
        exit(1)

# Load the feed IDs and patterns
FEED_IDS_TO_CANCEL = []
NON_HEX_PATTERNS = []

if args.feed_ids_file:
    FEED_IDS_TO_CANCEL, NON_HEX_PATTERNS = load_feed_ids(args.feed_ids_file)

if args.name_pattern:
    NON_HEX_PATTERNS.append(args.name_pattern)

# Authenticate with Chainlink Node
@retry_on_connection_error(max_retries=5, base_delay=2, max_delay=30)
def authenticate(session, node_url, password):
    session_endpoint = f"{node_url}/sessions"
    auth_response = session.post(
        session_endpoint,
        json={"email": EMAIL, "password": password},
        verify=False
    )

    if auth_response.status_code != 200:
        print(f"❌ Error: Authentication failed")
        return None

    print(f"✅ Authentication successful")
    return session

# Retrieve Feeds Manager Names Dynamically
@retry_on_connection_error(max_retries=3, base_delay=1, max_delay=10)
def get_all_feeds_managers(session, node_url):
    graphql_endpoint = f"{node_url}/query"

    query = """
    {
        feedsManagers {
            results {
                id
                name
            }
        }
    }
    """

    response = session.post(
        graphql_endpoint,
        json={"query": query},
        verify=False
    )

    try:
        data = response.json()
        if "errors" in data:
            print(f"❌ GraphQL Query Error on {node_url}:")
            print(json.dumps(data["errors"], indent=2))
            return []

        feeds_managers = data.get("data", {}).get("feedsManagers", {}).get("results", [])
        return feeds_managers

    except json.JSONDecodeError:
        print(f"❌ Failed to decode JSON response from {node_url}")
        return []

# Fetch Jobs from Feeds Manager
@retry_on_connection_error(max_retries=3, base_delay=1, max_delay=10)
def fetch_jobs_to_cancel(session, node_url, feeds_manager_id):
    graphql_endpoint = f"{node_url}/query"

    query = """
    query FetchFeedManagerWithProposals($id: ID!) {
        feedsManager(id: $id) {
            ... on FeedsManager {
                jobProposals {
                    ... on JobProposal {
                        id
                        name
                        status
                        pendingUpdate
                        latestSpec {
                            createdAt
                            id
                        }
                    }
                }
            }
            ... on NotFoundError {
                message
                code
                __typename
            }
            __typename
        }
    }
    """

    variables = {"id": str(feeds_manager_id)}
    response = session.post(
        graphql_endpoint,
        json={"query": query, "variables": variables},
        verify=False
    )

    data = response.json()
    if "errors" in data:
        print(f"❌ GraphQL Error on {node_url}: {data['errors']}")
        return []

    return data.get("data", {}).get("feedsManager", {}).get("jobProposals", [])

# Identify Jobs to Cancel
def get_jobs_to_cancel(jobs):
    jobs_to_cancel = []
    matched_feed_ids = set()
    matched_patterns = set()
    matched_job_ids = set()
    
    # Convert all feed IDs to lowercase for case-insensitive comparison
    feed_ids_lower = [feed_id.lower() for feed_id in FEED_IDS_TO_CANCEL]
    
    for job in jobs:
        if job["status"] != "APPROVED":
            continue
            
        job_id = job.get("id", "")
        job_name = job.get("name", "")
        job_name_lower = job_name.lower()
        match_reason = None
        matched_identifier = None
        
        # Check for specific job ID match
        if args.job_id and job_id == args.job_id:
            match_reason = f"job ID {job_id}"
            matched_identifier = job_id
            matched_job_ids.add(job_id)
        
        # Check for feed ID matches
        elif FEED_IDS_TO_CANCEL:
            for i, feed_id_lower in enumerate(feed_ids_lower):
                if feed_id_lower in job_name_lower:
                    match_reason = f"feed ID {FEED_IDS_TO_CANCEL[i]}"
                    matched_identifier = FEED_IDS_TO_CANCEL[i]
                    matched_feed_ids.add(matched_identifier)
                    break
        
        # Check for non-hex pattern matches if no feed ID matched
        if not match_reason and NON_HEX_PATTERNS:
            for pattern in NON_HEX_PATTERNS:
                if pattern.lower() in job_name_lower:
                    match_reason = f"pattern '{pattern}'"
                    matched_identifier = pattern
                    matched_patterns.add(pattern)
                    break
        
        # If we found a match, add the job to our cancel list
        if match_reason:
            latest_spec_id = job.get("latestSpec", {}).get("id")
            if latest_spec_id:
                jobs_to_cancel.append((latest_spec_id, job_name, matched_identifier, match_reason))
            else:
                print(f"⚠️ Warning: Job '{job_name}' has no latest spec ID, skipping")
    
    # Sort jobs by name alphabetically
    jobs_to_cancel.sort(key=lambda x: x[1])
    
    # Identify unmatched feed IDs and patterns
    unmatched_feed_ids = [feed_id for feed_id in FEED_IDS_TO_CANCEL if feed_id not in matched_feed_ids]
    unmatched_patterns = [pattern for pattern in NON_HEX_PATTERNS if pattern not in matched_patterns]
    
    return jobs_to_cancel, unmatched_feed_ids, unmatched_patterns

# Cancel a single job with retry logic
@retry_on_connection_error(max_retries=5, base_delay=2, max_delay=30)
def cancel_job(session, node_url, job_id, job_name, identifier):
    graphql_endpoint = f"{node_url}/query"

    mutation = """
    mutation CancelJobProposalSpec($id: ID!) {
        cancelJobProposalSpec(id: $id) {
            __typename
        }
    }
    """

    print(f"⏳ Cancelling job ID: {job_id} ({job_name})")

    response = session.post(
        graphql_endpoint,
        json={"query": mutation, "variables": {"id": job_id}},
        verify=False
    )

    result = response.json()
    if "errors" in result:
        print(f"❌ Failed to cancel job ID: {job_id}")
        print(json.dumps(result, indent=2))
        return False
    else:
        print(f"✅ Cancelled job ID: {job_id}")
        return True

# Cancel Jobs with proper error handling
def cancel_jobs(session, node_url, jobs_to_cancel):
    successful = 0
    failed = 0
    
    for job_id, job_name, identifier, match_reason in jobs_to_cancel:
        try:
            if cancel_job(session, node_url, job_id, job_name, identifier):
                successful += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Exception when cancelling job {job_id}: {e}")
            failed += 1
    
    return successful, failed

# Main Execution
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print(f"🔍 Checking jobs on {args.service.upper()} {args.node.upper()} ({NODE_URL})")
    
    # Display criteria
    criteria = []
    if args.job_id:
        criteria.append(f"job ID: {args.job_id}")
    if FEED_IDS_TO_CANCEL:
        criteria.append(f"{len(FEED_IDS_TO_CANCEL)} feed IDs")
    if NON_HEX_PATTERNS:
        criteria.append(f"{len(NON_HEX_PATTERNS)} pattern(s): {', '.join(NON_HEX_PATTERNS)}")
    
    print(f"🔍 Cancellation criteria: {' and '.join(criteria)}")

    session = requests.Session()
    session = authenticate(session, NODE_URL, PASSWORD)
    if not session:
        exit(1)

    feeds_managers = get_all_feeds_managers(session, NODE_URL)
    if not feeds_managers:
        print(f"✅ No feeds managers found")
        exit(0)

    found_jobs = False
    all_jobs_to_cancel = []
    all_unmatched_feed_ids = []
    all_unmatched_patterns = []
    total_jobs = 0
    total_successful = 0
    total_failed = 0
    
    # Track all matched patterns globally across feed managers
    all_matched_patterns = set()
    all_matched_feed_ids = set()
    
    for fm in feeds_managers:
        print(f"🔍 Fetching job proposals for {fm['name']}")

        jobs = fetch_jobs_to_cancel(session, NODE_URL, fm["id"])
        jobs_to_cancel, unmatched_feed_ids, unmatched_patterns = get_jobs_to_cancel(jobs)
        
        # Add to the overall list of jobs to cancel
        all_jobs_to_cancel.extend(jobs_to_cancel)
        
        # Track all matched identifiers globally
        for _, _, identifier, match_reason in jobs_to_cancel:
            if "feed ID" in match_reason:
                all_matched_feed_ids.add(identifier)
            elif "pattern" in match_reason:
                all_matched_patterns.add(identifier)
        
        if not jobs_to_cancel:
            print(f"✅ No cancellations needed for {fm['name']}")
            continue
        
        found_jobs = True
        print(f"📋 Found {len(jobs_to_cancel)} jobs to cancel for {fm['name']}")
        total_jobs += len(jobs_to_cancel)
        
        # Just list the jobs if not in execute mode
        if not EXECUTE:
            print("📃 Jobs that would be cancelled (dry run):")
            for job_id, job_name, identifier, match_reason in jobs_to_cancel:
                print(f"  - {job_name} (ID: {job_id}, Match: {match_reason})")
        else:
            # Add a progress counter
            print(f"⏳ Starting cancellation of {len(jobs_to_cancel)} jobs...")
            successful, failed = cancel_jobs(session, NODE_URL, jobs_to_cancel)
            total_successful += successful
            total_failed += failed
    
    # Compute truly unmatched identifiers globally
    all_unmatched_feed_ids = [feed_id for feed_id in FEED_IDS_TO_CANCEL if feed_id not in all_matched_feed_ids]
    all_unmatched_patterns = [pattern for pattern in NON_HEX_PATTERNS if pattern not in all_matched_patterns]
    
    # Report on unmatched feed IDs
    if all_unmatched_feed_ids:
        print("\n" + "=" * 60)
        print(f"⚠️ Found {len(all_unmatched_feed_ids)} feed IDs with no matching jobs:")
        for feed_id in sorted(all_unmatched_feed_ids):
            print(f"  - {feed_id}")
    
    # Report on unmatched patterns
    if all_unmatched_patterns:
        print("\n" + "=" * 60)
        print(f"⚠️ Found {len(all_unmatched_patterns)} patterns with no matching jobs:")
        for pattern in sorted(all_unmatched_patterns):
            print(f"  - {pattern}")
    
    # Print summary
    if EXECUTE and found_jobs:
        print("\n" + "=" * 60)
        print(f"📊 Job Cancellation Summary:")
        print(f"  Total jobs processed: {total_jobs}")
        print(f"  Successfully cancelled: {total_successful}")
        print(f"  Failed to cancel: {total_failed}")
            
    if not found_jobs:
        print("✅ No matching jobs found for cancellation")
    elif not EXECUTE:
        print("\n⚠️ Dry run completed. Use --execute flag to perform actual cancellations.")