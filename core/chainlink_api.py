#!/usr/bin/env python3
import os
import json
import requests
import urllib3
import time
from requests.exceptions import RequestException, SSLError

from utils.helpers import retry_on_connection_error

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
        
    @retry_on_connection_error(max_retries=5, base_delay=2, max_delay=30)
    def authenticate(self):
        """
        Authenticate with the Chainlink Node
        
        Returns:
        - session: Authenticated session object or None if authentication fails
        """
        self.session = requests.Session()
        session_endpoint = f"{self.node_url}/sessions"
        
        auth_response = self.session.post(
            session_endpoint,
            json={"email": self.email, "password": self.password},
            verify=False
        )

        if auth_response.status_code != 200:
            print(f"❌ Error: Authentication failed")
            return None

        print(f"✅ Authentication successful")
        return self.session
    
    @retry_on_connection_error(max_retries=3, base_delay=1, max_delay=10)
    def get_all_feeds_managers(self):
        """
        Retrieve all feeds managers from the Chainlink node
        
        Returns:
        - List of feeds managers
        """
        if not self.session:
            print("❌ Error: Not authenticated. Call authenticate() first.")
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
                print(f"❌ GraphQL Query Error:")
                print(json.dumps(data["errors"], indent=2))
                return []

            feeds_managers = data.get("data", {}).get("feedsManagers", {}).get("results", [])
            return feeds_managers

        except json.JSONDecodeError:
            print(f"❌ Failed to decode JSON response from {self.node_url}")
            return []
    
    @retry_on_connection_error(max_retries=3, base_delay=1, max_delay=10)
    def fetch_jobs(self, feeds_manager_id):
        """
        Fetch all job proposals for a specific feeds manager
        
        Parameters:
        - feeds_manager_id: ID of the feeds manager
        
        Returns:
        - List of job proposals
        """
        if not self.session:
            print("❌ Error: Not authenticated. Call authenticate() first.")
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
            print(f"❌ GraphQL Error: {data['errors']}")
            return []

        return data.get("data", {}).get("feedsManager", {}).get("jobProposals", [])
    
    @retry_on_connection_error(max_retries=5, base_delay=2, max_delay=30)
    def cancel_job(self, job_id):
        """
        Cancel a job proposal spec
        
        Parameters:
        - job_id: ID of the job spec to cancel
        
        Returns:
        - Boolean indicating success or failure
        """
        if not self.session:
            print("❌ Error: Not authenticated. Call authenticate() first.")
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
            print(f"❌ Failed to cancel job ID: {job_id}")
            print(json.dumps(result, indent=2))
            return False
        else:
            return True
    
    @retry_on_connection_error(max_retries=5, base_delay=2, max_delay=30)
    def approve_job(self, spec_id, force=True):
        """
        Approve or reapprove a job proposal spec
        
        Parameters:
        - spec_id: ID of the spec to approve
        - force: Whether to force approval even if the job has been canceled
        
        Returns:
        - Boolean indicating success or failure
        """
        if not self.session:
            print("❌ Error: Not authenticated. Call authenticate() first.")
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
            print(f"❌ Failed to approve job spec ID: {spec_id}")
            print(json.dumps(result, indent=2))
            return False
        else:
            return True