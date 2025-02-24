import os
import json
import requests
import urllib3
import logging
from logging.handlers import SysLogHandler
from dotenv import load_dotenv
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables
load_dotenv()

# Logging setup
logger = logging.getLogger("ChainlinkJobManager")
logger.setLevel(logging.DEBUG)  # Changed from INFO to DEBUG

# Define consistent log format
log_format = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

# Console logging (terminal output)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)
console_handler.setLevel(logging.INFO)  # Keep console at INFO level
logger.addHandler(console_handler)

# File logging
file_handler = logging.FileHandler("chainlink_jobs.log")
file_handler.setFormatter(log_format)
file_handler.setLevel(logging.DEBUG)  # File gets DEBUG level
logger.addHandler(file_handler)

# Syslog (journalctl) logging
syslog_handler = SysLogHandler(address='/dev/log')
syslog_handler.setFormatter(logging.Formatter('%(name)s: %(levelname)s %(message)s'))
syslog_handler.setLevel(logging.INFO)  # Keep syslog at INFO level
logger.addHandler(syslog_handler)

# Slack and PagerDuty setup
SLACK_WEBHOOK = os.getenv("SLACK_WEBHOOK")
PAGERDUTY_INTEGRATION_KEY = os.getenv("PAGERDUTY_INTEGRATION_KEY")

CONFIG_FILE = "cl_hosts.json"
INCIDENTS_FILE = "open_incidents.json"

EMAIL = os.getenv("EMAIL")
EXECUTE = os.getenv("EXECUTE", "0") == "1"

if not EMAIL:
    logger.error("Missing required environment variable (EMAIL).")
    exit(1)

def load_hosts():
    try:
        with open(CONFIG_FILE, "r") as file:
            data = json.load(file)

        hosts = []
        for service, networks in data.get("services", {}).items():
            for network, details in networks.items():
                url = details["url"]
                password_index = details["password"]
                password = os.getenv(f"PASSWORD_{password_index}")
                hosts.append((service.upper(), network.upper(), url, password))

        if not hosts:
            logger.error("No hosts found in the JSON file")
        return hosts

    except Exception as e:
        logger.exception(f"Failed to load {CONFIG_FILE}: {e}")
        return []

def load_open_incidents():
    """Load list of open PagerDuty incidents from file"""
    try:
        if os.path.exists(INCIDENTS_FILE):
            with open(INCIDENTS_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error loading incidents file: {e}")
        return {}

def save_open_incidents(incidents):
    """Save list of open PagerDuty incidents to file"""
    try:
        with open(INCIDENTS_FILE, 'w') as f:
            json.dump(incidents, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving incidents file: {e}")

def track_incident(service, network, job_id, error_msg=None):
    """Add job to open incidents tracking with error message"""
    incidents = load_open_incidents()
    key = f"{service}_{network}"
    
    # Check if this is a new incident or existing one
    is_new_incident = True
    
    # Handle transitioning from old list format to new dict format
    if key in incidents:
        # Convert from old list format if needed
        if isinstance(incidents[key], list):
            temp_dict = {}
            for old_job_id in incidents[key]:
                temp_dict[old_job_id] = {
                    "error": None,
                    "first_seen": time.time(),
                    "last_seen": time.time()
                }
            incidents[key] = temp_dict
            
        # Now check if this job ID is already tracked
        if job_id in incidents[key]:
            is_new_incident = False
    else:
        incidents[key] = {}
        
    # Store the error message with the incident
    if is_new_incident or job_id not in incidents[key]:
        incidents[key][job_id] = {
            "error": error_msg,
            "first_seen": time.time(),
            "last_seen": time.time()
        }
    else:
        # Update existing incident
        incidents[key][job_id]["error"] = error_msg
        incidents[key][job_id]["last_seen"] = time.time()
    
    save_open_incidents(incidents)
    return is_new_incident

def remove_incident(service, network, job_id):
    """Remove job from open incidents tracking"""
    incidents = load_open_incidents()
    key = f"{service}_{network}"
    
    if key in incidents and job_id in incidents[key]:
        incidents[key].pop(job_id)
        if not incidents[key]:  # Remove key if no more incidents
            incidents.pop(key)
        save_open_incidents(incidents)

def authenticate(session, node_url, password):
    session_endpoint = f"{node_url}/sessions"
    try:
        auth_response = session.post(
            session_endpoint, 
            json={"email": EMAIL, "password": password}, 
            verify=False,
            timeout=30  # 30 second timeout
        )

        if auth_response.status_code != 200:
            logger.error(f"Authentication failed for {node_url}")
            return None

        logger.info(f"Authentication successful for {node_url}")
        return session
    except requests.exceptions.Timeout:
        logger.error(f"Authentication request timed out for {node_url}")
        return None
    except Exception as e:
        logger.error(f"Authentication error for {node_url}: {str(e)}")
        return None

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
    try:
        response = session.post(
            graphql_endpoint, 
            json={"query": query}, 
            verify=False,
            timeout=30  # 30 second timeout
        )
        data = response.json()
        
        if "errors" in data:
            logger.error(f"GraphQL Query Error on {node_url}:")
            logger.error(json.dumps(data["errors"], indent=2))
            return []
            
        feeds_managers = data.get("data", {}).get("feedsManagers", {}).get("results", [])
        return feeds_managers
    except requests.exceptions.Timeout:
        logger.error(f"Request timed out when fetching feeds managers from {node_url}")
        return []
    except Exception as e:
        logger.error(f"Error fetching feeds managers from {node_url}: {str(e)}")
        return []

def fetch_jobs(session, node_url, feeds_manager_id):
    graphql_endpoint = f"{node_url}/query"
    query = """
    query FetchFeedsManager($id: ID!) {
        feedsManager(id: $id) {
            ... on FeedsManager {
                jobProposals {
                    id
                    name
                    status
                    latestSpec {
                        id
                        status
                    }
                }
            }
        }
    }
    """
    variables = {"id": str(feeds_manager_id)}
    try:
        response = session.post(
            graphql_endpoint, 
            json={"query": query, "variables": variables}, 
            verify=False,
            timeout=30  # 30 second timeout
        )
        data = response.json()
        
        if "errors" in data:
            logger.error(f"GraphQL Error on {node_url}: {data['errors']}")
            return []
            
        return data.get("data", {}).get("feedsManager", {}).get("jobProposals", [])
    except requests.exceptions.Timeout:
        logger.error(f"Request timed out when fetching jobs from {node_url}")
        return []
    except Exception as e:
        logger.error(f"Error fetching jobs from {node_url}: {str(e)}")
        return []

def get_jobs_to_approve(jobs):
    pending_jobs, updated_jobs = [], []
    for job in jobs:
        if job["status"] == "PENDING":
            pending_jobs.append((job["latestSpec"]["id"], job))
        elif job.get("latestSpec", {}).get("status") == "PENDING":
            updated_jobs.append((job["latestSpec"]["id"], job))
    return pending_jobs + updated_jobs

def check_open_incidents(session, node_url, service, network):
    """Check if any tracked incidents can be resolved"""
    incidents = load_open_incidents()
    key = f"{service}_{network}"
    
    if key not in incidents or not incidents[key]:
        return
        
    logger.info(f"Checking status of {len(incidents[key])} tracked incidents for {service} {network}")
    
    for fm in get_all_feeds_managers(session, node_url):
        jobs = fetch_jobs(session, node_url, fm["id"])
        for job in jobs:
            if job['id'] in incidents[key]:
                if job["status"] != "PENDING" and job.get("latestSpec", {}).get("status") != "PENDING":
                    # Job is no longer pending, resolve the incident
                    send_pagerduty_alert(f"job_fail_{service}_{network}_{job['id']}", 
                                       f"Job approval resolved on {service} {network}", 
                                       {"job_id": job['id'], "status": job['status']}, 
                                       action="resolve")
                    remove_incident(service, network, job['id'])
                    logger.info(f"Resolved incident for job {job['id']} on {service} {network}")

def approve_jobs(session, node_url, jobs_to_approve, service, network):
    graphql_endpoint = f"{node_url}/query"
    mutation = """
    mutation ApproveJobProposalSpec($id: ID!, $force: Boolean) {
        approveJobProposalSpec(id: $id, force: $force) {
            ... on ApproveJobProposalSpecSuccess {
                spec { id }
            }
            ... on NotFoundError { message }
        }
    }
    """
    approved_jobs = []
    failed_jobs = []
    new_failures = []
    
    for job_id, job in jobs_to_approve:
        try:
            logger.info(f"Approving job ID: {job_id} ({job['name']})")
            response = session.post(
                graphql_endpoint, 
                json={"query": mutation, "variables": {"id": job_id, "force": True}}, 
                verify=False,
                timeout=30
            )
            result = response.json()
            if "errors" in result:
                error_msg = f"{job['name']}: {result['errors']}"
                logger.error(f"Failed to approve job {job_id}: {error_msg}")
                failed_jobs.append((job_id, job, error_msg))
                
                # Track the incident and check if it's new
                is_new = track_incident(service, network, job['id'], error_msg)
                if is_new:
                    new_failures.append((job_id, job, error_msg))
                    
                send_pagerduty_alert(f"job_fail_{service}_{network}_{job['id']}", 
                                   f"Job approval error on {service} {network}", 
                                   {"error": error_msg, "node": node_url, "job_id": job['id']})
                continue
                
            logger.info(f"Approved job ID: {job_id} ({job['name']})")
            approved_jobs.append(job)
            
            # Successfully approved - remove from tracking
            remove_incident(service, network, job['id'])
            send_pagerduty_alert(f"job_fail_{service}_{network}_{job['id']}", 
                               f"Job approval resolved on {service} {network}", 
                               {"job_id": job['id'], "status": "APPROVED"}, 
                               action="resolve")
        except requests.exceptions.Timeout:
            error_msg = f"Request timed out after 30 seconds when approving job {job_id}"
            logger.error(error_msg)
            failed_jobs.append((job_id, job, error_msg))
            
            # Track the incident and check if it's new
            is_new = track_incident(service, network, job['id'], error_msg)
            if is_new:
                new_failures.append((job_id, job, error_msg))
                
            send_pagerduty_alert(f"job_fail_{service}_{network}_{job['id']}", 
                               f"Job approval error on {service} {network}", 
                               {"error": error_msg, "node": node_url, "job_id": job['id']})
            continue
        except Exception as e:
            error_msg = f"Failed to approve job {job_id}: {str(e)}"
            logger.error(error_msg)
            failed_jobs.append((job_id, job, str(e)))
            
            # Track the incident and check if it's new
            is_new = track_incident(service, network, job['id'], error_msg)
            if is_new:
                new_failures.append((job_id, job, error_msg))
                
            send_pagerduty_alert(f"job_fail_{service}_{network}_{job['id']}", 
                               f"Job approval error on {service} {network}", 
                               {"error": str(e), "node": node_url, "job_id": job['id']})
            continue
            
    # Send Slack alert only for new failures
    if new_failures:
        failure_messages = []
        for job_id, job, error in new_failures:
            failure_messages.append(f"Job {job['id']}: {job['name']}\nerror: {error}")
        failure_message = f"<!channel> :warning: Approval failed for {service} {network}:\n```" + "\n\n".join(failure_messages) + "```"
        send_slack_alert(failure_message)
        
    # Send Slack alert for approved jobs
    if approved_jobs:
        success_message = f"Approved jobs for {service} {network}:\n```" + \
                         "\n".join(job['name'] for job in approved_jobs) + "```"
        send_slack_alert(success_message)
        
    return approved_jobs, failed_jobs

def send_slack_alert(message):
    if SLACK_WEBHOOK:
        logger.debug(f"Sending Slack alert: {message}")
        try:
            response = requests.post(SLACK_WEBHOOK, json={"text": message}, timeout=30)
            logger.debug(f"Slack response code: {response.status_code}")
        except requests.exceptions.Timeout:
            logger.error("Slack alert timed out")
        except Exception as e:
            logger.error(f"Error sending Slack alert: {str(e)}")

def send_pagerduty_alert(alert_key, summary, details, action="trigger"):
    if PAGERDUTY_INTEGRATION_KEY:
        payload = {
            "routing_key": PAGERDUTY_INTEGRATION_KEY,
            "event_action": action,
            "dedup_key": alert_key,
            "payload": {
                "summary": summary,
                "severity": "error",
                "source": alert_key,
                "custom_details": details
            }
        }
        logger.debug(f"Sending PagerDuty {action} alert for {alert_key}: {summary}")
        try:
            response = requests.post(
                "https://events.pagerduty.com/v2/enqueue", 
                json=payload,
                timeout=30  # 30 second timeout
            )
            logger.debug(f"PagerDuty response code: {response.status_code}")
        except requests.exceptions.Timeout:
            logger.error(f"PagerDuty alert timed out for {alert_key}")
        except Exception as e:
            logger.error(f"Error sending PagerDuty alert: {str(e)}")

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Starting Chainlink Job Manager")
    logger.info("=" * 60)
    
    hosts = load_hosts()
    for service, network, url, password in hosts:
        logger.info(f"Checking jobs on {service} {network} ({url})")
        
        session = requests.Session()
        if not authenticate(session, url, password):
            auth_alert_key = f"auth_fail_{service}_{network}"
            send_slack_alert(f":warning: Authentication failed for {service} {network}")
            send_pagerduty_alert(auth_alert_key, 
                               f"Authentication failed for {service} {network}", 
                               {"node_url": url})
            continue
            
        # Check any open incidents
        check_open_incidents(session, url, service, network)
            
        for fm in get_all_feeds_managers(session, url):
            logger.info(f"Fetching job proposals for {fm['name']}")
            try:
                jobs_to_approve = get_jobs_to_approve(fetch_jobs(session, url, fm["id"]))
                if not jobs_to_approve:
                    logger.info(f"No approvals needed for {fm['name']}")
                    continue
                    
                if not EXECUTE:
                    logger.warning(f"EXECUTE flag is not set - No jobs will be approved on {service} {network}")
                    continue
                    
                approved_jobs, failed_jobs = approve_jobs(session, url, jobs_to_approve, service, network)
                    
            except Exception as e:
                logger.error(f"Error processing jobs for {service} {network}: {str(e)}")
                    
    logger.info("=" * 60)
    logger.info("Chainlink Job Manager Complete")
    logger.info("=" * 60)