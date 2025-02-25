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
parser = argparse.ArgumentParser(description='Reapprove canceled Chainlink jobs matching specific feed IDs')
parser.add_argument('--service', required=True, help='Service name (e.g. bootstrap, ocr)')
parser.add_argument('--node', required=True, help='Node name (e.g. arbitrum, ethereum)')
parser.add_argument('--execute', action='store_true', help='Execute reapprovals (default: dry run)')
parser.add_argument('--config', default='cl_hosts.json', help='Path to config file (default: cl_hosts.json)')
parser.add_argument('--feed-ids-file', required=True, help='Path to file containing feed IDs (one per line)')
args = parser.parse_args()

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
    # Check if feed_ids_file is provided
    if not feed_ids_file:
        print("❌ Error: Feed IDs file is required")
        exit(1)
    
    try:
        # Extract feed IDs from the file
        feed_ids = []
        with open(feed_ids_file, 'r') as file:
            for line in file:
                # Clean up the line and extract 0x... addresses
                line = line.strip()
                # Look for 0x pattern followed by hexadecimal characters
                matches = re.findall(r'(0x[0-9a-fA-F]+)', line)
                feed_ids.extend(matches)
        
        if not feed_ids:
            print(f"❌ Error: No valid feed IDs found in {feed_ids_file}")
            exit(1)
        
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
        print(f"✅ Loaded {len(unique_feed_ids)} unique feed IDs from {feed_ids_file}")
        return unique_feed_ids
        
    except Exception as e:
        print(f"❌ Error reading feed IDs file: {e}")
        exit(1)

# Load the feed IDs
FEED_IDS_TO_REAPPROVE = load_feed_ids(args.feed_ids_file)

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
def fetch_jobs_to_reapprove(session, node_url, feeds_manager_id):
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
                            id
                            status
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

# Identify Jobs to Reapprove
def get_jobs_to_reapprove(jobs, feed_ids):
    jobs_to_reapprove = []
    matched_feed_ids = set()
    
    # Convert all feed IDs to lowercase for case-insensitive comparison
    feed_ids_lower = [feed_id.lower() for feed_id in feed_ids]
    
    for job in jobs:
        # Check for "CANCELLED" or "CANCELED" status (handle different spellings)
        job_status = job.get("status", "").upper()
        if job_status in ["CANCELLED", "CANCELED"]:
            job_name_lower = job["name"].lower()
            for i, feed_id_lower in enumerate(feed_ids_lower):
                if feed_id_lower in job_name_lower:
                    # We need the latest spec ID - this is what we'll try to approve
                    latest_spec_id = job.get("latestSpec", {}).get("id")
                    if latest_spec_id:
                        jobs_to_reapprove.append((latest_spec_id, job["name"], feed_ids[i], job["id"]))
                        matched_feed_ids.add(feed_ids[i])
                    else:
                        print(f"⚠️ Warning: Job '{job['name']}' has no latest spec ID")
    
    # Sort jobs by name alphabetically
    jobs_to_reapprove.sort(key=lambda x: x[1])
    
    # Identify unmatched feed IDs
    unmatched_feed_ids = [feed_id for feed_id in feed_ids if feed_id not in matched_feed_ids]
    
    return jobs_to_reapprove, unmatched_feed_ids

# Reapprove a single job
@retry_on_connection_error(max_retries=5, base_delay=2, max_delay=30)
def reapprove_job(session, node_url, spec_id, job_name, feed_id, job_id):
    graphql_endpoint = f"{node_url}/query"

    mutation = """
    mutation ApproveJobProposalSpec($id: ID!, $force: Boolean) {
        approveJobProposalSpec(id: $id, force: $force) {
            ... on ApproveJobProposalSpecSuccess {
                spec {
                    id
                }
            }
            ... on NotFoundError {
                message
            }
        }
    }
    """

    print(f"⏳ Reapproving job spec ID: {spec_id} for job proposal ID: {job_id} ({job_name})")

    response = session.post(
        graphql_endpoint,
        json={"query": mutation, "variables": {"id": spec_id, "force": True}},
        verify=False
    )

    result = response.json()
    if "errors" in result:
        print(f"❌ Failed to reapprove job spec ID: {spec_id}")
        print(json.dumps(result, indent=2))
        return False
    else:
        print(f"✅ Reapproved job spec ID: {spec_id} for job ({job_name})")
        return True

# Reapprove Jobs with retry logic
def reapprove_jobs(session, node_url, jobs_to_reapprove):
    successful = 0
    failed = 0
    
    for spec_id, job_name, feed_id, job_id in jobs_to_reapprove:
        try:
            if reapprove_job(session, node_url, spec_id, job_name, feed_id, job_id):
                successful += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Exception when reapproving job {spec_id}: {e}")
            failed += 1
    
    return successful, failed

# Main Execution
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print(f"🔍 Checking for canceled jobs on {args.service.upper()} {args.node.upper()} ({NODE_URL})")
    print(f"🔍 Using {len(FEED_IDS_TO_REAPPROVE)} feed IDs for job matching")

    session = requests.Session()
    session = authenticate(session, NODE_URL, PASSWORD)
    if not session:
        exit(1)

    feeds_managers = get_all_feeds_managers(session, NODE_URL)
    if not feeds_managers:
        print(f"✅ No feeds managers found")
        exit(0)

    found_jobs = False
    all_unmatched_feed_ids = []
    total_jobs = 0
    total_successful = 0
    total_failed = 0
    
    for fm in feeds_managers:
        print(f"🔍 Fetching job proposals for {fm['name']}")

        jobs = fetch_jobs_to_reapprove(session, NODE_URL, fm["id"])
        jobs_to_reapprove, unmatched_feed_ids = get_jobs_to_reapprove(jobs, FEED_IDS_TO_REAPPROVE)
        all_unmatched_feed_ids.extend(unmatched_feed_ids)

        if not jobs_to_reapprove:
            print(f"✅ No jobs to reapprove for {fm['name']}")
            continue
        
        found_jobs = True
        print(f"📋 Found {len(jobs_to_reapprove)} jobs to reapprove for {fm['name']}")
        total_jobs += len(jobs_to_reapprove)
        
        # Just list the jobs if not in execute mode
        if not EXECUTE:
            print("📃 Jobs that would be reapproved (dry run):")
            for spec_id, job_name, feed_id, job_id in jobs_to_reapprove:
                print(f"  - {job_name} (Job ID: {job_id}, Spec ID: {spec_id})")
        else:
            # Add a progress counter
            print(f"⏳ Starting reapproval of {len(jobs_to_reapprove)} jobs...")
            successful, failed = reapprove_jobs(session, NODE_URL, jobs_to_reapprove)
            total_successful += successful
            total_failed += failed
    
    # De-duplicate unmatched feed IDs (remove duplicates across feed managers)
    all_unmatched_feed_ids = list(set(all_unmatched_feed_ids))
    
    # Report on unmatched feed IDs
    if all_unmatched_feed_ids:
        print("\n" + "=" * 60)
        print(f"⚠️ Found {len(all_unmatched_feed_ids)} feed IDs with no matching canceled jobs:")
        
        # Show all unmatched feed IDs (no limit)
        for feed_id in sorted(all_unmatched_feed_ids):
            print(f"  - {feed_id}")
    
    # Print summary
    if EXECUTE and found_jobs:
        print("\n" + "=" * 60)
        print(f"📊 Job Reapproval Summary:")
        print(f"  Total jobs processed: {total_jobs}")
        print(f"  Successfully reapproved: {total_successful}")
        print(f"  Failed to reapprove: {total_failed}")
            
    if not found_jobs:
        print("✅ No matching jobs found for reapproval")
    elif not EXECUTE:
        print("\n⚠️ Dry run completed. Use --execute flag to perform actual reapprovals.")