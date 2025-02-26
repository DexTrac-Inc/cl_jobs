#!/usr/bin/env python3
"""
Chainlink Job Manager - A unified tool for managing Chainlink node jobs

This script provides functionality for:
- Listing jobs with filters and sorting options
- Cancelling jobs based on criteria
- Reapproving cancelled jobs

Example usage:
  # List all jobs on a node
  python cl_jobs_manager.py list --service bootstrap --node ethereum
  
  # Cancel jobs matching a pattern (dry run)
  python cl_jobs_manager.py cancel --service bootstrap --node ethereum --name-pattern "cron-capabilities"
  
  # Reapprove cancelled jobs (with execution)
  python cl_jobs_manager.py reapprove --service bootstrap --node ethereum --feed-ids-file feed_ids.txt --execute
"""

import os
import sys
import argparse
from dotenv import load_dotenv

# Import core modules
from core.chainlink_api import ChainlinkAPI
from utils.helpers import load_config

# Import command modules
from commands import list_cmd, cancel_cmd, reapprove_cmd

# Load environment variables
load_dotenv()

def main():
    """
    Main entry point for the Chainlink Job Manager
    """
    # Create the main parser
    parser = argparse.ArgumentParser(
        description='Chainlink Job Manager - Manage Chainlink node jobs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    # Add common arguments
    parser.add_argument('--config', default='cl_hosts.json', help='Path to config file (default: cl_hosts.json)')
    
    # Create subparsers for commands
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Register command arguments
    list_cmd.register_arguments(subparsers)
    cancel_cmd.register_arguments(subparsers)
    reapprove_cmd.register_arguments(subparsers)
    
    # Parse arguments
    args = parser.parse_args()
    
    # Check if a command was specified
    if not args.command:
        parser.print_help()
        return 1
    
    # Get required environment variables
    email = os.getenv("EMAIL")
    if not email:
        print("❌ Error: Missing required environment variable (EMAIL).")
        return 1
    
    # Load configuration for the specified service and node
    config = load_config(args.config, args.service, args.node)
    if not config:
        return 1
    
    node_url, password_index = config
    password = os.getenv(f"PASSWORD_{password_index}")
    
    if not password:
        print(f"❌ Error: Missing PASSWORD_{password_index} environment variable.")
        return 1
    
    # Initialize the API client
    chainlink_api = ChainlinkAPI(node_url, email, password)
    
    # Execute the requested command
    if args.command == 'list':
        success = list_cmd.execute(args, chainlink_api)
    elif args.command == 'cancel':
        success = cancel_cmd.execute(args, chainlink_api)
    elif args.command == 'reapprove':
        success = reapprove_cmd.execute(args, chainlink_api)
    else:
        print(f"❌ Error: Unknown command '{args.command}'")
        return 1
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())