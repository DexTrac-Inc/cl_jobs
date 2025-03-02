#!/usr/bin/env python3
import os
import sys
import json
import requests
import urllib3
import logging
import argparse
from logging.handlers import SysLogHandler
from dotenv import load_dotenv
import time
import io
from contextlib import redirect_stdout

# Import components from the job manager
from core.chainlink_api import ChainlinkAPI
from utils.helpers import load_config, retry_on_connection_error
from utils.bridge_ops import create_missing_bridges, check_bridge_config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables
load_dotenv()

# Logging setup - main application logger
logger = logging.getLogger("ChainlinkJobManager")
logger.setLevel(logging.DEBUG)

# Define consistent log format
log_format = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

# Console logging (terminal output)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)

# File logging
file_handler = logging.FileHandler("chainlink_jobs.log")
file_handler.setFormatter(log_format)
file_handler.setLevel(logging.DEBUG)
logger.addHandler(file_handler)

# Syslog (journalctl) logging
try:
    syslog_handler = SysLogHandler(address='/dev/log')
    syslog_handler.setFormatter(logging.Formatter('%(name)s: %(levelname)s %(message)s'))
    syslog_handler.setLevel(logging.INFO)
    logger.addHandler(syslog_handler)
except (FileNotFoundError, PermissionError):
    logger.warning("Could not connect to syslog, skipping syslog handler")

# Ensure child loggers inherit settings
logging.getLogger("ChainlinkJobManager.api").setLevel(logging.DEBUG)
logging.getLogger("ChainlinkJobManager.helpers").setLevel(logging.DEBUG)
logging.getLogger("ChainlinkJobManager.bridge_ops").setLevel(logging.DEBUG)

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
    """
    Load Chainlink node hosts from configuration
    
    Returns:
    - List of tuples (service, network, url, password) for all configured nodes
    """
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
    """
    Load list of open PagerDuty incidents from file with file locking
    to prevent race conditions when multiple instances run concurrently
    
    Returns:
    - Dictionary of tracked incidents
    """
    import fcntl
    
    try:
        if os.path.exists(INCIDENTS_FILE):
            with open(INCIDENTS_FILE, 'r') as f:
                # Acquire a shared lock (multiple readers can access)
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    return json.load(f)
                finally:
                    # Release the lock
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in incidents file: {e}")
        # If JSON is corrupt, return empty dict
        return {}
    except Exception as e:
        logger.error(f"Error loading incidents file: {e}")
        return {}

def save_open_incidents(incidents):
    """
    Save list of open PagerDuty incidents to file with file locking
    to prevent race conditions when multiple instances run concurrently
    
    Parameters:
    - incidents: Dictionary of incidents to save
    """
    import fcntl
    import tempfile
    import os
    import shutil
    
    try:
        # Create a temporary file in the same directory
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', 
            dir=os.path.dirname(os.path.abspath(INCIDENTS_FILE)),
            delete=False
        )
        
        try:
            # Write incidents to the temporary file
            json.dump(incidents, temp_file, indent=2)
            temp_file.flush()
            os.fsync(temp_file.fileno())  # Ensure data is written to disk
            temp_file.close()
            
            # Open the target file with exclusive lock
            with open(INCIDENTS_FILE, 'w') as f:
                # Acquire an exclusive lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                
                try:
                    # Copy from temp file to the target file
                    shutil.copy2(temp_file.name, INCIDENTS_FILE)
                finally:
                    # Release the lock
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            # Clean up the temporary file
            try:
                os.unlink(temp_file.name)
            except:
                pass
                
    except Exception as e:
        logger.error(f"Error saving incidents file: {e}")

def track_incident(service, network, job_id, error_msg=None):
    """
    Add job to open incidents tracking with error message
    
    Parameters:
    - service: Service name
    - network: Network name
    - job_id: ID of the failing job
    - error_msg: Error message to store
    
    Returns:
    - Boolean indicating if this is a new incident
    """
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
    """
    Remove job from open incidents tracking
    
    Parameters:
    - service: Service name
    - network: Network name
    - job_id: ID of the job to remove
    """
    incidents = load_open_incidents()
    key = f"{service}_{network}"
    
    if key in incidents and job_id in incidents[key]:
        incidents[key].pop(job_id)
        if not incidents[key]:  # Remove key if no more incidents
            incidents.pop(key)
        save_open_incidents(incidents)

def get_jobs_to_approve(jobs):
    """
    Filter jobs that need approval
    
    Parameters:
    - jobs: List of jobs
    
    Returns:
    - List of tuples (spec_id, job) that need approval
    """
    pending_jobs, updated_jobs = [], []
    for job in jobs:
        if job["status"] == "PENDING":
            pending_jobs.append((job["latestSpec"]["id"], job))
        elif job.get("latestSpec", {}).get("status") == "PENDING":
            updated_jobs.append((job["latestSpec"]["id"], job))
    return pending_jobs + updated_jobs

def check_open_incidents(chainlink_api, service, network):
    """
    Check if any tracked incidents can be resolved
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - service: Service name
    - network: Network name
    """
    incidents = load_open_incidents()
    key = f"{service}_{network}"
    
    if key not in incidents or not incidents[key]:
        return
        
    logger.info(f"Checking status of {len(incidents[key])} tracked incidents for {service} {network}")
    
    for fm in chainlink_api.get_all_feeds_managers(use_logger=True):
        jobs = chainlink_api.fetch_jobs(fm["id"], use_logger=True)
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

def approve_jobs(chainlink_api, jobs_to_approve, service, network, suppress_notifications=False):
    """Approve the specified jobs"""
    approved_jobs = []
    failed_jobs = []
    
    # Import needed for redirection
    import io
    from contextlib import redirect_stdout
    
    for spec_id, job in jobs_to_approve:
        job_name = job.get('name', 'Unknown')
        job_id = job.get('id', 'Unknown')
        
        try:
            logger.info(f"Approving job: {job_name} (Spec ID: {spec_id})")
            
            # Suppress direct console output from API
            f = io.StringIO()
            with redirect_stdout(f):
                success = chainlink_api.approve_job(spec_id, use_logger=True)
            
            if success:
                logger.info(f"Successfully approved {job_name}")
                approved_jobs.append(job)
            else:
                # Get the detailed error from the last response
                error_response = getattr(chainlink_api.session, '_last_response', None)
                error_text = ""
                if error_response and hasattr(error_response, 'text'):
                    error_text = error_response.text
                    # Log the full error via logger
                    for line in error_text.split('\n'):
                        logger.debug(line)
                
                logger.error(f"Failed to approve {job_name}")
                
                # Create a copy of the job with error details
                job_with_error = job.copy()
                job_with_error['error_details'] = error_text
                
                # Process bridge errors
                if "bridge check: not all bridges exist" in error_text:
                    logger.warning(f"Bridge error detected. Attempting to create missing bridges...")
                    
                    # Use use_logger=True to tell bridge functions to use logger
                    bridges_created = create_missing_bridges(
                        chainlink_api, 
                        error_text, 
                        service, 
                        network, 
                        log_to_console=False,
                        use_logger=True
                    )
                    
                    if bridges_created:
                        logger.info(f"Missing bridges created successfully. Retrying approval...")
                        
                        # Suppress direct console output from retry
                        f = io.StringIO()
                        with redirect_stdout(f):
                            retry_success = chainlink_api.approve_job(spec_id, use_logger=True)
                        
                        if retry_success:
                            logger.info(f"Successfully approved {job_name} after adding missing bridges")
                            approved_jobs.append(job)
                            continue
                        else:
                            logger.error(f"Failed to approve {job_name} even after adding bridges")
                    else:
                        logger.error(f"Failed to create missing bridges for {job_name}")
                    
                    # Check if bridges exist in other groups
                    missing_bridges, other_group_bridges = check_bridge_config(
                        error_text, 
                        service, 
                        network, 
                        log_to_console=False,
                        use_logger=True
                    )
                    
                    if missing_bridges:
                        bridge_error = f"These bridges are not configured in any group: {', '.join(missing_bridges)}"
                        logger.error(bridge_error)
                        job_with_error['bridge_diagnostic'] = bridge_error
                        
                    if other_group_bridges:
                        logger.error("Some bridges exist in other bridge groups:")
                        group_info = []
                        for bridge, groups in other_group_bridges:
                            bridge_msg = f"{bridge} found in groups: {', '.join(groups)}"
                            logger.error(f"  - {bridge_msg}")
                            group_info.append(bridge_msg)
                        
                        if group_info:
                            job_with_error['other_groups'] = "Bridges found in other groups: " + "; ".join(group_info)
                
                failed_jobs.append(job_with_error)
                
        except Exception as e:
            logger.error(f"Exception when approving {job_name}: {str(e)}")
            
            # Create a copy with error details
            job_with_error = job.copy()
            job_with_error['error_details'] = str(e)
            failed_jobs.append(job_with_error)
    
    # Send notifications
    if not suppress_notifications:
        # Only send notifications if we have results to report
        if approved_jobs:
            send_approval_notification(service, network, approved_jobs)
        
        if failed_jobs:
            send_failure_notification(service, network, failed_jobs)
    
    return approved_jobs, failed_jobs

def send_approval_notification(service, network, approved_jobs):
    """
    Send notification for successfully approved jobs
    
    Parameters:
    - service: Service name
    - network: Network name
    - approved_jobs: List of successfully approved jobs
    """
    # Format job names as a list with the service/network as header
    approved_job_names = "\n".join(job.get('name', 'Unknown') for job in approved_jobs)
    success_message = f"✅ Approved jobs for {service} {network}:\n```{approved_job_names}```"
    send_slack_alert(success_message)
    
    # Resolve any existing incidents for these jobs
    for job in approved_jobs:
        job_id = job.get('id', 'Unknown')
        # Successfully approved - remove from tracking
        remove_incident(service, network, job_id)
        send_pagerduty_alert(
            f"job_fail_{service}_{network}_{job_id}", 
            f"Job approval resolved on {service} {network}", 
            {"job_id": job_id, "status": "APPROVED"}, 
            action="resolve"
        )

def send_failure_notification(service, network, failed_jobs):
    """
    Send notification for jobs that failed to approve
    
    Parameters:
    - service: Service name
    - network: Network name
    - failed_jobs: List of jobs that failed to approve
    """
    new_failures = []
    
    # Track incidents and identify new failures
    for job in failed_jobs:
        job_id = job.get('id', 'Unknown')
        job_name = job.get('name', 'Unknown')
        
        # Build a detailed error message
        error_details = job.get('error_details', 'No error details available')
        error_msg = f"Failed to approve job {job_id} ({job_name}): {error_details}"
        
        # Add bridge diagnostic information if available
        if 'bridge_diagnostic' in job:
            error_msg += f"\n{job['bridge_diagnostic']}"
        if 'other_groups' in job:
            error_msg += f"\n{job['other_groups']}"
        
        # Track the incident and check if it's new
        is_new = track_incident(service, network, job_id, error_msg)
        if is_new:
            new_failures.append(job)
            
        # Send PagerDuty alert for each failure
        alert_details = {
            "error": error_msg,
            "node": network,
            "job_id": job_id
        }
        
        send_pagerduty_alert(
            f"job_fail_{service}_{network}_{job_id}", 
            f"Job approval error on {service} {network}", 
            alert_details
        )
    
    # Send Slack alert only for new failures
    if new_failures:
        # Format detailed failure messages for the code block
        failure_messages = []
        for job in new_failures:
            job_details = f"Job {job.get('id', 'Unknown')}: {job.get('name', 'Unknown')}"
            
            if 'error_details' in job:
                # Truncate long error messages for Slack
                error_details = job.get('error_details', '')
                if len(error_details) > 300:
                    error_details = error_details[:297] + "..."
                job_details += f"\nError: {error_details}"
                
            # Add bridge diagnostic information if available
            if 'bridge_diagnostic' in job:
                job_details += f"\n{job['bridge_diagnostic']}"
            if 'other_groups' in job:
                job_details += f"\n{job['other_groups']}"
                
            failure_messages.append(job_details)
        
        # Send formatted message with @channel mention
        failure_message = f"@channel :warning: Job approval failed for {service} {network}:\n```" + "\n\n".join(failure_messages) + "```"
        send_slack_alert(failure_message)

@retry_on_connection_error(max_retries=3, base_delay=1, max_delay=10)
def send_slack_alert(message, use_logger=True):
    """
    Send an alert to Slack
    
    Parameters:
    - message: Message text to send
    - use_logger: Whether to use logger instead of print
    """
    if SLACK_WEBHOOK:
        logger.debug(f"Sending Slack alert: {message}")
        try:
            response = requests.post(SLACK_WEBHOOK, json={"text": message}, timeout=30)
            logger.debug(f"Slack response code: {response.status_code}")
        except requests.exceptions.Timeout:
            logger.error("Slack alert timed out")
        except Exception as e:
            logger.error(f"Error sending Slack alert: {str(e)}")

@retry_on_connection_error(max_retries=3, base_delay=1, max_delay=10)
def send_pagerduty_alert(alert_key, summary, details, action="trigger", use_logger=True):
    """
    Send an alert to PagerDuty
    
    Parameters:
    - alert_key: Deduplication key for the alert
    - summary: Alert summary
    - details: Alert details
    - action: Action type (trigger, resolve, etc.)
    - use_logger: Whether to use logger instead of print
    """
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
                timeout=30
            )
            logger.debug(f"PagerDuty response code: {response.status_code}")
        except requests.exceptions.Timeout:
            logger.error(f"PagerDuty alert timed out for {alert_key}")
        except Exception as e:
            logger.error(f"Error sending PagerDuty alert: {str(e)}")

def main():
    # Parse command line arguments for manual runs
    parser = argparse.ArgumentParser(description='Chainlink Job Manager - Approve pending jobs')
    parser.add_argument('--suppress-notifications', action='store_true', 
                      help='Suppress Slack and PagerDuty notifications (for manual runs)')
    parser.add_argument('--execute', action='store_true',
                      help='Execute job approvals (override env variable)')
    args = parser.parse_args()
    
    # Override EXECUTE flag if specified in command line
    execute_flag = args.execute or EXECUTE
    suppress_notifications = args.suppress_notifications
    
    logger.info("=" * 60)
    logger.info("Starting Chainlink Job Manager")
    logger.info("=" * 60)
    
    if suppress_notifications:
        logger.info("Notifications are suppressed for this run")
    
    hosts = load_hosts()
    for service, network, url, password in hosts:
        logger.info(f"Checking jobs on {service} {network} ({url})")
        
        # Initialize API client with retry capabilities
        chainlink_api = ChainlinkAPI(url, EMAIL, password)
        
        # Call authenticate directly - no extra logging
        auth_result = chainlink_api.authenticate(use_logger=True)
        
        if not auth_result:
            # Authentication failed logging is handled in chainlink_api.py
            if not suppress_notifications:
                auth_alert_key = f"auth_fail_{service}_{network}"
                send_slack_alert(f":warning: Authentication failed for {service} {network}")
                send_pagerduty_alert(auth_alert_key, 
                                   f"Authentication failed for {service} {network}", 
                                   {"node_url": url})
            continue
            
        # Check any open incidents
        check_open_incidents(chainlink_api, service, network)
            
        for fm in chainlink_api.get_all_feeds_managers(use_logger=True):
            logger.info(f"Fetching job proposals for {fm['name']}")
            try:
                jobs = chainlink_api.fetch_jobs(fm["id"], use_logger=True)
                jobs_to_approve = get_jobs_to_approve(jobs)
                if not jobs_to_approve:
                    logger.info(f"No approvals needed for {fm['name']}")
                    continue
                    
                if not execute_flag:
                    logger.warning(f"EXECUTE flag is not set - No jobs will be approved on {service} {network}")
                    logger.info(f"Would approve {len(jobs_to_approve)} jobs:")
                    for _, job in jobs_to_approve:
                        logger.info(f"  {job['name']} (Job ID: {job['id']})")
                    continue
                    
                approved_jobs, failed_jobs = approve_jobs(
                    chainlink_api, 
                    jobs_to_approve, 
                    service, 
                    network, 
                    suppress_notifications
                )
                    
            except Exception as e:
                logger.error(f"Error processing jobs for {service} {network}: {str(e)}")
                    
    logger.info("=" * 60)
    logger.info("Chainlink Job Manager Complete")
    logger.info("=" * 60)

if __name__ == "__main__":
    main()