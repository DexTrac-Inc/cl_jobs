#!/usr/bin/env python3
import os
import sys
import io
import contextlib
import importlib
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

# Add parent directory to path for imports
parent_dir = str(Path(__file__).resolve().parent.parent)
sys.path.append(parent_dir)

from core.chainlink_api import ChainlinkAPI
from utils.helpers import load_node_config, setup_logging
from commands.list_cmd import execute as execute_list
from commands.cancel_cmd import execute as execute_cancel
from commands.reapprove_cmd import execute as execute_reapprove
from commands.bridge_cmd import execute as execute_bridge

# Configure logger
logger = logging.getLogger("ChainlinkJobManager.command_executor")


class CommandExecutor:
    """Execute job manager commands from parsed arguments"""
    
    def __init__(self):
        self.config = load_node_config()
        self.email = os.environ.get("EMAIL")
        self.passwords = {
            i: os.environ.get(f"PASSWORD_{i}") 
            for i in range(10) 
            if os.environ.get(f"PASSWORD_{i}")
        }
    
    def _initialize_api(self, service: str, node: str) -> Optional[ChainlinkAPI]:
        """Initialize ChainlinkAPI for a given service and node"""
        if not self.config or "services" not in self.config:
            return None
            
        if service not in self.config["services"]:
            return None
            
        if node not in self.config["services"][service]:
            return None
            
        node_config = self.config["services"][service][node]
        node_url = node_config.get("url")
        
        if not node_url:
            return None
            
        password_index = node_config.get("password", 0)
        password = self.passwords.get(password_index)
        
        if not password:
            return None
            
        api = ChainlinkAPI(node_url, self.email, password)
        if not api.authenticate():
            return None
            
        return api
    
    def execute_bridge_list_command(self, args: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Execute the bridge list command directly using the API
        
        Args:
            args: Command arguments with service and node
            
        Returns:
            Tuple of (success, message)
        """
        # Initialize the API
        api = self._initialize_api(args["service"], args["node"])
        if not api:
            return False, f"Failed to connect to {args['service']}/{args['node']}"
            
        try:
            # Import the function directly
            from utils.bridge_ops import get_bridges
            
            # Get bridges directly from the API
            print(f"Getting bridges directly from API for {args['service']}/{args['node']}")
            bridges = get_bridges(api, log_to_console=False)
            
            if not bridges:
                return True, "❌ No bridges found"
            
            # Sort bridges alphabetically by name
            sorted_bridges = sorted(bridges, key=lambda b: b.get("name", "").lower())
            
            # Determine the maximum name length for proper spacing
            max_name_length = max([len(bridge.get("name", "")) for bridge in sorted_bridges], default=30)
            # Add padding and ensure it's at least 30 characters
            column_width = max(max_name_length + 4, 30)
            
            # Format the output with bridges information
            output = f"🔍 Listing bridges on {args['service'].upper()} {args['node'].upper()} ({api.node_url})\n\n"
            output += f"📋 Found {len(bridges)} bridges:\n"
            output += "-" * (column_width + 40) + "\n"  # Adjust separator length
            output += f"{'Name':{column_width}} URL\n"
            output += "-" * (column_width + 40) + "\n"  # Adjust separator length
            
            for bridge in sorted_bridges:
                name = bridge.get("name", "N/A")
                url = bridge.get("url", "N/A")
                output += f"{name:{column_width}} {url}\n"
                
            return True, f"```\n{output}\n```"
        except Exception as e:
            print(f"Error listing bridges: {e}")
            return False, f"❌ Error listing bridges: {str(e)}"
            
    def execute_command(self, command: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Execute a job manager command
        
        Args:
            command: Command name
            args: Command arguments
            
        Returns:
            Tuple of (success, message)
        """
        print(f"Executing command: {command} with args: {args}")
        
        # Special handling for bridge list command which is prone to parsing issues
        if command == "bridge_list" and "service" in args and "node" in args:
            print(f"Using direct API access for bridge_list command")
            return self.execute_bridge_list_command(args)
        
        # Check for required arguments
        if command not in ["help"]:
            # Most commands require service and node
            if "service" not in args or "node" not in args:
                print(f"Missing required arguments. Command: {command}, Args: {args}")
                return False, "Missing required arguments. Service and node are required."
        
        # Capture stdout to return as message
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            try:
                # List command
                if command == "list":
                    # Convert arguments to the expected format
                    api = self._initialize_api(args["service"], args["node"])
                    if not api:
                        return False, f"Failed to connect to {args['service']}/{args['node']}"
                    
                    # Create args object as expected by list_cmd
                    class Args:
                        pass
                    
                    cmd_args = Args()
                    cmd_args.service = args["service"]
                    cmd_args.node = args["node"]
                    cmd_args.status = args.get("status")
                    cmd_args.has_updates = args.get("has_updates", False)
                    cmd_args.sort = args.get("sort", "name")
                    cmd_args.reverse = args.get("reverse", False)
                    cmd_args.full_width = False
                    cmd_args.format = "table"
                    cmd_args.output = None
                    
                    success = execute_list(cmd_args, api)
                    
                # Cancel command
                elif command == "cancel":
                    api = self._initialize_api(args["service"], args["node"])
                    if not api:
                        return False, f"Failed to connect to {args['service']}/{args['node']}"
                    
                    # Create args object as expected by cancel_cmd
                    class Args:
                        pass
                    
                    cmd_args = Args()
                    cmd_args.service = args["service"]
                    cmd_args.node = args["node"]
                    cmd_args.name_pattern = args.get("name_pattern")
                    
                    # Special handling for contract addresses in job cancellation
                    # This addresses an issue where the standard get_jobs_to_cancel function
                    # might not match addresses correctly in all cases
                    if "address" in args or "feed_ids" in args:
                        # Create a custom name pattern that explicitly targets the contract address format
                        # This is more reliable than the default substring matching
                        address = args.get("address")
                        if address:
                            # Create a name pattern that matches "contract <address>" format
                            # The \s+contract\s+ pattern captures the common format in job names
                            cmd_args.name_pattern = f"contract {address}"
                            logger.info(f"Using custom name pattern for address: {cmd_args.name_pattern}")
                        
                        # Also set feed_ids to maintain compatibility with the original logic
                        if "address" in args:
                            cmd_args.feed_ids = [args["address"]]
                        elif "feed_ids" in args:
                            if isinstance(args["feed_ids"], list):
                                cmd_args.feed_ids = args["feed_ids"]
                            else:
                                # Handle case where feed_ids might be a single string
                                cmd_args.feed_ids = [args["feed_ids"]]
                    else:
                        cmd_args.feed_ids = None
                    
                    cmd_args.feed_ids_file = None
                    cmd_args.execute = args.get("execute", True)  # Default to execute for Slack
                    cmd_args.yes = True  # Auto-confirm for Slack interface for better UX
                    
                    # Handle job_id if provided
                    if "job_id" in args:
                        cmd_args.job_id = args["job_id"]
                        # When job_id is specified, don't use feed_ids to avoid conflicts
                        if cmd_args.feed_ids and not cmd_args.name_pattern:
                            logger.info("Both job_id and feed_ids specified, using job_id for cancellation")
                            cmd_args.feed_ids = None
                    
                    # Debug logging to help diagnose issues
                    if cmd_args.feed_ids:
                        logger.info(f"Cancelling with feed_ids: {cmd_args.feed_ids}")
                    if cmd_args.name_pattern:
                        logger.info(f"Cancelling with name_pattern: {cmd_args.name_pattern}")
                    if hasattr(cmd_args, 'job_id') and cmd_args.job_id:
                        logger.info(f"Cancelling with job_id: {cmd_args.job_id}")
                    
                    success = execute_cancel(cmd_args, api)
                    
                # Reapprove command
                elif command == "reapprove":
                    api = self._initialize_api(args["service"], args["node"])
                    if not api:
                        return False, f"Failed to connect to {args['service']}/{args['node']}"
                    
                    # Create args object as expected by reapprove_cmd
                    class Args:
                        pass
                    
                    cmd_args = Args()
                    cmd_args.service = args["service"]
                    cmd_args.node = args["node"]
                    
                    # Special handling for addresses in job reapproval, similar to cancel
                    if "address" in args or "feed_ids" in args:
                        # Use a name pattern that specifically targets contract addresses in job names
                        address = args.get("address")
                        if address:
                            # Create a name pattern that matches the "contract <address>" format
                            cmd_args.name_pattern = f"contract {address}"
                            logger.info(f"Using custom name pattern for address: {cmd_args.name_pattern}")
                        
                        # Also set feed_ids to maintain compatibility with the original logic
                        if "address" in args:
                            cmd_args.feed_ids = [args["address"]]
                        elif "feed_ids" in args:
                            if isinstance(args["feed_ids"], list):
                                cmd_args.feed_ids = args["feed_ids"]
                            else:
                                # Handle case where feed_ids might be a single string
                                cmd_args.feed_ids = [args["feed_ids"]]
                    else:
                        cmd_args.feed_ids = None
                        
                    cmd_args.feed_ids_file = None
                    # Only override name_pattern if not already set
                    if not cmd_args.name_pattern:
                        cmd_args.name_pattern = args.get("name_pattern")
                    cmd_args.force = args.get("force", False)
                    cmd_args.execute = args.get("execute", True)  # Default to execute for Slack
                    
                    # Debug logging
                    if cmd_args.feed_ids:
                        logger.info(f"Reapproving with feed_ids: {cmd_args.feed_ids}")
                    if cmd_args.name_pattern:
                        logger.info(f"Reapproving with name_pattern: {cmd_args.name_pattern}")
                    
                    success = execute_reapprove(cmd_args, api)
                    
                # Bridge commands
                elif command.startswith("bridge_"):
                    api = self._initialize_api(args["service"], args["node"])
                    if not api:
                        return False, f"Failed to connect to {args['service']}/{args['node']}"
                    
                    # Create args object as expected by bridge_cmd
                    class Args:
                        pass
                    
                    cmd_args = Args()
                    cmd_args.service = args["service"]
                    cmd_args.node = args["node"]
                    cmd_args.config = "cl_hosts.json"  # Default config file
                    cmd_args.bridges_config = "cl_bridges.json"  # Default bridges config
                    
                    # Skip the bridge_list command since we're handling it separately
                    if command == "bridge_create":
                        if not args.get("name") or not args.get("url"):
                            return False, "Bridge creation requires both name and URL parameters"
                        
                        # There's a mismatch in the bridge_cmd.py create_bridge function
                        # It has two different implementations with different parameter orders
                        # We need to adapt to how it's actually called in execute()
                        cmd_args.bridge_command = "create"
                        cmd_args.name = args.get("name")
                        cmd_args.url = args.get("url")
                        # These are needed for the create_bridge function
                        cmd_args.confirmations = args.get("confirmations", 0)
                        cmd_args.min_payment = args.get("min_payment", 0)
                        
                    elif command == "bridge_update":
                        if not args.get("name") or not args.get("url"):
                            return False, "Bridge update requires both name and URL parameters"
                        cmd_args.bridge_command = "update"
                        cmd_args.name = args.get("name")
                        cmd_args.url = args.get("url")
                        
                    elif command == "bridge_delete":
                        if not args.get("name"):
                            return False, "Bridge deletion requires a name parameter"
                        cmd_args.bridge_command = "delete"
                        cmd_args.name = args.get("name")
                        cmd_args.execute = True
                    
                    # Add any additional bridge-specific arguments
                    cmd_args.group = args.get("group")
                    cmd_args.batch = args.get("batch", False)
                    
                    try:
                        # Special handling for create bridge command
                        if command == "bridge_create":
                            # The command execution is unusual - create_bridge is called directly
                            # with specific parameter order, not through the Args object
                            bridge_name = args.get("name")
                            bridge_url = args.get("url")
                            confirmations = args.get("confirmations", 0)
                            min_payment = args.get("min_payment", 0)
                            
                            # Clean up URL if it contains Slack formatting
                            if bridge_url:
                                # Handle Slack piped URLs like https://example.com|example.com
                                if '|' in bridge_url:
                                    bridge_url = bridge_url.split('|')[0]
                                
                                # Handle Slack angle bracket URLs like <https://example.com>
                                if bridge_url.startswith('<') and bridge_url.endswith('>'):
                                    bridge_url = bridge_url[1:-1]
                            
                            if not bridge_name or not bridge_url:
                                return False, "Bridge creation requires both name and URL parameters"
                                
                            # Use the direct bridge_ops create_bridge function which gives us more control
                            from utils.bridge_ops import create_bridge as create_bridge_function
                            
                            # Log what we're doing with full details
                            logger.info(f"Creating bridge '{bridge_name}' on {args['service'].upper()} {args['node'].upper()} with URL {bridge_url}")
                            
                            # First check if this bridge already exists
                            from utils.bridge_ops import get_bridge
                            existing_bridge = get_bridge(api, bridge_name)
                            if existing_bridge:
                                logger.info(f"Bridge '{bridge_name}' already exists with URL: {existing_bridge.get('url')}")
                                if existing_bridge.get('url') != bridge_url:
                                    logger.info(f"Updating URL from '{existing_bridge.get('url')}' to '{bridge_url}'")
                                else:
                                    return True, f"✅ Bridge '{bridge_name}' already exists with URL {bridge_url}"
                            
                            # Call the API directly instead of through command execution
                            success = create_bridge_function(
                                api, 
                                bridge_name,  # Pass the explicit bridge name
                                bridge_url, 
                                confirmations, 
                                min_payment,
                                log_to_console=True
                            )
                        elif command != "bridge_list":  # Skip bridge_list completely
                            # Normal execution for other bridge commands (except bridge_list which is handled directly)
                            logger.info(f"Using standard execute_bridge for command: {command}")
                            success = execute_bridge(cmd_args, api)
                    except AttributeError as e:
                        # Handle cases where a required attribute is missing
                        error_msg = str(e)
                        if "'Args' object has no attribute" in error_msg:
                            missing_attr = error_msg.split("'")[-2]
                            return False, f"Missing required parameter: {missing_attr}"
                        raise e
                    
                else:
                    return False, f"Unknown command: {command}"
                    
            except AttributeError as e:
                # Handle missing attribute errors gracefully
                error_msg = str(e)
                if "'Args' object has no attribute" in error_msg:
                    missing_attr = error_msg.split("'")[-2]
                    return False, f"Missing required parameter: {missing_attr}. Try adding --{missing_attr} to your command."
                return False, f"Error executing command: {str(e)}"
            except ValueError as e:
                # Handle value errors gracefully
                return False, f"Invalid value in command: {str(e)}"
            except Exception as e:
                # Log the full exception for debugging
                import traceback
                logger.error(f"Exception executing command: {command}")
                logger.error(traceback.format_exc())
                return False, f"Error executing command: {str(e)}"
                
        # Get the captured output
        output_text = output.getvalue()
        
        # Format the response for Slack (limit message size)
        if len(output_text) > 3000:
            output_text = output_text[:3000] + "...\n(output truncated due to length)"
            
        return True, f"```\n{output_text}\n```"