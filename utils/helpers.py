#!/usr/bin/env python3
import os
import json
import re
import time
import random
import logging
from functools import wraps
from requests.exceptions import RequestException, SSLError
from logging.handlers import RotatingFileHandler

# Configure logger - use child logger of main application
logger = logging.getLogger("ChainlinkJobManager.helpers")

def setup_logging(logger_name, log_file=None, level=logging.INFO, docker_mode=None):
    """
    Set up logging configuration
    
    Parameters:
    - logger_name: Name for the logger
    - log_file: File to write logs to (optional)
    - level: Logging level (default: INFO)
    - docker_mode: Force Docker logging mode (None=auto-detect)
    
    Returns:
    - Configured logger
    """
    # Create logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    
    # Check if we're running in Docker
    if docker_mode is None:
        docker_mode = os.environ.get('DOCKER_CONTAINER', '').lower() == 'true' or os.path.exists('/.dockerenv')
    
    # Create formatter - simpler for Docker
    if docker_mode:
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    else:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Prevent adding duplicate handlers
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Create file handler if log file is specified
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # Log startup message
    if docker_mode:
        logger.info(f"Logger {logger_name} initialized in Docker mode")
    else:
        logger.info(f"Logger {logger_name} initialized")
    
    return logger

def load_node_config(config_file="cl_hosts.json"):
    """
    Load node configuration from cl_hosts.json
    
    Parameters:
    - config_file: Path to the configuration file
    
    Returns:
    - Dictionary with node configuration or None if error
    """
    try:
        with open(config_file, "r") as file:
            config = json.load(file)
        return config
    except Exception as e:
        logger.error(f"Failed to load node configuration: {str(e)}")
        return None

def retry_on_connection_error(max_retries=2, base_delay=3, max_delay=5):
    """
    Decorator to retry functions on connection errors with specific delays.
    
    Parameters:
    - max_retries: Maximum number of retry attempts
    - base_delay: Delay in seconds for first retry (3 seconds)
    - max_delay: Delay in seconds for second retry (5 seconds)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            use_logger = kwargs.get('use_logger', False)
            while True:
                try:
                    return func(*args, **kwargs)
                except (RequestException, SSLError) as e:
                    retries += 1
                    if retries > max_retries:
                        error_msg = f"Max retries exceeded. Last error: {e}"
                        if use_logger:
                            logger.error(error_msg)
                        else:
                            print(f"❌ {error_msg}")
                        # Return appropriate empty value based on function's annotations
                        return_annotations = getattr(func, '__annotations__', {}).get('return')
                        if return_annotations == bool:
                            return False
                        elif return_annotations == list:
                            return []
                        elif return_annotations == dict:
                            return {}
                        return None
                    
                    # Use specific delays: 3s for first retry, 5s for second retry
                    delay = base_delay if retries == 1 else max_delay
                    error_msg = f"Connection error: {e}"
                    retry_msg = f"Retrying in {delay} seconds... (Attempt {retries}/{max_retries})"
                    if use_logger:
                        logger.warning(error_msg)
                        logger.info(retry_msg)
                    else:
                        print(f"⚠️ {error_msg}")
                        print(f"⏳ {retry_msg}")
                    time.sleep(delay)
        return wrapper
    return decorator

def load_config(config_file, service, node, use_logger=False):
    """
    Load configuration for a specific service and node
    
    Parameters:
    - config_file: Path to the config file
    - service: Service name (e.g., bootstrap, ocr)
    - node: Node name (e.g., arbitrum, ethereum)
    - use_logger: Whether to use logger instead of print
    
    Returns:
    - Tuple of (node_url, password_index, node_config) or None if there's an error
    """
    # Check for config in mounted config directory first
    docker_config_path = os.path.join("config", os.path.basename(config_file))
    if os.path.exists(docker_config_path):
        config_file = docker_config_path
        if use_logger:
            logger.info(f"Using Docker mounted config: {config_file}")
    
    try:
        with open(config_file, "r") as file:
            config_data = json.load(file)
            
        # Get node URL and password index from config
        try:
            service_config = config_data["services"][service]
            node_config = service_config[node]
            node_url = node_config["url"]
            password_index = node_config.get("password", 0)
            
            # Return the full node_config as well for additional settings
            return node_url, password_index, node_config
                
        except KeyError:
            error_msg = f"Service '{service}' or node '{node}' not found in {config_file}"
            if use_logger:
                logger.error(error_msg)
            else:
                print(f"❌ Error: {error_msg}")
            return None
            
    except Exception as e:
        error_msg = f"Failed to load {config_file}: {e}"
        if use_logger:
            logger.error(error_msg)
        else:
            print(f"❌ Error: {error_msg}")
        return None

def load_feed_ids(feed_ids_file, use_logger=False):
    """
    Load feed IDs and non-hex patterns from a file
    
    Parameters:
    - feed_ids_file: Path to file containing feed IDs and patterns
    - use_logger: Whether to use logger instead of print
    
    Returns:
    - Tuple of (feed_ids, non_hex_patterns) or empty lists on error
    """
    if not feed_ids_file:
        return [], []
    
    try:
        # Extract feed IDs from the file
        feed_ids = []
        non_hex_patterns = []
        
        with open(feed_ids_file, 'r') as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue  # Skip empty lines and comments
                
                # Look for 0x pattern followed by hexadecimal characters
                matches = re.findall(r'(0x[0-9a-fA-F]+)', line)
                if matches:
                    feed_ids.extend(matches)
                else:
                    # If no hex pattern, use the line as a regular text pattern
                    non_hex_patterns.append(line)
        
        # Check for duplicates
        feed_id_count = {}
        for feed_id in feed_ids:
            feed_id_count[feed_id] = feed_id_count.get(feed_id, 0) + 1
        
        duplicate_feed_ids = {feed_id: count for feed_id, count in feed_id_count.items() if count > 1}
        
        if duplicate_feed_ids:
            warning_msg = f"Found {len(duplicate_feed_ids)} duplicate feed IDs in the input file:"
            if use_logger:
                logger.warning(warning_msg)
                for feed_id, count in duplicate_feed_ids.items():
                    logger.warning(f"  - {feed_id} (appears {count} times)")
            else:
                print(f"⚠️ Warning: {warning_msg}")
                for feed_id, count in duplicate_feed_ids.items():
                    print(f"  - {feed_id} (appears {count} times)")
        
        # Use only unique feed IDs
        unique_feed_ids = list(feed_id_count.keys())
        
        # Summary
        if unique_feed_ids or non_hex_patterns:
            if unique_feed_ids:
                info_msg = f"Loaded {len(unique_feed_ids)} unique feed IDs from {feed_ids_file}"
                if use_logger:
                    logger.info(info_msg)
                else:
                    print(f"✅ {info_msg}")
            if non_hex_patterns:
                info_msg = f"Loaded {len(non_hex_patterns)} non-hex patterns from {feed_ids_file}"
                if use_logger:
                    logger.info(info_msg)
                else:
                    print(f"✅ {info_msg}")
            return unique_feed_ids, non_hex_patterns
        else:
            warning_msg = f"No valid identifiers found in {feed_ids_file}"
            if use_logger:
                logger.warning(warning_msg)
            else:
                print(f"⚠️ Warning: {warning_msg}")
            return [], []
        
    except Exception as e:
        error_msg = f"Error reading feed IDs file: {e}"
        if use_logger:
            logger.error(error_msg)
        else:
            print(f"❌ {error_msg}")
        return [], []

def format_table_row(columns, widths, separator=" "):
    """
    Format a row for table display
    
    Parameters:
    - columns: List of column values
    - widths: List of column widths
    - separator: Character to use as separator
    
    Returns:
    - Formatted string
    """
    row = []
    for i, col in enumerate(columns):
        if i < len(widths):
            row.append(f"{str(col):<{widths[i]}}")
        else:
            row.append(str(col))
    return separator.join(row)

def filter_jobs(jobs, status=None, has_updates=False):
    """
    Filter jobs based on criteria
    
    Parameters:
    - jobs: List of jobs to filter
    - status: Filter by status (e.g., APPROVED, CANCELLED)
    - has_updates: Filter for jobs with pending updates
    
    Returns:
    - Filtered list of jobs
    """
    filtered_jobs = jobs.copy()
    
    # Apply status filter if specified
    if status:
        filtered_jobs = [j for j in filtered_jobs if j.get("status", "").upper() == status.upper()]
    
    # Filter for jobs with pending updates if requested
    if has_updates:
        filtered_jobs = [j for j in filtered_jobs if j.get("pendingUpdate", False)]
    
    return filtered_jobs

def confirm_action(prompt, use_logger=False):
    """
    Ask the user to confirm an action
    
    Parameters:
    - prompt: Question to ask the user
    - use_logger: Whether to use logger instead of print
    
    Returns:
    - Boolean indicating whether the user confirmed (True) or not (False)
    """
    if use_logger:
        logger.info(f"{prompt} [y/N]")
    else:
        prompt = f"{prompt} [y/N]: "
    
    response = input(prompt).strip().lower()
    return response == 'y' or response == 'yes'