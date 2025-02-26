#!/usr/bin/env python3
import json
import re
import logging

# Configure logger
logger = logging.getLogger("ChainlinkBridgeOps")

def get_bridges(chainlink_api, log_to_console=True):
    """
    Get all bridges from the node
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - log_to_console: Whether to print results to console
    
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
            error_msg = f"Failed to get bridges, status code: {response.status_code}"
            if log_to_console:
                print(f"❌ Error: {error_msg}")
            logger.error(error_msg)
            return []
    except Exception as e:
        error_msg = f"Exception when getting bridges: {e}"
        if log_to_console:
            print(f"❌ {error_msg}")
        logger.error(error_msg)
        return []

def get_bridge(chainlink_api, bridge_name, log_to_console=True):
    """
    Get a specific bridge by name
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - bridge_name: Name of the bridge
    - log_to_console: Whether to print results to console
    
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
            error_msg = f"Failed to get bridge '{bridge_name}', status code: {response.status_code}"
            if log_to_console:
                print(f"❌ Error: {error_msg}")
            logger.error(error_msg)
            return None
    except Exception as e:
        error_msg = f"Exception when getting bridge '{bridge_name}': {e}"
        if log_to_console:
            print(f"❌ {error_msg}")
        logger.error(error_msg)
        return None

def create_bridge(chainlink_api, name, url, confirmations=0, min_payment="0", log_to_console=True):
    """
    Create or update a bridge
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - name: Name of the bridge
    - url: URL of the bridge adapter
    - confirmations: Number of confirmations
    - min_payment: Minimum contract payment
    - log_to_console: Whether to print results to console
    
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
            success_msg = f"Bridge '{name}' created/updated successfully"
            if log_to_console:
                print(f"✅ {success_msg}")
            logger.info(success_msg)
            return True
        else:
            error_msg = f"Failed to create/update bridge '{name}', status code: {response.status_code}"
            if log_to_console:
                print(f"❌ {error_msg}")
                print(f"Response: {response.text}")
            logger.error(f"{error_msg}. Response: {response.text}")
            return False
    except Exception as e:
        error_msg = f"Exception when creating/updating bridge '{name}': {e}"
        if log_to_console:
            print(f"❌ {error_msg}")
        logger.error(error_msg)
        return False

def delete_bridge(chainlink_api, bridge_name, log_to_console=True):
    """
    Delete a bridge by name
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - bridge_name: Name of the bridge to delete
    - log_to_console: Whether to print results to console
    
    Returns:
    - Boolean indicating success or failure
    """
    try:
        response = chainlink_api.session.delete(
            f"{chainlink_api.node_url}/v2/bridge_types/{bridge_name}",
            verify=False
        )
        
        if response.status_code == 200:
            success_msg = f"Bridge '{bridge_name}' deleted successfully"
            if log_to_console:
                print(f"✅ {success_msg}")
            logger.info(success_msg)
            return True
        else:
            error_msg = f"Failed to delete bridge '{bridge_name}', status code: {response.status_code}"
            if log_to_console:
                print(f"❌ {error_msg}")
                print(f"Response: {response.text}")
            logger.error(f"{error_msg}. Response: {response.text}")
            return False
    except Exception as e:
        error_msg = f"Exception when deleting bridge '{bridge_name}': {e}"
        if log_to_console:
            print(f"❌ {error_msg}")
        logger.error(error_msg)
        return False

def get_bridge_groups(service, node, config_file="cl_hosts.json", log_to_console=True):
    """
    Get bridge groups for a specific node
    
    Parameters:
    - service: Service name (e.g., bootstrap, ocr)
    - node: Node name (e.g., arbitrum, ethereum)
    - config_file: Path to the config file
    - log_to_console: Whether to print results to console
    
    Returns:
    - List of bridge groups or empty list if not found
    """
    try:
        with open(config_file, "r") as file:
            config_data = json.load(file)
        
        node_config = config_data["services"][service][node]
        
        # Check for bridge_groups array first, fall back to single bridge_group
        if "bridge_groups" in node_config:
            bridge_groups = node_config["bridge_groups"]
            info_msg = f"Using multiple bridge groups from node config: {bridge_groups}"
            if log_to_console:
                print(info_msg)
            logger.info(info_msg)
            return bridge_groups
        elif "bridge_group" in node_config:
            bridge_groups = [node_config["bridge_group"]]
            info_msg = f"Using single bridge group from node config: {bridge_groups[0]}"
            if log_to_console:
                print(info_msg)
            logger.info(info_msg)
            return bridge_groups
        else:
            error_msg = f"No bridge_group or bridge_groups specified for {service}/{node} in config"
            if log_to_console:
                print(f"❌ {error_msg}")
            logger.error(error_msg)
            return []
    except KeyError:
        error_msg = f"Service '{service}' or node '{node}' not found in {config_file}"
        if log_to_console:
            print(f"❌ {error_msg}")
        logger.error(error_msg)
        return []
    except Exception as e:
        error_msg = f"Error loading node configuration: {e}"
        if log_to_console:
            print(f"❌ {error_msg}")
        logger.error(error_msg)
        return []

def get_bridges_from_groups(bridge_groups, bridges_config_file="cl_bridges.json", log_to_console=True):
    """
    Get consolidated bridges from specified bridge groups
    
    Parameters:
    - bridge_groups: List of bridge group names
    - bridges_config_file: Path to bridges configuration file
    - log_to_console: Whether to print results to console
    
    Returns:
    - Dictionary mapping bridge names to URLs
    """
    consolidated_bridges = {}
    
    try:
        with open(bridges_config_file, "r") as file:
            bridges_config = json.load(file)
            
        for group in bridge_groups:
            if group not in bridges_config.get("bridges", {}):
                warning_msg = f"Bridge group '{group}' not found in bridges configuration, skipping"
                if log_to_console:
                    print(f"⚠️ {warning_msg}")
                logger.warning(warning_msg)
                continue
                
            # Add bridges from this group to the consolidated mapping
            group_bridges = bridges_config["bridges"][group]
            consolidated_bridges.update(group_bridges)
            
        if not consolidated_bridges:
            error_msg = f"No valid bridge groups found in: {bridge_groups}"
            if log_to_console:
                print(f"❌ {error_msg}")
            logger.error(error_msg)
        
        return consolidated_bridges
    except Exception as e:
        error_msg = f"Error loading bridges configuration: {e}"
        if log_to_console:
            print(f"❌ {error_msg}")
        logger.error(error_msg)
        return {}

def batch_process_bridges(chainlink_api, service, node, group=None, config_file="cl_hosts.json", bridges_config_file="cl_bridges.json", log_to_console=True):
    """
    Process bridges in batch based on configuration files
    
    Parameters:
    - chainlink_api: Initialized ChainlinkAPI instance
    - service: Service name (e.g., bootstrap, ocr)
    - node: Node name (e.g., arbitrum, ethereum)
    - group: Optional specific bridge group to use
    - config_file: Path to config file
    - bridges_config_file: Path to bridges configuration file
    - log_to_console: Whether to print results to console
    
    Returns:
    - Tuple of (successful_count, failed_count)
    """
    try:
        # Get bridge groups for this node
        bridge_groups = get_bridge_groups(service, node, config_file, log_to_console)
        if not bridge_groups:
            return 0, 0
            
        # Get consolidated bridges from all groups
        consolidated_bridges = get_bridges_from_groups(bridge_groups, bridges_config_file, log_to_console)
        if not consolidated_bridges:
            return 0, 0
            
        # Get existing bridges to avoid unnecessary updates
        existing_bridges = get_bridges(chainlink_api, log_to_console=False)
        existing_bridge_names = {bridge["name"]: bridge for bridge in existing_bridges}
        
        successful = 0
        failed = 0
        
        # Process each bridge
        info_msg = f"Processing {len(consolidated_bridges)} bridges from configuration..."
        if log_to_console:
            print(info_msg)
        logger.info(info_msg)
        
        for bridge_name, bridge_url in consolidated_bridges.items():
            # Skip if bridge already exists with same URL
            if bridge_name in existing_bridge_names and existing_bridge_names[bridge_name]["url"] == bridge_url:
                info_msg = f"Bridge '{bridge_name}' already exists with correct URL, skipping"
                if log_to_console:
                    print(f"ℹ️ {info_msg}")
                logger.info(info_msg)
                successful += 1
                continue
                
            info_msg = f"Creating/updating bridge '{bridge_name}' with URL '{bridge_url}'"
            if log_to_console:
                print(info_msg)
            logger.info(info_msg)
            
            if create_bridge(chainlink_api, bridge_name, bridge_url, log_to_console=log_to_console):
                successful += 1
            else:
                failed += 1
                
        return successful, failed
    except Exception as e:
        error_msg = f"Exception during batch processing: {e}"
        if log_to_console:
            print(f"❌ {error_msg}")
        logger.error(error_msg)
        return 0, 0

def parse_bridge_error(error_message):
    """
    Parse bridge error message to extract required and existing bridges
    
    Parameters:
    - error_message: Error message containing bridge information
    
    Returns:
    - Tuple of (required_bridges, existing_bridges)
    """
    required_bridges = []
    existing_bridges = []
    
    # Extract the required bridges from the error message
    required_bridges_match = re.search(r'asked for \[(.*?)\]', error_message)
    if required_bridges_match:
        required_bridges = [b.strip() for b in required_bridges_match.group(1).split()]
    
    # Extract existing bridges if available
    existing_bridges_match = re.search(r'exists \[(.*?)\]', error_message)
    if existing_bridges_match:
        # Extract bridge names from complex structure - we only need the names
        existing_text = existing_bridges_match.group(1)
        existing_bridges = re.findall(r'\{(bridge-[^\s]+)', existing_text)
    
    return required_bridges, existing_bridges

def create_missing_bridges(chainlink_api, error_message, service, node, config_file="cl_hosts.json", bridges_config_file="cl_bridges.json", log_to_console=True):
    """
    Parse the error message, identify missing bridges, and create them
    
    Parameters:
    - chainlink_api: ChainlinkAPI instance
    - error_message: Error message containing bridge information
    - service: Service name (e.g., bootstrap, ocr)
    - node: Node name (e.g., arbitrum, ethereum)
    - config_file: Path to config file
    - bridges_config_file: Path to bridges configuration file
    - log_to_console: Whether to print results to console
    
    Returns:
    - Boolean indicating success or failure
    """
    info_msg = "Analyzing error message to identify missing bridges..."
    if log_to_console:
        print(info_msg)
    logger.info(info_msg)
    
    # Parse error message to get required and existing bridges
    required_bridges, existing_bridges = parse_bridge_error(error_message)
    
    if not required_bridges:
        error_msg = "Could not parse required bridges from error message"
        if log_to_console:
            print(f"❌ {error_msg}")
        logger.error(error_msg)
        return False
    
    info_msg = f"Required bridges: {required_bridges}"
    if log_to_console:
        print(info_msg)
    logger.info(info_msg)
    
    info_msg = f"Existing bridges: {existing_bridges}"
    if log_to_console:
        print(info_msg)
    logger.info(info_msg)
    
    # Determine missing bridges
    missing_bridges = [b for b in required_bridges if b not in existing_bridges]
    if not missing_bridges:
        info_msg = "No missing bridges identified"
        if log_to_console:
            print(info_msg)
        logger.info(info_msg)
        return False
    
    info_msg = f"Missing bridges to create: {missing_bridges}"
    if log_to_console:
        print(info_msg)
    logger.info(info_msg)
    
    # Get bridge groups for this node
    bridge_groups = get_bridge_groups(service, node, config_file, log_to_console)
    if not bridge_groups:
        return False
    
    # Get consolidated bridges from all groups
    consolidated_bridges = get_bridges_from_groups(bridge_groups, bridges_config_file, log_to_console)
    if not consolidated_bridges:
        return False
    
    # Create each missing bridge
    success_count = 0
    for bridge_name in missing_bridges:
        if bridge_name in consolidated_bridges:
            bridge_url = consolidated_bridges[bridge_name]
            if create_bridge(chainlink_api, bridge_name, bridge_url, log_to_console=log_to_console):
                success_count += 1
        else:
            error_msg = f"Bridge '{bridge_name}' not found in any configured bridge groups: {bridge_groups}"
            if log_to_console:
                print(f"❌ {error_msg}")
            logger.error(error_msg)
    
    return success_count == len(missing_bridges)

def check_bridge_config(error_message, service, node, bridges_config_file="cl_bridges.json", config_file="cl_hosts.json", log_to_console=True):
    """
    Check if required bridges exist in any bridge group
    
    Parameters:
    - error_message: Error message containing bridge information
    - service: Service name
    - node: Node name
    - bridges_config_file: Path to bridges configuration file
    - config_file: Path to node configuration file
    - log_to_console: Whether to print results to console
    
    Returns:
    - Tuple of (list of bridges not in any group, list of bridges in other groups)
    """
    # Parse error message to get required bridges
    required_bridges, _ = parse_bridge_error(error_message)
    if not required_bridges:
        return [], []
    
    # Load bridges configuration
    try:
        with open(bridges_config_file, "r") as file:
            bridges_config = json.load(file)
            
        # Get bridge groups for this node
        current_groups = get_bridge_groups(service, node, config_file, False)
            
        # Find which bridges exist in which groups
        not_in_any_group = []
        in_other_groups = []
        
        for bridge_name in required_bridges:
            found_in_any = False
            found_groups = []
            
            for group_name, group_bridges in bridges_config.get("bridges", {}).items():
                if bridge_name in group_bridges:
                    found_in_any = True
                    if group_name not in current_groups:
                        found_groups.append(group_name)
            
            if not found_in_any:
                not_in_any_group.append(bridge_name)
            elif found_groups:  # Only add if found in groups OTHER than the node's current groups
                in_other_groups.append((bridge_name, found_groups))
        
        return not_in_any_group, in_other_groups
        
    except Exception as e:
        error_msg = f"Error checking bridge configuration: {e}"
        if log_to_console:
            print(f"❌ {error_msg}")
        logger.error(error_msg)
        return [], [] 