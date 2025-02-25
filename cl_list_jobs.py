#!/usr/bin/env python3
import os
import json
import requests
import urllib3
import argparse
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
parser = argparse.ArgumentParser(description='List Chainlink jobs with their status')
parser.add_argument('--service', required=True, help='Service name (e.g. bootstrap, ocr)')
parser.add_argument('--node', required=True, help='Node name (e.g. arbitrum, ethereum)')
parser.add_argument('--config', default='cl_hosts.json', help='Path to config file (default: cl_hosts.json)')
parser.add_argument('--status', help='Filter jobs by status (e.g. APPROVED, CANCELLED, PENDING)')
parser.add_argument('--has-updates', action='store_true', help='Show only jobs with pending updates')
parser.add_argument('--output', help='Save output to JSON file')
parser.add_argument('--format', choices=['table', 'json'], default='table', help='Output format (default: table)')
parser.add_argument('--full-width', action='store_true', help='Do not restrict table width for wide terminals')
parser.add_argument('--sort', choices=['name', 'id', 'spec_id', 'updates'], default='name', 
                    help='Sort column (default: name)')
parser.add_argument('--reverse', action='store_true', help='Reverse sort order')
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
def fetch_jobs(session, node_url, feeds_manager_id):
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
                            createdAt
                            version
                        }
                        specs {
                            id
                            status
                            version
                            createdAt
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

# Filter jobs based on criteria
def filter_jobs(jobs):
    filtered_jobs = jobs.copy()
    
    # Apply status filter if specified
    if args.status:
        filtered_jobs = [j for j in filtered_jobs if j.get("status", "").upper() == args.status.upper()]
    
    # Filter for jobs with pending updates if requested
    if args.has_updates:
        filtered_jobs = [j for j in filtered_jobs if j.get("pendingUpdate", False)]
    
    return filtered_jobs

# Display jobs in table format
def display_jobs_table(jobs, manager_name):
    if not jobs:
        print(f"✅ No matching jobs found for {manager_name}")
        return
    
    # Count jobs by status
    status_counts = {}
    jobs_by_status = {}
    
    for job in jobs:
        status = job.get("status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
        
        if status not in jobs_by_status:
            jobs_by_status[status] = []
        
        jobs_by_status[status].append(job)
    
    # Print status summary
    print(f"\n📊 Job Status Summary for {manager_name}:")
    for status, count in status_counts.items():
        print(f"  {status}: {count} jobs")
    
    # Determine column widths based on whether full-width is enabled
    if args.full_width:
        name_width = 200  # Very wide to accommodate any name length
        table_width = 250
    else:
        name_width = 90   # Default width for standard terminals
        table_width = 120
    
    # Define sort key functions
    sort_keys = {
        'name': lambda j: j.get("name", "").lower(),
        'id': lambda j: int(j.get("id", "0")),
        'spec_id': lambda j: int(j.get("latestSpec", {}).get("id", "0")),
        'updates': lambda j: j.get("pendingUpdate", False)
    }
    
    # Get the appropriate sort key function
    sort_key = sort_keys.get(args.sort, sort_keys['name'])
    
    # Process each status group
    for status, status_jobs in sorted(jobs_by_status.items()):
        print(f"\n{status} JOBS ({len(status_jobs)}):")
        print("-" * table_width)
        print("{:<5} {:<{name_width}} {:<15} {:<10}".format(
            "ID", "Name", "Updates", "Spec ID", name_width=name_width))
        print("-" * table_width)
        
        # Sort jobs using the selected sort key and direction
        status_jobs.sort(key=sort_key, reverse=args.reverse)
        
        # Print job info for this status
        for job in status_jobs:
            job_id = job.get("id", "N/A")
            job_name = job.get("name", "N/A")
            has_updates = "Yes" if job.get("pendingUpdate", False) else "No"
            spec_id = job.get("latestSpec", {}).get("id", "N/A")
            
            # Only truncate if not in full-width mode
            if not args.full_width and len(job_name) > name_width:
                truncated_name = job_name[:name_width-3] + "..."
            else:
                truncated_name = job_name
            
            print("{:<5} {:<{name_width}} {:<15} {:<10}".format(
                job_id, truncated_name, has_updates, spec_id, name_width=name_width
            ))

# Main Execution
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print(f"🔍 Listing jobs on {args.service.upper()} {args.node.upper()} ({NODE_URL})")
    
    # Apply any filters to the description
    filter_desc = []
    if args.status:
        filter_desc.append(f"status={args.status.upper()}")
    if args.has_updates:
        filter_desc.append("with pending updates")
    
    if filter_desc:
        print(f"🔍 Filtering jobs: {', '.join(filter_desc)}")
    
    # Show sorting info
    sort_desc = f"sorted by {args.sort}"
    if args.reverse:
        sort_desc += " (reversed)"
    print(f"🔍 {sort_desc}")

    session = requests.Session()
    session = authenticate(session, NODE_URL, PASSWORD)
    if not session:
        exit(1)

    feeds_managers = get_all_feeds_managers(session, NODE_URL)
    if not feeds_managers:
        print(f"✅ No feeds managers found")
        exit(0)

    all_jobs = []
    
    for fm in feeds_managers:
        print(f"🔍 Fetching job proposals for {fm['name']}")

        jobs = fetch_jobs(session, NODE_URL, fm["id"])
        filtered_jobs = filter_jobs(jobs)
        
        # Add manager info to each job for JSON output
        for job in filtered_jobs:
            job["manager"] = fm["name"]
            job["manager_id"] = fm["id"]
        
        all_jobs.extend(filtered_jobs)
        
        # Display table output if requested
        if args.format == 'table':
            display_jobs_table(filtered_jobs, fm['name'])
    
    # Generate JSON output if requested
    if args.format == 'json' or args.output:
        json_output = {
            "service": args.service,
            "node": args.node,
            "url": NODE_URL,
            "total_jobs": len(all_jobs),
            "jobs": all_jobs
        }
        
        if args.format == 'json':
            print(json.dumps(json_output, indent=2))
        
        if args.output:
            try:
                with open(args.output, 'w') as outfile:
                    json.dump(json_output, outfile, indent=2)
                print(f"\n✅ Output saved to {args.output}")
            except Exception as e:
                print(f"\n❌ Error saving output to file: {e}")
    
    # Print summary
    print("\n" + "=" * 60)
    print(f"📊 Total Jobs: {len(all_jobs)}")