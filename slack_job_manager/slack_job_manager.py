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
    
    # DIRECT NATURAL LANGUAGE COMMANDS - completely bypass the command parser
    # Check for specific patterns first
    
    # Cancel/reapprove jobs with multiple addresses
    cancel_reapprove_match = re.search(r'(cancel|reapprove|delete)\s+jobs\s+((?:0x[a-fA-F0-9]{40}(?:\s+|,\s*)?)+)(?:on\s+(\w+)\s+(\w+))?', text, re.IGNORECASE)
    if cancel_reapprove_match:
        action = cancel_reapprove_match.group(1).lower()
        addresses_str = cancel_reapprove_match.group(2)
        node = cancel_reapprove_match.group(3)
        service = cancel_reapprove_match.group(4)
        
        # Extract multiple addresses from the string
        # This handles both space-separated and comma-separated formats
        addresses = re.findall(r'0x[a-fA-F0-9]{40}', addresses_str)
        logger.info(f"Detected {action} command with {len(addresses)} addresses: {addresses}")
        
        if not node or not service:
            # Try to find the network and service in the rest of the text
            network_match = re.search(r'on\s+(\w+)\s+(\w+)', text, re.IGNORECASE)
            if network_match:
                node = network_match.group(1)
                service = network_match.group(2)
            else:
                say(f"❌ Please specify node and service (e.g., '{action} jobs {addresses[0]} on tron ocr')")
                return
        
        # Handle both "cancel" and "delete" as cancellation actions
        if action == "cancel" or action == "delete":
            handle_direct_job_cancel(addresses, node, service, say)
        else:  # reapprove
            handle_direct_job_reapprove(addresses, node, service, say)
        return
    
    # List jobs command with optional status filter
    list_jobs_match = re.search(r'list\s+(?:(\w+)\s+)?jobs\s+on\s+(\w+)\s+(\w+)', text, re.IGNORECASE)
    if list_jobs_match:
        logger.info(f"Detected natural language job list command directly")
        status_filter = list_jobs_match.group(1)
        node = list_jobs_match.group(2)
        service = list_jobs_match.group(3)
        
        # Convert common status words to API values
        if status_filter:
            if status_filter.lower() in ['approved', 'active', 'running']:
                status_filter = 'APPROVED'
            elif status_filter.lower() in ['cancelled', 'canceled', 'stopped', 'disabled']:
                status_filter = 'CANCELLED'
            elif status_filter.lower() in ['pending', 'waiting']:
                status_filter = 'PENDING'
                
        handle_direct_job_list(node, service, say, status_filter)
        return
    
    # List bridges command
    list_bridges_match = re.search(r'list\s+bridges\s+on\s+(\w+)\s+(\w+)', text, re.IGNORECASE)
    if list_bridges_match:
        logger.info(f"Detected natural language bridge list command directly")
        node = list_bridges_match.group(1)
        service = list_bridges_match.group(2)
        handle_direct_bridge_list(node, service, say)
        return
        
    delete_bridge_match = re.search(r'delete\s+bridge\s+([a-zA-Z0-9_-]+)\s+on\s+(\w+)\s+(\w+)', text, re.IGNORECASE)
    if delete_bridge_match:
        logger.info(f"Detected natural language bridge delete command directly")
        bridge_name = delete_bridge_match.group(1)
        node = delete_bridge_match.group(2)
        service = delete_bridge_match.group(3)
        handle_direct_bridge_delete(bridge_name, node, service, say)
        return
        
    create_bridge_match = re.search(r'create\s+bridge\s+on\s+(\w+)\s+(\w+)\s+with\s+name\s+([a-zA-Z0-9_-]+)\s+and\s+url\s+<?([^>\s]+)>?', text, re.IGNORECASE)
    if create_bridge_match:
        logger.info(f"Detected natural language bridge create command directly")
        node = create_bridge_match.group(1)
        service = create_bridge_match.group(2)
        bridge_name = create_bridge_match.group(3)
        bridge_url = create_bridge_match.group(4)
        
        # Clean URL
        if bridge_url.startswith('<') and bridge_url.endswith('>'):
            bridge_url = bridge_url[1:-1]
        if '|' in bridge_url:
            bridge_url = bridge_url.split('|')[0]
            
        handle_direct_bridge_create(bridge_name, bridge_url, node, service, say)
        return
    
    # 1. If no direct natural language match, try to parse as a structured command
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
            logger.info(f"Checking for natural language bridge command: {command}, {text}")
            
            # Check for natural language bridge pattern in text
            if "on" in text.lower() and re.search(r'\b(tron|ocr|bootstrap|ethereum|polygon|arbitrum|optimism|base|avax|bsc)\b', text, re.IGNORECASE):
                logger.info(f"Detected natural language bridge command '{command}' with node/service")
                
                # Direct implementation for each bridge command type
                if command == "bridge_list":
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
                            
                        # Break the output into chunks if it's too long for Slack
                        # Slack has a message size limit of about 4000 characters
                        # Split by lines first to avoid breaking rows between messages
                        lines = output.split('\n')
                        
                        chunks = []
                        current_chunk = []
                        current_size = 0
                        max_chunk_size = 3800
                        
                        # Determine where the header ends (usually after the table separator line)
                        header_end = 0
                        for i, line in enumerate(lines):
                            if "-" * 10 in line:  # Find the second separator line
                                header_end = i + 2  # Include the line after the separator
                                break
                        
                        # Add headers to first chunk
                        header_lines = lines[:header_end]  # Header lines
                        header_text = '\n'.join(header_lines)
                        current_chunk.append(header_text)
                        current_size = len(header_text)
                        
                        # Process the data rows (everything after headers)
                        for line in lines[header_end:]:
                            line_length = len(line) + 1  # +1 for the newline character
                            
                            # If adding this line would exceed the limit, start a new chunk
                            if current_size + line_length > max_chunk_size:
                                # Save current chunk
                                chunks.append('\n'.join(current_chunk))
                                
                                # Start a new chunk with the headers
                                current_chunk = []
                                current_chunk.append(header_text)
                                current_size = len(header_text)
                            
                            # Add the line to the current chunk
                            current_chunk.append(line)
                            current_size += line_length
                        
                        # Add the last chunk if it has content
                        if current_chunk:
                            chunks.append('\n'.join(current_chunk))
                        
                        # Send each chunk as a separate message
                        for i, chunk in enumerate(chunks):
                            if len(chunks) > 1:
                                chunk_header = f"Part {i+1}/{len(chunks)}:\n"
                                say(f"```\n{chunk_header}{chunk}\n```")
                            else:
                                say(f"```\n{chunk}\n```")
                        return
                        
                    except Exception as e:
                        logger.exception(f"Error in direct bridge list implementation: {e}")
                        say(f"❌ Error listing bridges: {str(e)}")
                        return
                        
                elif command == "bridge_create" and "name" in args and "url" in args:
                    # Direct implementation for bridge create command
                    logger.info(f"Using direct implementation for natural language bridge create")
                
                try:
                    # Get parameters from the args
                    node = args["node"]
                    service = args["service"]
                    bridge_name = args["name"]
                    bridge_url = args["url"]
                    
                    # Handle URL formatting
                    if bridge_url.startswith('<') and bridge_url.endswith('>'):
                        bridge_url = bridge_url[1:-1]
                    if '|' in bridge_url:
                        bridge_url = bridge_url.split('|')[0]
                    
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
                        
                    # Check if bridge exists
                    from commands.bridge_cmd import get_bridge
                    existing_bridge = get_bridge(api, bridge_name)
                    
                    # Create bridge data
                    bridge_data = {
                        "name": bridge_name,
                        "url": bridge_url,
                        "minimumContractPayment": "0",
                        "confirmations": 0
                    }
                    
                    if existing_bridge:
                        # Check if update is needed
                        if existing_bridge.get('url') != bridge_url:
                            # Update bridge
                            response = api.session.patch(
                                f"{api.node_url}/v2/bridge_types/{bridge_name}",
                                json=bridge_data,
                                verify=False
                            )
                            
                            if response.status_code == 200:
                                say(f"✅ Bridge '{bridge_name}' updated successfully from {existing_bridge.get('url')} to {bridge_url}")
                            else:
                                say(f"❌ Failed to update bridge '{bridge_name}', status code: {response.status_code}\nResponse: {response.text}")
                        else:
                            say(f"✅ Bridge '{bridge_name}' already exists with correct URL: {bridge_url}")
                    else:
                        # Create bridge
                        response = api.session.post(
                            f"{api.node_url}/v2/bridge_types",
                            json=bridge_data,
                            verify=False
                        )
                        
                        if response.status_code in [200, 201]:
                            say(f"✅ Bridge '{bridge_name}' created successfully with URL: {bridge_url}")
                        else:
                            say(f"❌ Failed to create bridge '{bridge_name}', status code: {response.status_code}\nResponse: {response.text}")
                    
                    return
                    
                except Exception as e:
                    logger.exception(f"Error in direct bridge create implementation: {e}")
                    say(f"❌ Error creating bridge: {str(e)}")
                    return
                    
            elif command == "bridge_delete" and "name" in args:
                # Direct implementation for bridge delete command
                logger.info(f"Using direct implementation for natural language bridge delete")
                
                try:
                    # Get parameters from the args
                    node = args["node"]
                    service = args["service"]
                    bridge_name = args["name"]
                    
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
                        
                    # Check if bridge exists
                    from commands.bridge_cmd import get_bridge
                    existing_bridge = get_bridge(api, bridge_name)
                    
                    if not existing_bridge:
                        say(f"❌ Bridge '{bridge_name}' does not exist")
                        return
                    
                    # Delete bridge
                    response = api.session.delete(
                        f"{api.node_url}/v2/bridge_types/{bridge_name}",
                        verify=False
                    )
                    
                    if response.status_code == 200:
                        say(f"✅ Bridge '{bridge_name}' deleted successfully")
                    else:
                        say(f"❌ Failed to delete bridge '{bridge_name}', status code: {response.status_code}\nResponse: {response.text}")
                    
                    return
                    
                except Exception as e:
                    logger.exception(f"Error in direct bridge delete implementation: {e}")
                    say(f"❌ Error deleting bridge: {str(e)}")
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


# Direct handlers for natural language bridge commands
def get_chainlink_api(node, service, say):
    """Initialize ChainlinkAPI for the specified node and service"""
    try:
        # Load configuration
        config = load_node_config()
        if not config or "services" not in config or service not in config["services"] or node not in config["services"][service]:
            say(f"❌ Configuration not found for {service}/{node}")
            return None
            
        node_config = config["services"][service][node]
        node_url = node_config.get("url")
        password_index = node_config.get("password", 0)
        
        if not node_url:
            say(f"❌ URL not found for {service}/{node}")
            return None
            
        # Get password
        password = os.environ.get(f"PASSWORD_{password_index}")
        if not password:
            say(f"❌ Password not available for {service}/{node}")
            return None
            
        # Initialize ChainlinkAPI
        from core.chainlink_api import ChainlinkAPI
        api = ChainlinkAPI(node_url, os.environ.get("EMAIL"), password)
        
        # Authenticate
        if not api.authenticate():
            say(f"❌ Authentication failed for {service}/{node}")
            return None
            
        return api
    except Exception as e:
        logger.exception(f"Error initializing ChainlinkAPI: {e}")
        say(f"❌ Error connecting to node: {str(e)}")
        return None

def handle_direct_bridge_list(node, service, say):
    """Handle direct bridge list command"""
    try:
        # Initialize API
        api = get_chainlink_api(node, service, say)
        if not api:
            return
            
        # Start with detailed log output
        status_info = f"✅ Authentication successful for {api.node_url}\n"
        status_info += f"🔍 Listing bridges on {service.upper()} {node.upper()} ({api.node_url})\n"
        
        # Get bridges
        from commands.bridge_cmd import get_all_bridges
        bridges = get_all_bridges(api)
        
        if not bridges:
            status_info += "❌ No bridges found"
            say(f"```\n{status_info}\n```")
            return
            
        # Sort bridges alphabetically by name
        sorted_bridges = sorted(bridges, key=lambda b: b.get("name", "").lower())
        
        # Determine the maximum name length for proper spacing
        max_name_length = max([len(bridge.get("name", "")) for bridge in sorted_bridges], default=30)
        # Add padding and ensure it's at least 30 characters
        column_width = max(max_name_length + 4, 30)
        
        # Add the bridge count to status info
        status_info += f"\n📋 Found {len(bridges)} bridges:\n"
        
        # Create the table header
        table_header = "-" * (column_width + 40) + "\n"  # Separator line
        table_header += f"{'Name':{column_width}} URL\n"
        table_header += "-" * (column_width + 40) + "\n"  # Separator line
        
        # Create table rows
        table_rows = []
        for bridge in sorted_bridges:
            name = bridge.get("name", "N/A")
            url = bridge.get("url", "N/A")
            table_rows.append(f"{name:{column_width}} {url}")
        
        # Break the output into chunks for Slack (max ~4000 chars)
        max_chunk_size = 3800
        chunks = []
        
        # First chunk includes status info and table header
        current_chunk = [status_info]
        current_chunk.append(table_header)
        current_size = len(status_info) + len(table_header)
        
        for row in table_rows:
            row_length = len(row) + 1  # +1 for newline
            
            # If adding this row would exceed the limit, start a new chunk
            if current_size + row_length > max_chunk_size:
                # Save current chunk
                chunks.append('\n'.join(current_chunk))
                
                # Start a new chunk with ONLY the table header (no status info)
                current_chunk = [table_header]
                current_size = len(table_header)
            
            # Add the row to the current chunk
            current_chunk.append(row)
            current_size += row_length
        
        # Add the last chunk if it has content
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        # Send each chunk as a separate message
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                chunk_header = f"Part {i+1}/{len(chunks)}:\n"
                say(f"```\n{chunk_header}{chunk}\n```")
            else:
                say(f"```\n{chunk}\n```")
    except Exception as e:
        logger.exception(f"Error listing bridges: {e}")
        say(f"❌ Error listing bridges: {str(e)}")

def handle_direct_bridge_delete(bridge_name, node, service, say):
    """Handle direct bridge delete command"""
    try:
        # Initialize API
        api = get_chainlink_api(node, service, say)
        if not api:
            return
            
        # Start with detailed log output
        output = f"✅ Authentication successful for {api.node_url}\n"
        output += f"🔍 Deleting bridge '{bridge_name}' from {service.upper()} {node.upper()} ({api.node_url})\n"
            
        # Check if bridge exists
        from commands.bridge_cmd import get_bridge
        existing_bridge = get_bridge(api, bridge_name)
        
        if not existing_bridge:
            output += f"❌ Bridge '{bridge_name}' does not exist"
            say(f"```\n{output}\n```")
            return
        
        output += f"📋 Found bridge '{bridge_name}' with URL: {existing_bridge.get('url')}\n"
        output += f"🗑️ Proceeding with deletion...\n"
        
        # Delete bridge
        response = api.session.delete(
            f"{api.node_url}/v2/bridge_types/{bridge_name}",
            verify=False
        )
        
        if response.status_code == 200:
            output += f"✅ Bridge '{bridge_name}' deleted successfully"
        else:
            output += f"❌ Failed to delete bridge '{bridge_name}', status code: {response.status_code}\nResponse: {response.text}"
            
        # Send the formatted output
        say(f"```\n{output}\n```")
    except Exception as e:
        logger.exception(f"Error deleting bridge: {e}")
        say(f"❌ Error deleting bridge: {str(e)}")

def handle_direct_job_list(node, service, say, status_filter=None):
    """Handle direct job list command with optional status filtering"""
    try:
        # Initialize API
        api = get_chainlink_api(node, service, say)
        if not api:
            return
            
        # Start with detailed log output but using plain text instead of emoji
        # to avoid formatting issues in Slack
        output = f"Authentication successful for {api.node_url}\n"
        if status_filter:
            output += f"Listing {status_filter.lower()} jobs on {service.upper()} {node.upper()} ({api.node_url})\n"
        else:
            output += f"Listing all jobs on {service.upper()} {node.upper()} ({api.node_url})\n"
        
        # Get all feeds managers
        feeds_managers = api.get_all_feeds_managers()
        if not feeds_managers:
            output += "No feeds managers found"
            say(f"```\n{output}\n```")
            return
            
        # Get all jobs from all feeds managers
        all_jobs = []
        for fm in feeds_managers:
            jobs = api.fetch_jobs(fm["id"])
            for job in jobs:
                # Add feeds manager name to job for reference
                job["feeds_manager"] = fm.get("name", "Unknown")
                all_jobs.append(job)
                
        if not all_jobs:
            output += "No jobs found"
            say(f"```\n{output}\n```")
            return
            
        # Filter jobs by status if requested
        if status_filter:
            filtered_jobs = [j for j in all_jobs if j.get("status") == status_filter]
        else:
            filtered_jobs = all_jobs
            
        # Sort jobs by name (default)
        sorted_jobs = sorted(filtered_jobs, key=lambda j: j.get("name", "").lower())
        
        # Count job statuses
        approved_count = sum(1 for j in filtered_jobs if j.get("status") == "APPROVED")
        pending_count = sum(1 for j in filtered_jobs if j.get("status") == "PENDING")
        cancelled_count = sum(1 for j in filtered_jobs if j.get("status") == "CANCELLED")
        total = len(filtered_jobs)
        
        # Add summary at the top (without emoji to avoid formatting issues)
        if status_filter:
            output += f"\nFound {total} {status_filter.lower()} jobs:\n"
        else:
            output += f"\nFound {total} jobs ({approved_count} approved, {pending_count} pending, {cancelled_count} cancelled):\n"
        
        # Determine column widths based on content
        name_width = max([len(j.get("name", "")) for j in sorted_jobs] + [4], default=30)
        name_width = max(name_width + 4, 35)  # Ensure minimum width
        id_width = 10
        status_width = 12
        update_width = 10
        
        # Table header
        output += "-" * (name_width + id_width + status_width + update_width + 10) + "\n"
        output += f"{'Name':{name_width}} {'ID':{id_width}} {'Status':{status_width}} {'Updates':{update_width}}\n"
        output += "-" * (name_width + id_width + status_width + update_width + 10) + "\n"
        
        # Table content
        for job in sorted_jobs:
            name = job.get("name", "N/A")
            job_id = job.get("id", "N/A")
            status = job.get("status", "N/A")
            has_updates = "Yes" if job.get("pendingUpdate") else "No"
            
            # Use plaintext status to avoid formatting issues in Slack
            status_str = status
            
            output += f"{name:{name_width}} {job_id:{id_width}} {status_str:{status_width}} {has_updates:{update_width}}\n"
            
            # For debugging - add contract address if it can be extracted from the name
            # import re
            # contract_match = re.search(r"contract\s+(0x[a-fA-F0-9]{40})", name)
            # if contract_match:
            #    output += f"  Contract: {contract_match.group(1)}\n"
        
        # Break the output into chunks if it's too long for Slack
        # Slack has a message size limit of about 4000 characters
        # Split by lines first to avoid breaking rows between messages
        lines = output.split('\n')
        
        # Determine where the header ends (usually after the table separator line)
        header_end = 0
        for i, line in enumerate(lines):
            if "-" * 10 in line:  # Find the second separator line
                header_end = i + 2  # Include the line after the separator
                break
                
        chunks = []
        current_chunk = []
        current_size = 0
        max_chunk_size = 3800
        
        # Add headers to first chunk
        header_lines = lines[:header_end]  # Header lines
        header_text = '\n'.join(header_lines)
        current_chunk.append(header_text)
        current_size = len(header_text)
        
        # Process the data rows (everything after headers)
        for line in lines[header_end:]:
            line_length = len(line) + 1  # +1 for the newline character
            
            # If adding this line would exceed the limit, start a new chunk
            if current_size + line_length > max_chunk_size:
                # Save current chunk
                chunks.append('\n'.join(current_chunk))
                
                # Start a new chunk with the headers
                current_chunk = []
                current_chunk.append(header_text)
                current_size = len(header_text)
            
            # Add the line to the current chunk
            current_chunk.append(line)
            current_size += line_length
        
        # Add the last chunk if it has content
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        # Send each chunk as a separate message
        for i, chunk in enumerate(chunks):
            if len(chunks) > 1:
                chunk_header = f"Part {i+1}/{len(chunks)}:\n"
                say(f"```\n{chunk_header}{chunk}\n```")
            else:
                say(f"```\n{chunk}\n```")
    except Exception as e:
        logger.exception(f"Error listing jobs: {e}")
        say(f"❌ Error listing jobs: {str(e)}")

def handle_direct_job_cancel(addresses, node, service, say):
    """Handle direct job cancellation command with multiple addresses"""
    try:
        # Initialize API
        api = get_chainlink_api(node, service, say)
        if not api:
            return
            
        # Start with detailed log output
        output = f"🔍 Cancelling jobs on {service.upper()} {node.upper()} ({api.node_url})\n"
        
        # Make patterns for each address - case insensitive matching
        patterns = []
        feed_ids = []
        for address in addresses:
            # Create pattern to match in job names
            patterns.append(f"contract {address.lower()}")
            feed_ids.append(address)
            
        output += f"🔍 Using {len(feed_ids)} feed IDs and {len(patterns)} pattern(s): "
        output += ", ".join(patterns) + " for job matching\n\n"
        
        # Get all feeds managers
        feeds_managers = api.get_all_feeds_managers()
        if not feeds_managers:
            output += "❌ No feeds managers found"
            say(f"```\n{output}\n```")
            return
            
        # Keep track of all jobs to cancel across all feeds managers
        all_jobs_to_cancel = []
        
        # Find matching jobs
        for fm in feeds_managers:
            output += f"📋 Processing feeds manager: {fm.get('name', 'Unknown')}\n\n"
            
            jobs = api.fetch_jobs(fm["id"])
            
            # Find jobs matching the criteria
            from commands.cancel_cmd import get_jobs_to_cancel
            jobs_to_cancel, matched_feed_ids, matched_patterns = get_jobs_to_cancel(
                jobs, feed_ids, patterns, None
            )
            
            all_jobs_to_cancel.extend(jobs_to_cancel)
        
        if not all_jobs_to_cancel:
            output += "❌ No jobs found matching the specified criteria"
            say(f"```\n{output}\n```")
            return
            
        # Display jobs that will be cancelled
        output += f"📋 Found {len(all_jobs_to_cancel)} jobs to cancel:\n"
        output += "-" * 80 + "\n"
        output += f"{'Spec ID':<15} {'Name':<30} {'Status':<20} {'Feeds Manager':<15}\n"
        output += "-" * 80 + "\n"
        
        for job_id, job_name, identifier, match_reason in all_jobs_to_cancel:
            # Truncate long job names
            if len(job_name) > 27:
                job_name = job_name[:24] + "..."
                
            # Extract status - assume it's part of the identifier
            status = "N/A"
            if isinstance(identifier, dict) and "status" in identifier:
                status = identifier["status"]
                
            # Get feeds manager name
            fm_name = "N/A"
            for fm in feeds_managers:
                # Check if the job is in this FM
                for fm_job in api.fetch_jobs(fm["id"]):
                    if fm_job.get("id") == job_id:
                        fm_name = fm.get("name", "N/A")
                        if len(fm_name) > 12:
                            fm_name = fm_name[:9] + "..."
                        break
                    
            output += f"{job_id:<15} {job_name:<30} {status:<20} {fm_name:<15}\n"
            
        # Cancel the jobs
        output += f"\n🔄 Cancelling jobs...\n"
        
        # Cancel each job with detailed logs
        successful = 0
        failed = 0
        
        for job_id, job_name, identifier, match_reason in all_jobs_to_cancel:
            try:
                output += f"⏳ Cancelling job ID: {job_id} ({job_name})\n"
                # Use the ChainlinkAPI directly to cancel the job
                if api.cancel_job(job_id):
                    output += f"✅ Cancelled job ID: {job_id}\n"
                    successful += 1
                else:
                    output += f"❌ Failed to cancel job ID: {job_id}\n"
                    failed += 1
            except Exception as e:
                output += f"❌ Exception when cancelling job {job_id}: {str(e)}\n"
                failed += 1
        
        # Show results
        output += f"\n{'='*60}\n"
        output += f"📊 Job Cancellation Summary:\n"
        output += f"  Total jobs processed: {len(all_jobs_to_cancel)}\n"
        output += f"  Successfully cancelled: {successful}\n"
        output += f"  Failed to cancel: {failed}\n"
        
        # Display the result
        say(f"```\n{output}\n```")
    except Exception as e:
        logger.exception(f"Error cancelling jobs: {e}")
        say(f"❌ Error cancelling jobs: {str(e)}")

def handle_direct_job_reapprove(addresses, node, service, say):
    """Handle direct job reapproval command with multiple addresses"""
    try:
        # Initialize API
        api = get_chainlink_api(node, service, say)
        if not api:
            return
            
        # Start with detailed log output
        output = f"🔍 Reapproving jobs on {service.upper()} {node.upper()} ({api.node_url})\n"
        
        # Make patterns for each address - case insensitive matching
        patterns = []
        feed_ids = []
        for address in addresses:
            # Create pattern to match in job names
            patterns.append(f"contract {address.lower()}")
            feed_ids.append(address)
            
        output += f"🔍 Using {len(feed_ids)} feed IDs and {len(patterns)} pattern(s): "
        output += ", ".join(patterns) + " for job matching\n\n"
        
        # Get all feeds managers
        feeds_managers = api.get_all_feeds_managers()
        if not feeds_managers:
            output += "❌ No feeds managers found"
            say(f"```\n{output}\n```")
            return
            
        # Keep track of all jobs to reapprove across all feeds managers
        all_jobs_to_reapprove = []
        all_matched_feed_ids = set()
        all_matched_patterns = set()
        
        # Find matching jobs
        for fm in feeds_managers:
            output += f"📋 Processing feeds manager: {fm.get('name', 'Unknown')}\n\n"
            
            jobs = api.fetch_jobs(fm["id"])
            
            # Find jobs matching the criteria
            from commands.reapprove_cmd import get_jobs_to_reapprove
            jobs_to_reapprove, matched_feed_ids, matched_patterns = get_jobs_to_reapprove(
                jobs, feed_ids, patterns, None
            )
            
            # Update our sets of matched IDs and patterns
            all_matched_feed_ids.update(matched_feed_ids)
            all_matched_patterns.update(matched_patterns)
            
            # Add feeds manager name to each job dictionary
            for job_dict in jobs_to_reapprove:
                job_dict['feeds_manager'] = fm.get('name', 'Unknown')
                
            all_jobs_to_reapprove.extend(jobs_to_reapprove)
        
        if not all_jobs_to_reapprove:
            output += "❌ No jobs found matching the specified criteria"
            say(f"```\n{output}\n```")
            return
            
        # Display jobs that will be reapproved
        output += f"📋 Found {len(all_jobs_to_reapprove)} jobs to reapprove:\n"
        output += "-" * 80 + "\n"
        output += f"{'Spec ID':<15} {'Name':<30} {'Status':<20} {'Feeds Manager':<15}\n"
        output += "-" * 80 + "\n"
        
        for job_dict in all_jobs_to_reapprove:
            spec_id = job_dict['spec_id']
            job_name = job_dict['name']
            status = job_dict['status']
            
            # Truncate long job names
            if len(job_name) > 27:
                job_name = job_name[:24] + "..."
                
            # Get feeds manager name
            fm_name = job_dict.get('feeds_manager', 'N/A')
            if len(fm_name) > 12:
                fm_name = fm_name[:9] + "..."
                    
            output += f"{spec_id:<15} {job_name:<30} {status:<20} {fm_name:<15}\n"
            
        # Reapprove the jobs
        output += f"\n🔄 Reapproving jobs...\n"
        
        # Reapprove each job directly since the reapprove_jobs function expects a specific format
        successful = 0
        failed = 0
        
        for job_dict in all_jobs_to_reapprove:
            try:
                output += f"⏳ Reapproving job spec ID: {job_dict['spec_id']} ({job_dict['name']})\n"
                # Use the ChainlinkAPI directly to approve the job
                if api.approve_job(job_dict['spec_id'], force=True):
                    output += f"✅ Reapproved job: {job_dict['name']}\n"
                    successful += 1
                else:
                    output += f"❌ Failed to reapprove job: {job_dict['name']}\n"
                    failed += 1
            except Exception as e:
                output += f"❌ Exception when approving job {job_dict['spec_id']}: {str(e)}\n"
                failed += 1
        
        # Show results
        output += f"\n{'='*60}\n"
        output += f"📊 Job Reapproval Summary:\n"
        output += f"  Total jobs processed: {len(all_jobs_to_reapprove)}\n"
        output += f"  Successfully reapproved: {successful}\n"
        output += f"  Failed to reapprove: {failed}\n"
        
        # Display the result
        say(f"```\n{output}\n```")
    except Exception as e:
        logger.exception(f"Error reapproving jobs: {e}")
        say(f"❌ Error reapproving jobs: {str(e)}")

def handle_direct_bridge_create(bridge_name, bridge_url, node, service, say):
    """Handle direct bridge create command"""
    try:
        # Initialize API
        api = get_chainlink_api(node, service, say)
        if not api:
            return
            
        # Start with detailed log output
        output = f"✅ Authentication successful for {api.node_url}\n"
        output += f"🔍 Creating/updating bridge '{bridge_name}' on {service.upper()} {node.upper()} ({api.node_url})\n"
        
        # Check if bridge exists
        from commands.bridge_cmd import get_bridge
        existing_bridge = get_bridge(api, bridge_name)
        
        # Create bridge data
        bridge_data = {
            "name": bridge_name,
            "url": bridge_url,
            "minimumContractPayment": "0",
            "confirmations": 0
        }
        
        if existing_bridge:
            output += f"📋 Found existing bridge '{bridge_name}' with URL: {existing_bridge.get('url')}\n"
            
            # Check if update is needed
            if existing_bridge.get('url') != bridge_url:
                output += f"🔄 Updating bridge URL from '{existing_bridge.get('url')}' to '{bridge_url}'\n"
                
                # Update bridge
                response = api.session.patch(
                    f"{api.node_url}/v2/bridge_types/{bridge_name}",
                    json=bridge_data,
                    verify=False
                )
                
                if response.status_code == 200:
                    output += f"✅ Bridge '{bridge_name}' updated successfully"
                else:
                    output += f"❌ Failed to update bridge '{bridge_name}', status code: {response.status_code}\nResponse: {response.text}"
            else:
                output += f"✅ Bridge already exists with correct URL"
        else:
            output += f"📋 Bridge '{bridge_name}' does not exist, creating new bridge\n"
            
            # Create bridge
            response = api.session.post(
                f"{api.node_url}/v2/bridge_types",
                json=bridge_data,
                verify=False
            )
            
            if response.status_code in [200, 201]:
                output += f"✅ Bridge '{bridge_name}' created successfully"
            else:
                output += f"❌ Failed to create bridge '{bridge_name}', status code: {response.status_code}\nResponse: {response.text}"
                
        # Send the formatted output
        say(f"```\n{output}\n```")
    except Exception as e:
        logger.exception(f"Error creating bridge: {e}")
        say(f"❌ Error creating bridge: {str(e)}")


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