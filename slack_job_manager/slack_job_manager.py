#!/usr/bin/env python3
import os
import re
import json
import logging
import time
from typing import Dict, List, Optional, Tuple, Any
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Load environment variables from parent directory
import sys
from pathlib import Path
parent_dir = str(Path(__file__).resolve().parent.parent)
sys.path.append(parent_dir)  # Add parent directory to path for imports
load_dotenv(dotenv_path=os.path.join(parent_dir, '.env'))

from core.chainlink_api import ChainlinkAPI
from utils.helpers import setup_logging, load_node_config
from commands.cancel_cmd import get_jobs_to_cancel, cancel_jobs

# Local imports
from command_parser import SlackCommandParser
from command_executor import CommandExecutor

# Configure logging
logger = setup_logging("ChainlinkJobManager.slack", "chainlink_slack_manager.log")

# Initialize Slack app
app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

# Load authorized users from environment variable
AUTHORIZED_USERS = os.environ.get("SLACK_AUTHORIZED_USERS", "").split(",")

# Message regex patterns for legacy job deletion
JOB_REQUEST_PATTERN = re.compile(
    r"please\s+remove\s+the.*job.*listed\s+below", re.IGNORECASE
)
NETWORK_PATTERN = re.compile(r":([a-zA-Z0-9_-]+):")
CONTRACT_PATTERN = re.compile(r"(0x[a-fA-F0-9]{40})")
NETWORK_NAME_PATTERN = re.compile(r"([a-zA-Z0-9_-]+)-(?:mainnet|testnet)")

# Initialize command parser and executor
command_parser = SlackCommandParser()
command_executor = CommandExecutor()


def validate_user(user_id: str) -> bool:
    """
    Check if a user is authorized to use Chainlink commands
    
    Args:
        user_id: Slack user ID
        
    Returns:
        True if authorized, False otherwise
    """
    if not AUTHORIZED_USERS:
        logger.warning("No authorized users defined, denying all requests")
        return False
        
    return user_id in AUTHORIZED_USERS


class LegacyJobDeleter:
    """
    Legacy job deletion handler for backward compatibility
    with the natural language deletion request format
    """
    
    def __init__(self):
        self.config = load_node_config()
        self.email = os.environ.get("EMAIL")
        self.passwords = {
            i: os.environ.get(f"PASSWORD_{i}") 
            for i in range(10) 
            if os.environ.get(f"PASSWORD_{i}")
        }
        
    def parse_deletion_request(self, text: str) -> Optional[Dict]:
        """Parse a job deletion request from Slack message text"""
        # Check if this looks like a job deletion request
        if not JOB_REQUEST_PATTERN.search(text):
            return None
            
        # Extract network information
        network_match = NETWORK_PATTERN.search(text)
        if not network_match:
            return None
        network = network_match.group(1)
        
        # Extract contract address
        contract_match = CONTRACT_PATTERN.search(text)
        if not contract_match:
            return None
        contract_address = contract_match.group(1)
        
        # Extract network name (e.g., 'fantom-mainnet')
        network_name_match = NETWORK_NAME_PATTERN.search(text)
        network_name = network_name_match.group(0) if network_name_match else None
        
        return {
            "network": network,
            "network_name": network_name,
            "contract_address": contract_address,
            "full_text": text
        }
    
    def find_node_for_network(self, network_name: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Find the appropriate node configuration for a given network"""
        if not self.config or "services" not in self.config:
            logger.error("Invalid configuration file")
            return None, None, None
            
        # Try to match service and node to the network name
        for service, nodes in self.config["services"].items():
            for node, node_config in nodes.items():
                # Match by exact name or partial match
                if (node.lower() == network_name.lower() or
                    network_name.lower().startswith(node.lower())):
                    return service, node, node_config.get("url")
        
        # If no direct match, log an error and continue
        logger.error(f"No node configuration found for network: {network_name}")
        return None, None, None
        
    def process_deletion_request(self, parsed_request: Dict, user_id: str) -> Dict:
        """Process a job deletion request"""
        if not validate_user(user_id):
            return {
                "success": False,
                "message": "❌ You are not authorized to delete jobs. Please contact an administrator."
            }
            
        # Find node configuration
        service, node, node_url = self.find_node_for_network(parsed_request["network_name"])
        if not node_url:
            return {
                "success": False,
                "message": f"❌ Could not find node configuration for network: {parsed_request['network_name']}"
            }
        
        # Get password for this node
        node_config = self.config["services"][service][node]
        password_index = node_config.get("password", 0)
        password = self.passwords.get(password_index)
        
        if not password:
            return {
                "success": False,
                "message": f"❌ No password found for node {service}/{node}"
            }
        
        # Initialize ChainlinkAPI
        api = ChainlinkAPI(node_url, self.email, password)
        
        # Authenticate
        if not api.authenticate():
            return {
                "success": False,
                "message": f"❌ Failed to authenticate with node {service}/{node}"
            }
        
        # Get all feeds managers
        feeds_managers = api.get_all_feeds_managers()
        if not feeds_managers:
            return {
                "success": False,
                "message": f"✅ No feeds managers found on {service}/{node}"
            }
        
        # Prepare for dry run
        contract_address = parsed_request["contract_address"]
        all_jobs_to_cancel = []
        
        # Track all matched patterns globally across feed managers
        all_matched_patterns = set()
        all_matched_feed_ids = set()
        
        # First identify the jobs that would be cancelled (dry run)
        for fm in feeds_managers:
            jobs = api.fetch_jobs(fm["id"])
            jobs_to_cancel, matched_feed_ids, matched_patterns = get_jobs_to_cancel(
                jobs, [contract_address], [], None
            )
            
            # Add to the overall list of jobs to cancel
            all_jobs_to_cancel.extend(jobs_to_cancel)
            
            # Track all matched identifiers globally
            all_matched_feed_ids.update(matched_feed_ids)
            all_matched_patterns.update(matched_patterns)
        
        # Check if we found jobs matching the criteria
        if not all_jobs_to_cancel:
            return {
                "success": False,
                "message": f"❌ No jobs found matching contract address: {contract_address} on {service}/{node}"
            }
        
        # Prepare a message with jobs that would be cancelled
        jobs_preview = "\n".join([
            f"• {job_name} (ID: {job_id}, Match: {match_reason})"
            for job_id, job_name, identifier, match_reason in all_jobs_to_cancel
        ])
        
        # Return the dry run results
        return {
            "success": True,
            "message": f"Found {len(all_jobs_to_cancel)} jobs matching contract address {contract_address} on {service}/{node}:\n{jobs_preview}",
            "jobs": all_jobs_to_cancel,
            "service": service,
            "node": node,
            "api": api,
        }
    
    def execute_deletion(self, api: ChainlinkAPI, jobs_to_cancel: List) -> Dict:
        """Execute job deletion after confirmation"""
        successful, failed = cancel_jobs(api, jobs_to_cancel)
        
        return {
            "success": successful > 0,
            "message": f"📊 Job Cancellation Results:\n• Successfully cancelled: {successful}\n• Failed to cancel: {failed}",
        }

# Initialize legacy job deleter
legacy_deleter = LegacyJobDeleter()


@app.message("")
def handle_message(message, say):
    """Handle incoming Slack messages"""
    text = message.get("text", "")
    user_id = message.get("user")
    
    # Check if user is authorized first
    if not validate_user(user_id):
        # Only respond if the message looks like a command
        if any(pattern in text.lower() for pattern in ["job", "bridge", "chainlink", "help"]):
            say("❌ You are not authorized to use Chainlink commands. Please contact an administrator.")
        return
    
    # 1. First try to parse as a structured command
    command = command_parser.detect_command(text)
    
    if command:
        # It's a structured command, parse arguments and execute
        args = command_parser.parse_arguments(command, text)
        
        if command == "help":
            # Special case for help command
            help_text = command_parser.get_help_text()
            say(help_text)
            return
            
        # SPECIAL HANDLING FOR BRIDGE COMMANDS WITH NATURAL LANGUAGE
        if command.startswith("bridge_") and "node" in args and "service" in args:
            # Check for natural language bridge commands with the "on node service" pattern
            natural_language_pattern = re.search(r'on\s+(\w+)\s+(\w+)', text, re.IGNORECASE)
            
            if natural_language_pattern and command == "bridge_list":
                # Direct implementation for bridge list command
                logger.info(f"Using direct implementation for natural language bridge list")
                
                try:
                    # Get the node and service from the args
                    node = args["node"]
                    service = args["service"]
                    
                    # Load configuration
                    config = load_node_config()
                    if not config or "services" not in config or service not in config["services"] or node not in config["services"][service]:
                        say(f"❌ Configuration not found for {service}/{node}")
                        return
                        
                    node_config = config["services"][service][node]
                    node_url = node_config.get("url")
                    password_index = node_config.get("password", 0)
                    
                    if not node_url:
                        say(f"❌ URL not found for {service}/{node}")
                        return
                        
                    # Get password
                    password = os.environ.get(f"PASSWORD_{password_index}")
                    if not password:
                        say(f"❌ Password not available for {service}/{node}")
                        return
                        
                    # Initialize ChainlinkAPI
                    from core.chainlink_api import ChainlinkAPI
                    api = ChainlinkAPI(node_url, os.environ.get("EMAIL"), password)
                    
                    # Authenticate
                    if not api.authenticate():
                        say(f"❌ Authentication failed for {service}/{node}")
                        return
                        
                    # Get bridges
                    from commands.bridge_cmd import get_all_bridges
                    bridges = get_all_bridges(api)
                    
                    if not bridges:
                        say("❌ No bridges found")
                        return
                        
                    # Sort bridges alphabetically by name
                    sorted_bridges = sorted(bridges, key=lambda b: b.get("name", "").lower())
                    
                    # Determine the maximum name length for proper spacing
                    max_name_length = max([len(bridge.get("name", "")) for bridge in sorted_bridges], default=30)
                    # Add padding and ensure it's at least 30 characters
                    column_width = max(max_name_length + 4, 30)
                    
                    # Format the output
                    output = f"🔍 Listing bridges on {service.upper()} {node.upper()} ({api.node_url})\n\n"
                    output += f"📋 Found {len(bridges)} bridges:\n"
                    output += "-" * (column_width + 40) + "\n"  # Adjust separator length
                    output += f"{'Name':{column_width}} URL\n"
                    output += "-" * (column_width + 40) + "\n"  # Adjust separator length
                    
                    for bridge in sorted_bridges:
                        name = bridge.get("name", "N/A")
                        url = bridge.get("url", "N/A")
                        output += f"{name:{column_width}} {url}\n"
                        
                    # Send the formatted output
                    say(f"```\n{output}\n```")
                    return
                    
                except Exception as e:
                    logger.exception(f"Error in direct bridge list implementation: {e}")
                    say(f"❌ Error listing bridges: {str(e)}")
                    return
        
        # DEBUGGING
        logger.info(f"About to execute command: {command} with args: {args}")
        
        # Execute the command
        success, message_text = command_executor.execute_command(command, args)
        
        # DEBUGGING
        logger.info(f"Command execution result: success={success}, message_length={len(message_text) if message_text else 0}")
        
        say(message_text)
        return
    
    # 2. If not a structured command, try to parse as a legacy deletion request
    parsed_request = legacy_deleter.parse_deletion_request(text)
    if not parsed_request:
        # Not a recognized command, ignore
        return
    
    # Process the legacy deletion request (dry run)
    results = legacy_deleter.process_deletion_request(parsed_request, user_id)
    
    if not results["success"]:
        say(results["message"])
        return
    
    # Ask for confirmation with button for legacy deletion
    say({
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Job Deletion Request*\n\n{results['message']}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Confirm Deletion"
                        },
                        "style": "danger",
                        "value": json.dumps({
                            "action": "confirm_deletion",
                            "service": results["service"],
                            "node": results["node"],
                            "jobs": [(job_id, job_name, identifier, match_reason) 
                                    for job_id, job_name, identifier, match_reason in results["jobs"]]
                        }),
                        "confirm": {
                            "title": {
                                "type": "plain_text",
                                "text": "Confirm Job Deletion"
                            },
                            "text": {
                                "type": "plain_text",
                                "text": "Are you sure you want to delete these jobs? This action cannot be undone."
                            },
                            "confirm": {
                                "type": "plain_text",
                                "text": "Yes, Delete Jobs"
                            },
                            "deny": {
                                "type": "plain_text",
                                "text": "Cancel"
                            }
                        },
                        "action_id": "confirm_deletion"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Cancel"
                        },
                        "value": "cancel",
                        "action_id": "cancel_deletion"
                    }
                ]
            }
        ]
    })


@app.action("confirm_deletion")
def handle_deletion_confirmation(ack, body, say):
    """Handle confirmation of job deletion"""
    ack()
    
    user_id = body["user"]["id"]
    if not validate_user(user_id):
        say("❌ You are not authorized to delete jobs. Please contact an administrator.")
        return
    
    try:
        # Parse the value from the button
        value = json.loads(body["actions"][0]["value"])
        service = value["service"]
        node = value["node"]
        jobs_to_cancel = [(job_id, job_name, identifier, match_reason) 
                         for job_id, job_name, identifier, match_reason in value["jobs"]]
        
        # Initialize API again (the stored instance might be expired)
        config = load_node_config()
        email = os.environ.get("EMAIL")
        passwords = {
            i: os.environ.get(f"PASSWORD_{i}") 
            for i in range(10) 
            if os.environ.get(f"PASSWORD_{i}")
        }
        
        node_config = config["services"][service][node]
        password_index = node_config.get("password", 0)
        password = passwords.get(password_index)
        node_url = node_config.get("url")
        
        api = ChainlinkAPI(node_url, email, password)
        if not api.authenticate():
            say("❌ Failed to authenticate with node for deletion. Please try again.")
            return
            
        # Execute the deletion
        results = legacy_deleter.execute_deletion(api, jobs_to_cancel)
        say(results["message"])
        
    except Exception as e:
        logger.exception("Error executing job deletion")
        say(f"❌ Error executing job deletion: {str(e)}")


@app.action("cancel_deletion")
def handle_deletion_cancellation(ack, say):
    """Handle cancellation of job deletion"""
    ack()
    say("✅ Job deletion cancelled.")


if __name__ == "__main__":
    logger.info("Starting Chainlink Slack Job Manager")
    
    try:
        # Check if app token is set for Socket Mode
        app_token = os.environ.get("SLACK_APP_TOKEN")
        if app_token and app_token.startswith("xapp-"):
            # Use Socket Mode
            handler = SocketModeHandler(app, app_token)
            logger.info("Starting Slack app using Socket Mode")
            handler.start()
        else:
            # Use HTTP
            port = int(os.environ.get("PORT", 3000))
            logger.info(f"Starting Slack app on port {port}")
            app.start(port=port)
    except Exception as e:
        logger.exception("Error starting Slack app")
        print(f"Error starting Slack app: {e}")