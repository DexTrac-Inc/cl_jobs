#!/usr/bin/env python3
import os
import json
import requests
import urllib3
import time
import logging
from requests.exceptions import RequestException, SSLError

from utils.helpers import retry_on_connection_error

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logger
logger = logging.getLogger("ChainlinkJobManager.api")  # Use a child logger of the main application logger

class ChainlinkAPI:
    """
    Core class for interacting with Chainlink Node API
    """
    
    def __init__(self, node_url, email, password):
        """
        Initialize the API with connection details
        
        Parameters:
        - node_url: URL of the Chainlink node
        - email: Email for authentication
        - password: Password for authentication
        """
        self.node_url = node_url
        self.email = email
        self.password = password
        self.session = None
        self.authenticated = False
        
    @retry_on_connection_error(max_retries=5, base_delay=2, max_delay=30)
    def authenticate(self, password=None, use_logger=False):
        """
        Authenticate with the Chainlink Node
        
        Parameters:
        - password: Password for authentication
        - use_logger: Whether to use logger instead of print
        
        Returns:
        - session: Authenticated session object or None if authentication fails
        """
        # Skip if already authenticated
        if self.authenticated:
            return True
        
        self.session = requests.Session()
        session_endpoint = f"{self.node_url}/sessions"
        
        auth_response = self.session.post(
            session_endpoint,
            json={"email": self.email, "password": password or self.password},
            verify=False
        )

        if auth_response.status_code != 200:
            error_msg = f"Authentication failed for {self.node_url}"
            if use_logger:
                logger.error(error_msg)
            else:
                print(f"❌ Error: {error_msg}")
            return False

        success_msg = f"Authentication successful for {self.node_url}"
        if use_logger:
            logger.info(success_msg)
        else:
            print(f"✅ {success_msg}")
        self.authenticated = True
        return self.session
    
    @retry_on_connection_error(max_retries=3, base_delay=1, max_delay=10)
    def get_all_feeds_managers(self, use_logger=False):
        """
        Retrieve all feeds managers from the Chainlink node
        
        Parameters:
        - use_logger: Whether to use logger instead of print
        
        Returns:
        - List of feeds managers
        """
        if not self.session:
            error_msg = "Not authenticated. Call authenticate() first."
            if use_logger:
                logger.error(error_msg)
            else:
                print(f"❌ Error: {error_msg}")
            return []
            
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
            verify=False
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
    
    @retry_on_connection_error(max_retries=3, base_delay=1, max_delay=10)
    def fetch_jobs(self, feeds_manager_id, use_logger=False):
        """
        Fetch all job proposals for a specific feeds manager
        
        Parameters:
        - feeds_manager_id: ID of the feeds manager
        - use_logger: Whether to use logger instead of print
        
        Returns:
        - List of job proposals
        """
        if not self.session:
            error_msg = "Not authenticated. Call authenticate() first."
            if use_logger:
                logger.error(error_msg)
            else:
                print(f"❌ Error: {error_msg}")
            return []
            
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
            verify=False
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
    
    @retry_on_connection_error(max_retries=5, base_delay=2, max_delay=30)
    def cancel_job(self, job_id, use_logger=False):
        """
        Cancel a job proposal spec
        
        Parameters:
        - job_id: ID of the job spec to cancel
        - use_logger: Whether to use logger instead of print
        
        Returns:
        - Boolean indicating success or failure
        """
        if not self.session:
            error_msg = "Not authenticated. Call authenticate() first."
            if use_logger:
                logger.error(error_msg)
            else:
                print(f"❌ Error: {error_msg}")
            return False
            
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
            verify=False
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
    
    @retry_on_connection_error(max_retries=5, base_delay=2, max_delay=30)
    def approve_job(self, spec_id, force=True, use_logger=False):
        """
        Approve or reapprove a job proposal spec
        
        Parameters:
        - spec_id: ID of the spec to approve
        - force: Whether to force approval even if the job has been canceled
        - use_logger: Whether to use logger instead of print
        
        Returns:
        - Boolean indicating success or failure
        """
        if not self.session:
            error_msg = "Not authenticated. Call authenticate() first."
            if use_logger:
                logger.error(error_msg)
            else:
                print(f"❌ Error: {error_msg}")
            return False
            
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
            verify=False
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