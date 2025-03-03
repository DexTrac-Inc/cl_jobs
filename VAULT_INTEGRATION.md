# HashiCorp Vault Integration Guide

This guide explains how to set up and use HashiCorp Vault for securely managing secrets in the cl_jobs application.

## Setup with Docker Compose

The easiest way to get started is by using the included Docker Compose configuration and setup script.

### Prerequisites

- Docker and Docker Compose installed
- Basic understanding of Vault concepts (KV secrets, tokens, policies)
- cl_jobs application set up with Docker

### 1. Start Vault and Initialize

Run the automated setup script:

```bash
./docker-vault-setup.sh
```

This script will:
1. Start the Vault service
2. Initialize Vault with a single unseal key
3. Unseal Vault
4. Enable the KV secrets engine
5. Create a policy for the application
6. Create a token for the application
7. Store the Chainlink credentials in Vault

The script will output the token and instructions for updating your `.env` file.

### 2. Update Environment Variables

Add the following to your `.env` file:

```
VAULT_ADDR=http://vault:8200
VAULT_TOKEN=<token-from-setup-script>
```

### 3. Test the Vault Setup

You can use the included Vault client to test the setup:

```bash
docker-compose run --rm vault-client status
docker-compose run --rm vault-client list chainlink
docker-compose run --rm vault-client get chainlink/auth
```

## Manual Vault Configuration

If you prefer to set up Vault manually or are using an existing Vault installation, follow these steps:

### 1. Enable KV Secrets Engine

```bash
vault secrets enable -version=2 kv
```

### 2. Create Policy

```bash
vault policy write chainlink-app - <<EOF
path "kv/data/chainlink/*" {
  capabilities = ["read"]
}
EOF
```

### 3. Create Token

```bash
vault token create -policy=chainlink-app
```

### 4. Store Secrets

```bash
vault kv put kv/chainlink/auth email="your-email@example.com" password_0="password1" password_1="password2"
```

### 5. Configure Application

Update your `.env` file with:

```
VAULT_ADDR=https://your-vault-server:8200
VAULT_TOKEN=your-token
```

## Integrating Vault in Python Code

Here's an example of how to integrate Vault in your Python code:

```python
import hvac
import os

# Initialize Vault client
vault_client = hvac.Client(
    url=os.environ.get('VAULT_ADDR'),
    token=os.environ.get('VAULT_TOKEN')
)

# Function to get secrets
def get_secret(path):
    try:
        response = vault_client.secrets.kv.v2.read_secret_version(
            path=path,
            mount_point='kv'
        )
        return response['data']['data']
    except Exception as e:
        print(f"Error retrieving secret: {e}")
        return None

# Example usage
auth_secrets = get_secret('chainlink/auth')
if auth_secrets:
    email = auth_secrets.get('email')
    password = auth_secrets.get('password_0')
    # Use these credentials instead of reading from environment
```

## Vault Security Considerations

1. **Token Management**: Rotate tokens regularly and use least-privilege policies.
2. **Unsealing**: In production, use auto-unseal features or distribute unseal keys.
3. **TLS**: Enable TLS for all Vault communications in production.
4. **Audit Logging**: Enable audit logging to track all access to secrets.

## Troubleshooting

If you encounter issues:

1. Check Vault status:
   ```bash
   docker-compose exec vault vault status
   ```

2. Verify authentication:
   ```bash
   docker-compose exec vault vault login $VAULT_TOKEN
   ```

3. Check secrets exist:
   ```bash
   docker-compose exec vault vault kv get kv/chainlink/auth
   ```

4. Inspect the seal status:
   ```bash
   docker-compose exec vault vault status | grep Sealed
   ```

5. Review Vault logs:
   ```bash
   docker-compose logs vault
   ```