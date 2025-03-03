#!/usr/bin/env python3
import os
import json
import argparse
from core.chainlink_api import ChainlinkAPI
from utils.helpers import load_config, confirm_action
from utils.bridge_ops import (
    get_bridges, 
    get_bridge,
    create_bridge, 
    delete_bridge,
    batch_process_bridges
)

def register_arguments(subparsers):
    """
    Register the bridge command arguments
    
    Parameters:
    - subparsers: Subparsers object from argparse
    """
    parser = subparsers.add_parser('bridge', help='Manage Chainlink bridges')
    
    # Create subcommands for different bridge operations
    bridge_subparsers = parser.add_subparsers(dest='bridge_command', help='Bridge operation')
    
    # List bridges command
    list_parser = bridge_subparsers.add_parser('list', help='List bridges')
    list_parser.add_argument('--service', required=True, help='Service name (e.g., bootstrap, ocr)')
    list_parser.add_argument('--node', required=True, help='Node name (e.g., arbitrum, ethereum)')
    
    # Create bridge command
    create_parser = bridge_subparsers.add_parser('create', help='Create or update bridge')
    create_parser.add_argument('--service', required=True, help='Service name (e.g., bootstrap, ocr)')
    create_parser.add_argument('--node', required=True, help='Node name (e.g., arbitrum, ethereum)')
    create_parser.add_argument('--name', required=True, help='Bridge name')
    create_parser.add_argument('--url', required=True, help='Bridge URL')
    create_parser.add_argument('--payment', type=str, default="0", help='Minimum contract payment (default: 0)')
    create_parser.add_argument('--confirmations', type=int, default=0, help='Confirmations (default: 0)')
    
    # Delete bridge command
    delete_parser = bridge_subparsers.add_parser('delete', help='Delete a bridge')
    delete_parser.add_argument('--service', required=True, help='Service name (e.g., bootstrap, ocr)')
    delete_parser.add_argument('--node', required=True, help='Node name (e.g., arbitrum, ethereum)')
    delete_parser.add_argument('--name', required=True, help='Bridge name to delete')
    delete_parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    
    # Batch create bridges from bridge groups
    batch_parser = bridge_subparsers.add_parser('batch', help='Batch create bridges from bridge configuration')
    batch_parser.add_argument('--service', required=True, help='Service name (e.g., bootstrap, ocr)')
    batch_parser.add_argument('--node', required=True, help='Node name (e.g., arbitrum, ethereum)')
    batch_parser.add_argument('--group', help='Specific bridge group to use (overrides node\'s bridge groups from config)')
    batch_parser.add_argument('--bridges-config', default='cl_bridges.json', help='Path to bridges configuration file')
    batch_parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    
    # Batch delete bridges command (NEW)
    batch_delete_parser = bridge_subparsers.add_parser('batch-delete', help='Batch delete bridges from bridge groups')
    batch_delete_parser.add_argument('--service', required=True, help='Service name (e.g., bootstrap, ocr)')
    batch_delete_parser.add_argument('--node', required=True, help='Node name (e.g., arbitrum, ethereum)')
    batch_delete_parser.add_argument('--group', help='Specific bridge group to delete')
    batch_delete_parser.add_argument('--bridges-config', default='cl_bridges.json', help='Path to bridges configuration file')
    batch_delete_parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    batch_delete_parser.add_argument('--execute', action='store_true', help='Execute deletion (dry run if not specified)')
    
    return parser

def execute(args, chainlink_api=None):
    """
    Execute the bridge command
    
    Parameters:
    - args: Parsed arguments
    - chainlink_api: ChainlinkAPI instance (will be created if not provided)
    
    Returns:
    - True if successful, False otherwise
    """
    # Only initialize if no ChainlinkAPI instance was provided
    if not chainlink_api:
        # Load configuration
        config_result = load_config("cl_hosts.json", args.service, args.node)
        if not config_result:
            return False
            
        node_url, password_index = config_result
        
        # Initialize ChainlinkAPI
        chainlink_api = ChainlinkAPI(node_url, os.getenv("EMAIL"))
        
        # Get password
        password = os.getenv(f"PASSWORD_{password_index}")
        if not password:
            print(f"❌ Error: PASSWORD_{password_index} environment variable not set")
            return False
            
        # Authenticate
        if not chainlink_api.authenticate(password):
            print(f"❌ Authentication failed for {args.service.upper()} {args.node.upper()} ({node_url})")
            return False
    
    # Execute appropriate command
    if args.bridge_command == 'list':
        return list_bridges(args, chainlink_api)
    elif args.bridge_command == 'create':
        return create_bridge_command(args, chainlink_api)
    elif args.bridge_command == 'delete':
        return delete_bridge(args, chainlink_api)
    elif args.bridge_command == 'batch':
        return batch_create_bridges(args, chainlink_api)
    elif args.bridge_command == 'batch-delete':
        return batch_delete_bridges(args, chainlink_api)
    else:
        print(f"❌ Error: Unknown bridge command '{args.bridge_command}'")
        return False

def list_bridges(args, chainlink_api):
    """
    List bridges on a node using the desired format from screenshot
    """
    print(f"🔍 Listing bridges on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    bridges = get_all_bridges(chainlink_api)
    if not bridges:
        print("❌ No bridges found")
        return True
    
    # Sort bridges alphabetically by name
    sorted_bridges = sorted(bridges, key=lambda b: b.get("name", "").lower())
    
    # Determine the maximum name length for proper spacing
    max_name_length = max([len(bridge.get("name", "")) for bridge in sorted_bridges], default=30)
    # Add padding and ensure it's at least 30 characters
    column_width = max(max_name_length + 4, 30)
    
    # Use exact format from screenshot with dynamic width
    print(f"\n📋 Found {len(bridges)} bridges:")
    print("-" * (column_width + 40))  # Adjust separator length
    print(f"{'Name':{column_width}} URL")
    print("-" * (column_width + 40))  # Adjust separator length
    
    for bridge in sorted_bridges:
        name = bridge.get("name", "N/A")
        url = bridge.get("url", "N/A")
        print(f"{name:{column_width}} {url}")
    
    return True

def get_all_bridges(chainlink_api):
    """
    Get all bridges from the node (handling potential pagination)
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - List of all bridges or empty list on error
    """
    try:
        all_bridges = []
        page = 1
        page_size = 100  # Adjust as needed
        
        while True:
            # Fetch one page of bridges
            url = f"{chainlink_api.node_url}/v2/bridge_types?page={page}&size={page_size}"
            response = chainlink_api.session.get(url, verify=False)
            
            if response.status_code != 200:
                print(f"❌ Error: Failed to get bridges, status code: {response.status_code}")
                return all_bridges if all_bridges else []
            
            data = response.json()
            bridges_data = data.get("data", [])
            
            # Extract bridge attributes
            for item in bridges_data:
                all_bridges.append(item.get("attributes", {}))
            
            # Check if we've reached the last page
            if len(bridges_data) < page_size:
                break
                
            page += 1
        
        return all_bridges
    except Exception as e:
        print(f"❌ Exception when getting bridges: {e}")
        return []

def create_bridge_command(args, chainlink_api):
    """
    Create or update a bridge (command handler version)
    
    Parameters:
    - args: Parsed arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - True if successful, False otherwise
    """
    print(f"🔍 Creating/updating bridge '{args.name}' on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    # Check if bridge exists
    existing_bridge = get_bridge(chainlink_api, args.name)
    
    bridge_data = {
        "name": args.name,
        "url": args.url,
        "minimumContractPayment": args.payment,
        "confirmations": args.confirmations
    }
    
    if existing_bridge:
        print(f"📋 Found existing bridge '{args.name}' with URL: {existing_bridge.get('url')}")
        
        # Check if update is needed
        if existing_bridge.get('url') != args.url:
            print(f"🔄 Updating bridge URL from '{existing_bridge.get('url')}' to '{args.url}'")
            
            result = update_bridge(chainlink_api, args.name, bridge_data)
            if result:
                print(f"✅ Bridge '{args.name}' updated successfully")
            else:
                print(f"❌ Failed to update bridge '{args.name}'")
                return False
        else:
            print(f"✅ Bridge already exists with correct URL")
    else:
        print(f"📋 Bridge '{args.name}' does not exist, creating new bridge")
        
        result = create_new_bridge(chainlink_api, bridge_data)
        if result:
            print(f"✅ Bridge '{args.name}' created successfully")
        else:
            print(f"❌ Failed to create bridge '{args.name}'")
            return False
    
    return True

def delete_bridge(args, chainlink_api):
    """
    Delete a bridge by name
    
    Parameters:
    - args: Parsed arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - True if successful, False otherwise
    """
    print(f"🔍 Deleting bridge '{args.name}' from {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    # Check if bridge exists
    existing_bridge = get_bridge(chainlink_api, args.name)
    
    if not existing_bridge:
        print(f"❌ Bridge '{args.name}' does not exist")
        return False
    
    print(f"📋 Found bridge '{args.name}' with URL: {existing_bridge.get('url')}")
    print(f"🗑️ Proceeding with deletion...")
    
    try:
        response = chainlink_api.session.delete(
            f"{chainlink_api.node_url}/v2/bridge_types/{args.name}",
            verify=False
        )
        
        if response.status_code == 200:
            print(f"✅ Bridge '{args.name}' deleted successfully")
            return True
        else:
            print(f"❌ Failed to delete bridge '{args.name}', status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception when deleting bridge '{args.name}': {e}")
        return False

def batch_create_bridges(args, chainlink_api):
    """
    Batch create bridges from bridge configuration
    
    Parameters:
    - args: Parsed arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - True if successful, False otherwise
    """
    print(f"🔍 Batch creating bridges on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    # Load bridges configuration
    bridges_config = load_bridges_config(args.bridges_config)
    if not bridges_config:
        print(f"❌ Error: Failed to load bridges configuration from {args.bridges_config}")
        return False
    
    # Check if bridges are defined in the config
    if not bridges_config.get("bridges"):
        print(f"❌ Error: No bridges defined in {args.bridges_config}")
        return False
    
    # Get the bridge group(s)
    groups_to_process = []
    
    # If a specific group was provided as argument, only use that one
    if args.group:
        groups_to_process = [args.group]
        print(f"🔍 Using specified bridge group: {args.group}")
    else:
        # Otherwise, get bridge_groups from node configuration
        node_config = load_node_config()
        if node_config and args.service in node_config and args.node in node_config[args.service]:
            node_settings = node_config[args.service][args.node]
            
            # Check for both singular and plural keys
            if "bridge_group" in node_settings:
                groups_to_process = [node_settings["bridge_group"]]
            elif "bridge_groups" in node_settings:
                groups_to_process = node_settings["bridge_groups"]
                
    # If no groups found, show available groups and exit
    if not groups_to_process:
        print(f"❌ Error: No bridge_group specified for {args.service}/{args.node} in config and no --group provided")
        
        # List available bridge groups from config file
        if bridges_config.get("bridges"):
            print("\nAvailable bridge groups in config:")
            for group in bridges_config["bridges"].keys():
                print(f"  - {group}")
            print("\nUse --group <group_name> to specify a bridge group")
        return False
    
    # Validate that all groups exist in the bridges config
    invalid_groups = [g for g in groups_to_process if g not in bridges_config["bridges"]]
    if invalid_groups:
        print(f"❌ Error: The following bridge groups were not found in bridges configuration: {', '.join(invalid_groups)}")
        print("\nAvailable bridge groups:")
        for group in bridges_config["bridges"].keys():
            print(f"  - {group}")
        return False
    
    print(f"🔍 Processing {len(groups_to_process)} bridge groups: {', '.join(groups_to_process)}")
    
    # Track overall statistics
    total_processed = 0
    total_success = 0
    total_failure = 0
    
    # Process each bridge group
    for bridge_group in groups_to_process:
        # Get bridges for the group
        bridges = bridges_config["bridges"].get(bridge_group, {})
        if not bridges:
            print(f"⚠️ Warning: No bridges defined for group '{bridge_group}', skipping")
            continue
        
        print(f"\n📋 Processing group '{bridge_group}' with {len(bridges)} bridges:")
        
        # Process each bridge in this group
        group_success = 0
        group_failure = 0
        
        for bridge_name, bridge_url in bridges.items():
            bridge_data = {
                "name": bridge_name,
                "url": bridge_url,
                "minimumContractPayment": "0",
                "confirmations": 0
            }
            
            if process_bridge(chainlink_api, bridge_data):
                group_success += 1
            else:
                group_failure += 1
                
        # Update totals
        total_processed += len(bridges)
        total_success += group_success
        total_failure += group_failure
        
        # Print group summary
        print(f"\n  Group '{bridge_group}' Summary:")
        print(f"    Bridges processed: {len(bridges)}")
        print(f"    Successfully created/updated: {group_success}")
        print(f"    Failed: {group_failure}")
    
    # Print overall summary
    print("\n" + "=" * 60)
    print(f"📊 Overall Bridge Creation Summary:")
    print(f"  Total bridges processed: {total_processed}")
    print(f"  Successfully created/updated: {total_success}")
    print(f"  Failed: {total_failure}")
    print(f"  Groups processed: {len(groups_to_process)}")
    
    return total_failure == 0

def load_bridges_config(config_file):
    """
    Load bridges configuration from JSON file
    
    Parameters:
    - config_file: Path to bridges configuration file
    
    Returns:
    - Dictionary with bridges configuration or None if loading failed
    """
    try:
        with open(config_file, "r") as file:
            config = json.load(file)
        return config
    except Exception as e:
        print(f"❌ Error loading bridges configuration: {e}")
        return None

def process_bridge(chainlink_api, bridge_data):
    """
    Process a single bridge (create or update)
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - bridge_data: Bridge data dictionary
    
    Returns:
    - True if successful, False otherwise
    """
    name = bridge_data.get("name")
    url = bridge_data.get("url")
    
    # Check if bridge exists
    existing_bridge = get_bridge(chainlink_api, name)
    
    if existing_bridge:
        # Check if update is needed
        if existing_bridge.get("url") != url:
            print(f"  🔄 Updating bridge '{name}' URL from '{existing_bridge.get('url')}' to '{url}'")
            if update_bridge(chainlink_api, name, bridge_data):
                print(f"  ✅ Bridge '{name}' updated successfully")
                return True
            else:
                print(f"  ❌ Failed to update bridge '{name}'")
                return False
        else:
            print(f"  ✅ Bridge '{name}' already exists with correct URL")
            return True
    else:
        print(f"  📋 Bridge '{name}' does not exist, creating new bridge")
        if create_new_bridge(chainlink_api, bridge_data):
            print(f"  ✅ Bridge '{name}' created successfully")
            return True
        else:
            print(f"  ❌ Failed to create bridge '{name}'")
            return False

def get_bridges(chainlink_api):
    """
    Get all bridges from the node
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - List of bridges or empty list on error
    """
    try:
        response = chainlink_api.session.get(
            f"{chainlink_api.node_url}/v2/bridge_types",
            verify=False
        )
        
        if response.status_code == 200:
            data = response.json()
            bridges = []
            for item in data.get("data", []):
                bridges.append(item.get("attributes", {}))
            return bridges
        else:
            print(f"❌ Error: Failed to get bridges, status code: {response.status_code}")
            return []
    except Exception as e:
        print(f"❌ Exception when getting bridges: {e}")
        return []

def get_bridge(chainlink_api, bridge_name):
    """
    Get a specific bridge by name
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - bridge_name: Name of the bridge
    
    Returns:
    - Bridge data or None if not found or error
    """
    try:
        response = chainlink_api.session.get(
            f"{chainlink_api.node_url}/v2/bridge_types/{bridge_name}",
            verify=False
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("data", {}).get("attributes", {})
        elif response.status_code == 404:
            return None
        else:
            print(f"❌ Error: Failed to get bridge '{bridge_name}', status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"❌ Exception when getting bridge '{bridge_name}': {e}")
        return None

def create_new_bridge(chainlink_api, bridge_data):
    """
    Create a new bridge
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - bridge_data: Bridge data dictionary
    
    Returns:
    - True if successful, False otherwise
    """
    try:
        response = chainlink_api.session.post(
            f"{chainlink_api.node_url}/v2/bridge_types",
            json=bridge_data,
            verify=False
        )
        
        if response.status_code in [200, 201]:
            return True
        else:
            print(f"❌ Error: Failed to create bridge, status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception when creating bridge: {e}")
        return False

def update_bridge(chainlink_api, bridge_name, bridge_data):
    """
    Update an existing bridge
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - bridge_name: Name of the bridge
    - bridge_data: Bridge data dictionary
    
    Returns:
    - True if successful, False otherwise
    """
    try:
        response = chainlink_api.session.patch(
            f"{chainlink_api.node_url}/v2/bridge_types/{bridge_name}",
            json=bridge_data,
            verify=False
        )
        
        if response.status_code == 200:
            return True
        else:
            print(f"❌ Error: Failed to update bridge '{bridge_name}', status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception when updating bridge '{bridge_name}': {e}")
        return False

def create_bridge(chainlink_api, name, url, confirmations=0, min_payment=0):
    """
    Create or update a bridge
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - name: Name of the bridge
    - url: URL of the bridge adapter
    - confirmations: Number of confirmations
    - min_payment: Minimum contract payment
    
    Returns:
    - Boolean indicating success or failure
    """
    try:
        bridge_data = {
            "name": name,
            "url": url,
            "confirmations": confirmations,
            "minimumContractPayment": str(min_payment)
        }
        
        response = chainlink_api.session.post(
            f"{chainlink_api.node_url}/v2/bridge_types",
            json=bridge_data,
            verify=False
        )
        
        if response.status_code in [200, 201]:
            print(f"✅ Bridge '{name}' created/updated successfully")
            return True
        else:
            print(f"❌ Failed to create/update bridge '{name}', status code: {response.status_code}")
            print(f"Response: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Exception when creating/updating bridge '{name}': {e}")
        return False

def batch_process_bridges(chainlink_api, service, node, config_file="cl_hosts.json", bridges_config_file="cl_bridges.json"):
    """
    Process bridges in batch based on configuration files
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - service: Service name (e.g., bootstrap, ocr)
    - node: Node name (e.g., arbitrum, ethereum)
    - config_file: Path to config file
    - bridges_config_file: Path to bridges configuration file
    
    Returns:
    - Tuple of (successful_count, failed_count)
    """
    try:
        # Load node configuration to get bridge groups
        with open(config_file, "r") as file:
            node_config_data = json.load(file)
        
        # Get bridge group for node
        bridge_groups = []
        try:
            node_config = node_config_data["services"][service][node]
            
            # Check for bridge_groups array first, fall back to single bridge_group
            if "bridge_groups" in node_config:
                bridge_groups = node_config["bridge_groups"]
                print(f"Using multiple bridge groups from node config: {bridge_groups}")
            elif "bridge_group" in node_config:
                bridge_groups = [node_config["bridge_group"]]
                print(f"Using single bridge group from node config: {bridge_groups[0]}")
            else:
                print(f"❌ No bridge_group or bridge_groups specified for {service}/{node} in config")
                return 0, 0
        except KeyError:
            print(f"❌ Service '{service}' or node '{node}' not found in {config_file}")
            return 0, 0
            
        # Load bridges configuration
        with open(bridges_config_file, "r") as file:
            bridges_config = json.load(file)
        
        # Build a consolidated mapping of bridges from all configured groups
        consolidated_bridges = {}
        for group in bridge_groups:
            if group not in bridges_config.get("bridges", {}):
                print(f"⚠️ Bridge group '{group}' not found in bridges configuration, skipping")
                continue
                
            # Add bridges from this group to the consolidated mapping
            group_bridges = bridges_config["bridges"][group]
            consolidated_bridges.update(group_bridges)
        
        if not consolidated_bridges:
            print(f"❌ No valid bridge groups found for {service}/{node}")
            return 0, 0
            
        # Get existing bridges to avoid unnecessary updates
        existing_bridges = get_bridges(chainlink_api)
        existing_bridge_names = {bridge["name"]: bridge for bridge in existing_bridges}
        
        successful = 0
        failed = 0
        
        # Process each bridge
        print(f"Processing {len(consolidated_bridges)} bridges from configuration...")
        
        for bridge_name, bridge_url in consolidated_bridges.items():
            # Skip if bridge already exists with same URL
            if bridge_name in existing_bridge_names and existing_bridge_names[bridge_name]["url"] == bridge_url:
                print(f"ℹ️ Bridge '{bridge_name}' already exists with correct URL, skipping")
                successful += 1
                continue
                
            print(f"Creating/updating bridge '{bridge_name}' with URL '{bridge_url}'")
            if create_bridge(chainlink_api, bridge_name, bridge_url):
                successful += 1
            else:
                failed += 1
                
        return successful, failed
    except Exception as e:
        print(f"❌ Exception during batch processing: {e}")
        return 0, 0

def load_node_config():
    """
    Load node configuration from cl_hosts.json
    
    Returns:
    - Dictionary with node configuration or None if error
    """
    try:
        with open("cl_hosts.json", "r") as file:
            config = json.load(file)
            
        # Return the services section of the config
        return config.get("services", {})
    except Exception as e:
        print(f"❌ Error loading node configuration: {e}")
        return None

def batch_delete_bridges(args, chainlink_api):
    """
    Batch delete bridges from bridge configuration groups
    
    Parameters:
    - args: Parsed arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - True if successful, False otherwise
    """
    print(f"🔍 Batch deleting bridges on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    # Load bridges configuration
    bridges_config = load_bridges_config(args.bridges_config)
    if not bridges_config:
        print(f"❌ Error: Failed to load bridges configuration from {args.bridges_config}")
        return False
    
    # Check if bridges are defined in the config
    if not bridges_config.get("bridges"):
        print(f"❌ Error: No bridges defined in {args.bridges_config}")
        return False
    
    # Get the bridge group(s) to delete
    groups_to_process = []
    
    # If a specific group was provided as argument, only use that one
    if args.group:
        groups_to_process = [args.group]
        print(f"🔍 Using specified bridge group: {args.group}")
    else:
        # Otherwise, get bridge_groups from node configuration
        node_config = load_node_config()
        if node_config and args.service in node_config and args.node in node_config[args.service]:
            node_settings = node_config[args.service][args.node]
            
            # Check for both singular and plural keys
            if "bridge_group" in node_settings:
                groups_to_process = [node_settings["bridge_group"]]
            elif "bridge_groups" in node_settings:
                groups_to_process = node_settings["bridge_groups"]
                
    # If no groups found, show available groups and exit
    if not groups_to_process:
        print(f"❌ Error: No bridge_group specified for {args.service}/{args.node} in config and no --group provided")
        
        # List available bridge groups from config file
        if bridges_config.get("bridges"):
            print("\nAvailable bridge groups in config:")
            for group in bridges_config["bridges"].keys():
                print(f"  - {group}")
            print("\nUse --group <group_name> to specify a bridge group to delete")
        return False
    
    # Validate that all groups exist in the bridges config
    invalid_groups = [g for g in groups_to_process if g not in bridges_config["bridges"]]
    if invalid_groups:
        print(f"❌ Error: The following bridge groups were not found in bridges configuration: {', '.join(invalid_groups)}")
        print("\nAvailable bridge groups:")
        for group in bridges_config["bridges"].keys():
            print(f"  - {group}")
        return False
    
    # Get a list of all bridges on the node
    existing_bridges = get_all_bridges(chainlink_api)
    existing_bridge_names = {bridge.get("name", ""): bridge for bridge in existing_bridges}
    
    # Collect all bridges that would be deleted
    bridges_to_delete = {}
    
    for bridge_group in groups_to_process:
        group_bridges = bridges_config["bridges"].get(bridge_group, {})
        for bridge_name in group_bridges.keys():
            if bridge_name in existing_bridge_names:
                bridges_to_delete[bridge_name] = existing_bridge_names[bridge_name].get("url", "N/A")
    
    # Show what will be deleted
    if not bridges_to_delete:
        print(f"✅ No bridges found to delete from groups: {', '.join(groups_to_process)}")
        return True
    
    print(f"\n🗑️ Found {len(bridges_to_delete)} bridges to delete from {len(groups_to_process)} groups:")
    for name, url in bridges_to_delete.items():
        print(f"  - {name}: {url}")
    
    # Check if this is a dry run
    if not args.execute:
        print("\n⚠️ DRY RUN - No bridges will be deleted")
        print("🔍 Use --execute to perform the actual deletion")
        return True
    
    # Delete the bridges
    print(f"\n🗑️ Deleting {len(bridges_to_delete)} bridges...")
    
    success_count = 0
    failure_count = 0
    
    for bridge_name in bridges_to_delete.keys():
        print(f"  🗑️ Deleting bridge '{bridge_name}'...")
        try:
            response = chainlink_api.session.delete(
                f"{chainlink_api.node_url}/v2/bridge_types/{bridge_name}",
                verify=False
            )
            
            if response.status_code == 200:
                print(f"  ✅ Bridge '{bridge_name}' deleted successfully")
                success_count += 1
            else:
                print(f"  ❌ Failed to delete bridge '{bridge_name}', status code: {response.status_code}")
                failure_count += 1
        except Exception as e:
            print(f"  ❌ Exception when deleting bridge '{bridge_name}': {e}")
            failure_count += 1
    
    # Print summary
    print("\n" + "=" * 60)
    print(f"📊 Bridge Deletion Summary:")
    print(f"  Total bridges processed: {len(bridges_to_delete)}")
    print(f"  Successfully deleted: {success_count}")
    print(f"  Failed: {failure_count}")
    print(f"  Groups processed: {len(groups_to_process)}")
    
    return failure_count == 0