#!/usr/bin/env python3
import os
import sys
import hvac
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_vault_client():
    """Initialize and return a Vault client"""
    vault_addr = os.environ.get('VAULT_ADDR')
    vault_token = os.environ.get('VAULT_TOKEN')
    
    if not vault_addr or not vault_token:
        print("Error: VAULT_ADDR and VAULT_TOKEN must be set in environment")
        sys.exit(1)
    
    try:
        client = hvac.Client(url=vault_addr, token=vault_token)
        if not client.is_authenticated():
            print("Error: Vault authentication failed")
            sys.exit(1)
        return client
    except Exception as e:
        print(f"Error connecting to Vault: {e}")
        sys.exit(1)

def get_secret(path):
    """Get a secret from Vault"""
    client = get_vault_client()
    try:
        response = client.secrets.kv.v2.read_secret_version(
            path=path,
            mount_point='kv'
        )
        return response['data']['data']
    except Exception as e:
        print(f"Error retrieving secret from {path}: {e}")
        return None

def list_secrets(path):
    """List secrets at a path"""
    client = get_vault_client()
    try:
        response = client.secrets.kv.v2.list_secrets(
            path=path,
            mount_point='kv'
        )
        return response.get('data', {}).get('keys', [])
    except Exception as e:
        print(f"Error listing secrets at {path}: {e}")
        return []

def main():
    if len(sys.argv) < 2:
        print("Usage: python vault-client.py <command> [arguments]")
        print("\nCommands:")
        print("  get <path>          Get a secret")
        print("  list <path>         List secrets at a path")
        print("  status              Check Vault status")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "get" and len(sys.argv) >= 3:
        path = sys.argv[2]
        secret = get_secret(path)
        if secret:
            print("Secret found:")
            for key, value in secret.items():
                print(f"  {key}: {value}")
    
    elif command == "list" and len(sys.argv) >= 3:
        path = sys.argv[2]
        keys = list_secrets(path)
        print(f"Secrets at {path}:")
        for key in keys:
            print(f"  {key}")
    
    elif command == "status":
        client = get_vault_client()
        try:
            print("Vault Connection Status:")
            print(f"  Authenticated: {client.is_authenticated()}")
            print(f"  Vault Address: {os.environ.get('VAULT_ADDR')}")
            sys_health = client.sys.read_health_status()
            print(f"  Vault Version: {sys_health.get('version')}")
            print(f"  Sealed: {sys_health.get('sealed')}")
            print(f"  Initialized: {sys_health.get('initialized')}")
        except Exception as e:
            print(f"Error checking Vault status: {e}")
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()