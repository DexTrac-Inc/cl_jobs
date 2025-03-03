#!/usr/bin/env python3
import os
import sys
import io
import contextlib
import importlib
import json
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

# Add parent directory to path for imports
parent_dir = str(Path(__file__).resolve().parent.parent)
sys.path.append(parent_dir)

from core.chainlink_api import ChainlinkAPI
from utils.helpers import load_node_config
from commands.list_cmd import execute as execute_list
from commands.cancel_cmd import execute as execute_cancel
from commands.reapprove_cmd import execute as execute_reapprove
from commands.bridge_cmd import execute as execute_bridge


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
    
    def execute_command(self, command: str, args: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Execute a job manager command
        
        Args:
            command: Command name
            args: Command arguments
            
        Returns:
            Tuple of (success, message)
        """
        # Check for required arguments
        if command not in ["help"]:
            # Most commands require service and node
            if "service" not in args or "node" not in args:
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
                    cmd_args.feed_ids = [args["address"]] if "address" in args else None
                    cmd_args.feed_ids_file = None
                    cmd_args.execute = True  # Always execute (preview will be shown first)
                    cmd_args.yes = False  # Require confirmation
                    
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
                    cmd_args.feed_ids = [args["address"]] if "address" in args else None
                    cmd_args.feed_ids_file = None
                    cmd_args.execute = True
                    
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
                    
                    if command == "bridge_list":
                        cmd_args.bridge_command = "list"
                        
                    elif command == "bridge_create":
                        cmd_args.bridge_command = "create"
                        cmd_args.name = args.get("name")
                        cmd_args.url = args.get("url")
                        
                    elif command == "bridge_update":
                        cmd_args.bridge_command = "update"
                        cmd_args.name = args.get("name")
                        cmd_args.url = args.get("url")
                        
                    elif command == "bridge_delete":
                        cmd_args.bridge_command = "delete"
                        cmd_args.name = args.get("name")
                        cmd_args.execute = True
                    
                    success = execute_bridge(cmd_args, api)
                    
                else:
                    return False, f"Unknown command: {command}"
                    
            except Exception as e:
                return False, f"Error executing command: {str(e)}"
                
        # Get the captured output
        output_text = output.getvalue()
        
        # Format the response for Slack (limit message size)
        if len(output_text) > 3000:
            output_text = output_text[:3000] + "...\n(output truncated due to length)"
            
        return True, f"```\n{output_text}\n```"