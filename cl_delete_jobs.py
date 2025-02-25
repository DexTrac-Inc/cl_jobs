import os
import json
import requests
import urllib3
import argparse
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables from .env
load_dotenv()

# Parse command line arguments
parser = argparse.ArgumentParser(description='Cancel Chainlink jobs matching specific feed IDs')
parser.add_argument('--service', required=True, help='Service name (e.g. bootstrap, ocr)')
parser.add_argument('--node', required=True, help='Node name (e.g. arbitrum, ethereum)')
parser.add_argument('--execute', action='store_true', help='Execute cancellations (default: dry run)')
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
                import re
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
FEED_IDS_TO_CANCEL = load_feed_ids(args.feed_ids_file)

# Authenticate with Chainlink Node
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

# Fetch APPROVED Jobs from Feeds Manager
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
def get_jobs_to_cancel(jobs, feed_ids):
    jobs_to_cancel = []
    matched_feed_ids = set()
    
    for job in jobs:
        if job["status"] == "APPROVED":
            for feed_id in feed_ids:
                if feed_id in job["name"]:
                    jobs_to_cancel.append((job["latestSpec"]["id"], job["name"], feed_id))
                    matched_feed_ids.add(feed_id)
    
    # Sort jobs by name alphabetically
    jobs_to_cancel.sort(key=lambda x: x[1])
    
    # Identify unmatched feed IDs
    unmatched_feed_ids = [feed_id for feed_id in feed_ids if feed_id not in matched_feed_ids]
    
    return jobs_to_cancel, unmatched_feed_ids

# Cancel Jobs
def cancel_jobs(session, node_url, jobs_to_cancel):
    graphql_endpoint = f"{node_url}/query"

    mutation = """
    mutation CancelJobProposalSpec($id: ID!) {
        cancelJobProposalSpec(id: $id) {
            __typename
        }
    }
    """

    for job_id, job_name, feed_id in jobs_to_cancel:
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
        else:
            print(f"✅ Cancelled job ID: {job_id}")

# Main Execution
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print(f"🔍 Checking jobs on {args.service.upper()} {args.node.upper()} ({NODE_URL})")
    print(f"🔍 Using {len(FEED_IDS_TO_CANCEL)} feed IDs for job matching")

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
    
    for fm in feeds_managers:
        print(f"🔍 Fetching job proposals for {fm['name']}")

        jobs = fetch_jobs_to_cancel(session, NODE_URL, fm["id"])
        jobs_to_cancel, unmatched_feed_ids = get_jobs_to_cancel(jobs, FEED_IDS_TO_CANCEL)
        all_unmatched_feed_ids.extend(unmatched_feed_ids)

        if not jobs_to_cancel:
            print(f"✅ No cancellations needed for {fm['name']}")
            continue
        
        found_jobs = True
        print(f"📋 Found {len(jobs_to_cancel)} jobs to cancel for {fm['name']}")
        
        # Just list the jobs if not in execute mode
        if not EXECUTE:
            print("📃 Jobs that would be cancelled (dry run):")
            for job_id, job_name, feed_id in jobs_to_cancel:
                print(f"  - {job_name} (ID: {job_id})")
        else:
            cancel_jobs(session, NODE_URL, jobs_to_cancel)
    
    # De-duplicate unmatched feed IDs (remove duplicates across feed managers)
    all_unmatched_feed_ids = list(set(all_unmatched_feed_ids))
    
    # Report on unmatched feed IDs
    if all_unmatched_feed_ids:
        print("\n" + "=" * 60)
        print(f"⚠️ Found {len(all_unmatched_feed_ids)} feed IDs with no matching jobs:")
        for feed_id in sorted(all_unmatched_feed_ids):
            print(f"  - {feed_id}")
            
    if not found_jobs:
        print("✅ No matching jobs found for cancellation")
    elif not EXECUTE:
        print("\n⚠️ Dry run completed. Use --execute flag to perform actual cancellations.")