#!/usr/bin/env python3
import os
import json
import requests
import urllib3
import time
import logging
import functools
from datetime import datetime, timedelta
from requests.exceptions import RequestException, SSLError

from utils.helpers import retry_on_connection_error
from core.vault_client import vault_client

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logger
logger = logging.getLogger("ChainlinkJobManager.api")  # Use a child logger of the main application logger

# Session pool to reuse connections
SESSION_POOL = {}

def requires_auth(func):
    """Decorator to ensure the method is called with an authenticated session"""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        use_logger = kwargs.get('use_logger', False)
        # Check if session needs renewal due to token expiration
        current_time = datetime.now()
        if (not self.session or 
            not self.authenticated or 
            not hasattr(self, 'token_expiry') or 
            current_time >= self.token_expiry):
            success = self.authenticate(use_logger=use_logger)
            if not success:
                if use_logger:
                    logger.error(f"Authentication required for {func.__name__} but failed")
                else:
                    print(f"❌ Error: Authentication required for {func.__name__} but failed")
                # Return appropriate empty value based on function's expected return type
                return_annotations = getattr(func, '__annotations__', {}).get('return')
                if return_annotations == bool:
                    return False
                elif return_annotations == list:
                    return []
                elif return_annotations == dict:
                    return {}
                return None
        return func(self, *args, **kwargs)
    return wrapper

class ChainlinkAPI:
    """
    Core class for interacting with Chainlink Node API
    """
    
    def __init__(self, node_url, email=None, password=None, password_index=None, node_name=None):
        """
        Initialize the API with connection details
        
        Parameters:
        - node_url: URL of the Chainlink node
        - email: Email for authentication (can be None if using Vault)
        - password: Password for authentication (can be None if using Vault)
        - password_index: Index for retrieving password from environment
        - node_name: Name of the node for retrieving credentials from Vault
        """
        self.node_url = node_url
        self.node_name = node_name
        self.password_index = password_index
        
        # Try to get credentials from Vault first
        if vault_client.is_available() and node_name:
            logger.debug(f"Getting credentials for {node_name} from Vault")
            credentials = vault_client.get_chainlink_credentials(node_name)
            if credentials:
                self.email = credentials.get('email', email)
                
                # Try to get password based on index if provided
                if password_index is not None and f'password_{password_index}' in credentials:
                    self.password = credentials.get(f'password_{password_index}')
                # Fallback to password_0
                elif 'password_0' in credentials:
                    self.password = credentials.get('password_0')
                else:
                    self.password = password
            else:
                self.email = email
                self.password = password
        else:
            # Use provided credentials
            self.email = email
            self.password = password
            
            # If password not provided but index is, get from environment
            if not self.password and password_index is not None:
                self.password = os.environ.get(f'PASSWORD_{password_index}')
        
        self.session = None
        self.authenticated = False
        self.token_expiry = None
        
    @retry_on_connection_error(max_retries=2, base_delay=3, max_delay=5)
    def authenticate(self, password=None, use_logger=False):
        """
        Authenticate with the Chainlink Node
        
        Parameters:
        - password: Password for authentication
        - use_logger: Whether to use logger instead of print
        
        Returns:
        - session: Authenticated session object or None if authentication fails
        """
        # Use existing session from pool if available
        global SESSION_POOL
        session_key = f"{self.node_url}:{self.email}"
        
        # Create a new session or reuse existing one
        if session_key in SESSION_POOL and SESSION_POOL[session_key]['valid_until'] > datetime.now():
            self.session = SESSION_POOL[session_key]['session']
            self.authenticated = True
            self.token_expiry = SESSION_POOL[session_key]['valid_until']
            debug_msg = f"Reusing cached session for {self.node_url} (valid until {self.token_expiry})"
            if use_logger:
                logger.debug(debug_msg)
            return True
        
        # Create new session
        self.session = requests.Session()
        session_endpoint = f"{self.node_url}/sessions"
        
        auth_response = self.session.post(
            session_endpoint,
            json={"email": self.email, "password": password or self.password},
            verify=False,
            timeout=10  # 10 second timeout
        )

        if auth_response.status_code != 200:
            error_msg = f"Authentication failed for {self.node_url}"
            if use_logger:
                logger.error(error_msg)
            else:
                print(f"❌ Error: {error_msg}")
            return False

        # Set token expiry to 24 hours from now (typical Chainlink token lifetime)
        # You may need to adjust this based on your specific node configuration
        self.token_expiry = datetime.now() + timedelta(hours=24)
        
        # Store in session pool
        SESSION_POOL[session_key] = {
            'session': self.session,
            'valid_until': self.token_expiry
        }

        success_msg = f"Authentication successful for {self.node_url} (valid until {self.token_expiry})"
        if use_logger:
            logger.info(success_msg)
        else:
            print(f"✅ {success_msg}")
        self.authenticated = True
        return self.session
    
    @requires_auth
    @retry_on_connection_error(max_retries=2, base_delay=3, max_delay=5)
    def get_all_feeds_managers(self, use_logger=False) -> list:
        """
        Retrieve all feeds managers from the Chainlink node
        
        Parameters:
        - use_logger: Whether to use logger instead of print
        
        Returns:
        - List of feeds managers
        """
        graphql_endpoint = f"{self.node_url}/query"

        query = """
        {
            feedsManagers {
                results {
                    id
                    name
                }
            }
        }
        """

        response = self.session.post(
            graphql_endpoint,
            json={"query": query},
            verify=False,
            timeout=10  # 10 second timeout
        )

        try:
            data = response.json()
            if "errors" in data:
                error_msg = "GraphQL Query Error:"
                if use_logger:
                    logger.error(error_msg)
                    logger.error(json.dumps(data["errors"], indent=2))
                else:
                    print(f"❌ {error_msg}")
                    print(json.dumps(data["errors"], indent=2))
                return []

            feeds_managers = data.get("data", {}).get("feedsManagers", {}).get("results", [])
            return feeds_managers

        except json.JSONDecodeError:
            error_msg = f"Failed to decode JSON response from {self.node_url}"
            if use_logger:
                logger.error(error_msg)
            else:
                print(f"❌ {error_msg}")
            return []
    
    @requires_auth
    @retry_on_connection_error(max_retries=2, base_delay=3, max_delay=5) 
    def fetch_jobs(self, feeds_manager_id, use_logger=False) -> list:
        """
        Fetch all job proposals for a specific feeds manager
        
        Parameters:
        - feeds_manager_id: ID of the feeds manager
        - use_logger: Whether to use logger instead of print
        
        Returns:
        - List of job proposals
        """
        graphql_endpoint = f"{self.node_url}/query"

        query = """
        query FetchFeedManagerWithProposals($id: ID!) {
            feedsManager(id: $id) {
                ... on FeedsManager {
                    jobProposals {
                        ... on JobProposal {
                            id
                            name
                            status
                            pendingUpdate
                            latestSpec {
                                id
                                status
                                createdAt
                                version
                            }
                            specs {
                                id
                                status
                                version
                                createdAt
                            }
                        }
                    }
                }
                ... on NotFoundError {
                    message
                    code
                    __typename
                }
                __typename
            }
        }
        """

        variables = {"id": str(feeds_manager_id)}
        response = self.session.post(
            graphql_endpoint,
            json={"query": query, "variables": variables},
            verify=False,
            timeout=10  # 10 second timeout
        )

        data = response.json()
        if "errors" in data:
            error_msg = f"GraphQL Error: {data['errors']}"
            if use_logger:
                logger.error(error_msg)
            else:
                print(f"❌ {error_msg}")
            return []

        return data.get("data", {}).get("feedsManager", {}).get("jobProposals", [])
    
    @requires_auth
    @retry_on_connection_error(max_retries=2, base_delay=3, max_delay=5)
    def cancel_job(self, job_id, use_logger=False) -> bool:
        """
        Cancel a job proposal spec
        
        Parameters:
        - job_id: ID of the job spec to cancel
        - use_logger: Whether to use logger instead of print
        
        Returns:
        - Boolean indicating success or failure
        """
        graphql_endpoint = f"{self.node_url}/query"

        mutation = """
        mutation CancelJobProposalSpec($id: ID!) {
            cancelJobProposalSpec(id: $id) {
                __typename
            }
        }
        """

        response = self.session.post(
            graphql_endpoint,
            json={"query": mutation, "variables": {"id": job_id}},
            verify=False,
            timeout=10  # 10 second timeout
        )

        result = response.json()
        if "errors" in result:
            error_msg = f"Failed to cancel job ID: {job_id}"
            if use_logger:
                logger.error(error_msg)
                logger.error(json.dumps(result, indent=2))
            else:
                print(f"❌ {error_msg}")
                print(json.dumps(result, indent=2))
            return False
        else:
            return True
    
    @requires_auth
    @retry_on_connection_error(max_retries=2, base_delay=3, max_delay=5)
    def approve_job(self, spec_id, force=True, use_logger=False) -> bool:
        """
        Approve or reapprove a job proposal spec
        
        Parameters:
        - spec_id: ID of the spec to approve
        - force: Whether to force approval even if the job has been canceled
        - use_logger: Whether to use logger instead of print
        
        Returns:
        - Boolean indicating success or failure
        """
        graphql_endpoint = f"{self.node_url}/query"

        mutation = """
        mutation ApproveJobProposalSpec($id: ID!, $force: Boolean) {
            approveJobProposalSpec(id: $id, force: $force) {
                ... on ApproveJobProposalSpecSuccess {
                    spec {
                        id
                    }
                }
                ... on NotFoundError {
                    message
                }
            }
        }
        """

        response = self.session.post(
            graphql_endpoint,
            json={"query": mutation, "variables": {"id": spec_id, "force": force}},
            verify=False,
            timeout=10  # 10 second timeout
        )
        
        # Store the last response for error analysis
        self.session._last_response = response

        result = response.json()
        if "errors" in result:
            error_msg = f"Failed to approve job spec ID: {spec_id}"
            if use_logger:
                logger.error(error_msg)
                logger.error(json.dumps(result, indent=2))
            else:
                print(f"❌ {error_msg}")
                print(json.dumps(result, indent=2))
            return False
        else:
            return True