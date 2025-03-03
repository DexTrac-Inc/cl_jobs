#!/usr/bin/env python3
import os
import logging
import hvac

# Configure logger
logger = logging.getLogger("ChainlinkJobManager.vault")

class VaultClient:
    """Client for retrieving secrets from HashiCorp Vault"""
    
    def __init__(self):
        """Initialize the Vault client"""
        self.client = None
        self.initialized = False
        self.initialize()
    
    def initialize(self):
        """Initialize connection to Vault"""
        vault_addr = os.environ.get('VAULT_ADDR')
        vault_token = os.environ.get('VAULT_TOKEN')
        
        if not vault_addr or not vault_token:
            logger.debug("VAULT_ADDR or VAULT_TOKEN not set, Vault integration disabled")
            return False
        
        try:
            self.client = hvac.Client(url=vault_addr, token=vault_token)
            if self.client.is_authenticated():
                logger.debug(f"Successfully authenticated with Vault at {vault_addr}")
                self.initialized = True
                return True
            else:
                logger.warning(f"Failed to authenticate with Vault using provided token")
                return False
        except Exception as e:
            logger.warning(f"Failed to initialize Vault client: {e}")
            return False
    
    def is_available(self):
        """Check if Vault is available and authenticated"""
        if not self.initialized or not self.client:
            return False
        
        try:
            return self.client.is_authenticated()
        except:
            return False
    
    def get_secret(self, path, mount_point='kv'):
        """
        Get a secret from Vault
        
        Parameters:
        - path: Path to the secret
        - mount_point: The KV mount point
        
        Returns:
        - Dictionary containing the secret or None if unavailable
        """
        if not self.is_available():
            return None
        
        try:
            response = self.client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=mount_point
            )
            return response['data']['data']
        except Exception as e:
            logger.warning(f"Error retrieving secret from Vault at path {path}: {e}")
            return None
    
    def get_chainlink_credentials(self, node_name=None):
        """
        Get Chainlink credentials from Vault
        
        Parameters:
        - node_name: Optional node name to get specific credentials
        
        Returns:
        - Dictionary with email and passwords
        """
        # Try to get credentials from Vault
        path = "chainlink/auth"
        if node_name:
            path = f"chainlink/{node_name}"
        
        secret = self.get_secret(path)
        
        # If successful, return the secret
        if secret:
            return secret
        
        # Fall back to environment variables
        logger.debug("Falling back to environment variables for credentials")
        credentials = {
            'email': os.environ.get('EMAIL')
        }
        
        # Get all PASSWORD_X environment variables
        for i in range(10):  # We support up to 10 password indices
            password_key = f'PASSWORD_{i}'
            password_value = os.environ.get(password_key)
            if password_value:
                credentials[password_key] = password_value
        
        return credentials

# Singleton instance
vault_client = VaultClient()