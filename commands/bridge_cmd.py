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
    batch_parser.add_argument('--execute', action='store_true', help='Execute changes')
    
    return parser

def execute(args, chainlink_api):
    """
    Execute the bridge command
    
    Parameters:
    - args: Command line arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    """
    if args.bridge_command == "list":
        bridges = get_bridges(chainlink_api)
        
        if not bridges:
            print("No bridges found")
            return
            
        for bridge in bridges:
            print(f"🔗 {bridge['name']}: {bridge['url']}")
        
        print(f"Total bridges: {len(bridges)}")
        
    elif args.bridge_command == "create":
        create_bridge(
            chainlink_api, 
            args.name, 
            args.url, 
            args.confirmations, 
            args.payment
        )
        
    elif args.bridge_command == "delete":
        if not args.yes and not confirm_action(f"Delete bridge '{args.name}'?"):
            print("❌ Operation cancelled by user")
            return
            
        response = chainlink_api.session.delete(
            f"{chainlink_api.node_url}/v2/bridge_types/{args.name}",
            verify=False
        )
        
        if response.status_code == 200:
            print(f"✅ Bridge '{args.name}' deleted successfully")
        else:
            print(f"❌ Failed to delete bridge '{args.name}', status code: {response.status_code}")
            
    elif args.bridge_command == "batch":
        if not args.execute:
            print("\n⚠️ Dry run mode. No changes will be made.")
            print("💡 Run with --execute to actually create/update bridges.")
            return
            
        if not args.yes and not confirm_action("Create/update bridges based on configuration?"):
            print("❌ Operation cancelled by user")
            return
            
        successful, failed = batch_process_bridges(
            chainlink_api, 
            args.service, 
            args.node,
            bridges_config_file=args.bridges_config
        )
        
        print("=" * 60)
        print(f"Bridge batch processing complete: {successful} successful, {failed} failed")

def list_bridges(args, chainlink_api):
    """
    List bridges on a node
    
    Parameters:
    - args: Parsed arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - True if successful, False otherwise
    """
    print(f"🔍 Listing bridges on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    bridges = get_bridges(chainlink_api)
    if not bridges:
        print("✅ No bridges found")
        return True
    
    print(f"\n📋 Found {len(bridges)} bridges:")
    print("-" * 80)
    print("{:<30} {:<50}".format("Name", "URL"))
    print("-" * 80)
    
    for bridge in bridges:
        name = bridge.get("name", "N/A")
        url = bridge.get("url", "N/A")
        print("{:<30} {:<50}".format(name, url))
    
    return True

def create_bridge(args, chainlink_api):
    """
    Create or update a bridge
    
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
    Batch create bridges from bridge configuration groups
    
    Parameters:
    - args: Parsed arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - True if successful, False otherwise
    """
    print(f"🔍 Batch creating bridges on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    # Load bridge configuration
    bridges_config = load_bridges_config(args.bridges_config)
    if not bridges_config:
        print(f"❌ Error: Failed to load bridges configuration from '{args.bridges_config}'")
        return False
    
    # Determine which bridge group to use
    bridge_group = None
    
    # If group is specified in command line, use that
    if args.group:
        bridge_group = args.group
        print(f"📋 Using specified bridge group: {bridge_group}")
    else:
        # Otherwise, get bridge_group from node configuration
        try:
            with open(args.config, "r") as file:
                config_data = json.load(file)
                
            node_config = config_data["services"][args.service][args.node]
            if "bridge_group" in node_config:
                bridge_group = node_config["bridge_group"]
                print(f"📋 Using bridge group from node config: {bridge_group}")
            else:
                print(f"❌ Error: No bridge_group specified for {args.service}/{args.node} in config and no --group provided")
                return False
                
        except Exception as e:
            print(f"❌ Error loading node configuration: {e}")
            return False
    
    # Check if group exists in bridges config
    if bridge_group not in bridges_config.get("bridges", {}):
        print(f"❌ Error: Bridge group '{bridge_group}' not found in bridges configuration")
        return False
    
    # Get bridges for this group
    bridges = bridges_config["bridges"][bridge_group]
    if not bridges:
        print(f"❌ Error: No bridges defined in group '{bridge_group}'")
        return False
    
    print(f"📋 Found {len(bridges)} bridges in group '{bridge_group}'")
    
    # Process each bridge
    success_count = 0
    failure_count = 0
    
    for bridge_name, bridge_url in bridges.items():
        bridge_data = {
            "name": bridge_name,
            "url": bridge_url,
            "minimumContractPayment": "0",
            "confirmations": 0
        }
        
        if process_bridge(chainlink_api, bridge_data):
            success_count += 1
        else:
            failure_count += 1
    
    # Print summary
    print("\n" + "=" * 60)
    print(f"📊 Bridge Creation Summary:")
    print(f"  Total bridges processed: {len(bridges)}")
    print(f"  Successfully created/updated: {success_count}")
    print(f"  Failed: {failure_count}")
    
    return failure_count == 0

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
    bridge_name = bridge_data["name"]
    bridge_url = bridge_data["url"]
    
    print(f"  Processing bridge: {bridge_name} -> {bridge_url}")
    
    # Check if bridge exists
    existing_bridge = get_bridge(chainlink_api, bridge_name)
    
    if existing_bridge:
        # Check if update is needed
        if existing_bridge.get('url') != bridge_url:
            print(f"  🔄 Updating bridge URL from '{existing_bridge.get('url')}' to '{bridge_url}'")
            
            result = update_bridge(chainlink_api, bridge_name, bridge_data)
            if result:
                print(f"  ✅ Bridge '{bridge_name}' updated successfully")
                return True
            else:
                print(f"  ❌ Failed to update bridge '{bridge_name}'")
                return False
        else:
            print(f"  ✅ Bridge already exists with correct URL")
            return True
    else:
        print(f"  📋 Bridge '{bridge_name}' does not exist, creating new bridge")
        
        result = create_new_bridge(chainlink_api, bridge_data)
        if result:
            print(f"  ✅ Bridge '{bridge_name}' created successfully")
            return True
        else:
            print(f"  ❌ Failed to create bridge '{bridge_name}'")
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