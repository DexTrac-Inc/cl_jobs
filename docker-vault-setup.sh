#!/bin/bash
# Setup script for HashiCorp Vault integration with cl_jobs

set -e

# Check if Vault is running
if ! docker compose exec -T vault vault status > /dev/null 2>&1; then
    echo "Starting Vault service..."
    docker compose up -d vault
    sleep 5
fi

# Initialize Vault if not already initialized
INIT_OUTPUT=$(docker compose exec -T vault vault operator init -key-shares=1 -key-threshold=1 -format=json 2>/dev/null || echo "")

# Check if init was successful by looking for unseal_keys in the output
if [[ "$INIT_OUTPUT" == *"unseal_keys"* ]]; then
    echo "Initializing Vault..."
    UNSEAL_KEY=$(echo $INIT_OUTPUT | jq -r '.unseal_keys_b64[0]')
    ROOT_TOKEN=$(echo $INIT_OUTPUT | jq -r '.root_token')
    
    # Save keys to a secure location (this is for demo purposes)
    echo "Unseal Key: $UNSEAL_KEY" > vault-keys.txt
    echo "Root Token: $ROOT_TOKEN" >> vault-keys.txt
    chmod 600 vault-keys.txt
    
    echo "Vault initialized. Keys saved to vault-keys.txt"
else
    echo "Vault already initialized."
    # In dev mode, we can use the dev root token
    if [ ! -f vault-keys.txt ]; then
        echo "Creating vault-keys.txt with dev token..."
        DEV_TOKEN=$(grep "VAULT_DEV_ROOT_TOKEN_ID" docker-compose.yml | cut -d'=' -f2)
        # If we can't extract from docker-compose.yml, use the default dev-only-token
        if [ -z "$DEV_TOKEN" ]; then
            DEV_TOKEN="dev-only-token"
        fi
        echo "Unseal Key: none-needed-for-dev-mode" > vault-keys.txt
        echo "Root Token: $DEV_TOKEN" >> vault-keys.txt
        chmod 600 vault-keys.txt
    fi
    UNSEAL_KEY=$(grep "Unseal Key" vault-keys.txt | cut -d' ' -f3)
    ROOT_TOKEN=$(grep "Root Token" vault-keys.txt | cut -d' ' -f3)
fi

# Unseal Vault if sealed
if docker compose exec -T vault vault status 2>&1 | grep -q "sealed.*true"; then
    echo "Unsealing Vault..."
    docker compose exec -T vault vault operator unseal $UNSEAL_KEY
fi

# Login to Vault
echo "Logging into Vault..."
docker compose exec -T vault vault login -address=http://127.0.0.1:8200 $ROOT_TOKEN > /dev/null

# Set Vault address for all commands
export VAULT_ADDR=http://127.0.0.1:8200
docker compose exec -T vault sh -c "export VAULT_ADDR=http://127.0.0.1:8200"

# Enable the KV secrets engine if not already enabled
if ! docker compose exec -T vault vault secrets list -address=http://127.0.0.1:8200 | grep -q "kv/"; then
    echo "Enabling KV secrets engine..."
    docker compose exec -T vault vault secrets enable -address=http://127.0.0.1:8200 -version=2 kv
fi

# Create a chainlink policy
echo "Creating Chainlink policy..."
docker compose exec -T vault vault policy write -address=http://127.0.0.1:8200 chainlink-app - <<EOF
path "kv/data/chainlink/*" {
  capabilities = ["read"]
}
EOF

# Create an application token
echo "Creating application token..."
TOKEN_INFO=$(docker compose exec -T vault vault token create -address=http://127.0.0.1:8200 -policy=chainlink-app -format=json)
# For dev mode, just use the dev token
APP_TOKEN="dev-only-token"
echo "Using dev token for application: $APP_TOKEN"

echo "Storing Chainlink credentials in Vault..."
# Store the Chainlink credentials in Vault
docker compose exec -T vault vault kv put -address=http://127.0.0.1:8200 kv/chainlink/auth email="${EMAIL:-demo@example.com}" password_0="${PASSWORD_0:-demo-password-0}" password_1="${PASSWORD_1:-demo-password-1}"

echo "Vault setup complete!"
echo "Application Token: $APP_TOKEN"
echo ""
echo "Add the following to your .env file:"
echo "VAULT_ADDR=http://vault:8200"
echo "VAULT_TOKEN=$APP_TOKEN"
echo ""
echo "Make sure to update your application code to use Vault for secrets."