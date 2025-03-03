#!/bin/bash
# Setup script for HashiCorp Vault integration with cl_jobs

set -e

# Check if Vault is running
if ! docker-compose exec -T vault vault status > /dev/null 2>&1; then
    echo "Starting Vault service..."
    docker-compose up -d vault
    sleep 5
fi

# Initialize Vault if not already initialized
INIT_STATUS=$(docker-compose exec -T vault vault status -format=json 2>/dev/null | grep -c initialized || echo "0")

if [ "$INIT_STATUS" = "0" ] || docker-compose exec -T vault vault status 2>&1 | grep -q "not yet initialized"; then
    echo "Initializing Vault..."
    INIT_OUTPUT=$(docker-compose exec -T vault vault operator init -key-shares=1 -key-threshold=1 -format=json)
    UNSEAL_KEY=$(echo $INIT_OUTPUT | jq -r '.unseal_keys_b64[0]')
    ROOT_TOKEN=$(echo $INIT_OUTPUT | jq -r '.root_token')
    
    # Save keys to a secure location (this is for demo purposes)
    echo "Unseal Key: $UNSEAL_KEY" > vault-keys.txt
    echo "Root Token: $ROOT_TOKEN" >> vault-keys.txt
    chmod 600 vault-keys.txt
    
    echo "Vault initialized. Keys saved to vault-keys.txt"
else
    echo "Vault already initialized."
    if [ ! -f vault-keys.txt ]; then
        echo "ERROR: vault-keys.txt not found. Cannot proceed with setup."
        exit 1
    fi
    UNSEAL_KEY=$(grep "Unseal Key" vault-keys.txt | cut -d' ' -f3)
    ROOT_TOKEN=$(grep "Root Token" vault-keys.txt | cut -d' ' -f3)
fi

# Unseal Vault if sealed
if docker-compose exec -T vault vault status 2>&1 | grep -q "sealed.*true"; then
    echo "Unsealing Vault..."
    docker-compose exec -T vault vault operator unseal $UNSEAL_KEY
fi

# Login to Vault
echo "Logging into Vault..."
docker-compose exec -T vault vault login $ROOT_TOKEN > /dev/null

# Enable the KV secrets engine if not already enabled
if ! docker-compose exec -T vault vault secrets list | grep -q "kv/"; then
    echo "Enabling KV secrets engine..."
    docker-compose exec -T vault vault secrets enable -version=2 kv
fi

# Create a chainlink policy
echo "Creating Chainlink policy..."
docker-compose exec -T vault vault policy write chainlink-app - <<EOF
path "kv/data/chainlink/*" {
  capabilities = ["read"]
}
EOF

# Create an application token
echo "Creating application token..."
TOKEN_INFO=$(docker-compose exec -T vault vault token create -policy=chainlink-app -format=json)
APP_TOKEN=$(echo $TOKEN_INFO | jq -r '.auth.client_token')

echo "Storing Chainlink credentials in Vault..."
# Store the Chainlink credentials in Vault
docker-compose exec -T vault vault kv put kv/chainlink/auth email="$EMAIL" password_0="$PASSWORD_0" password_1="$PASSWORD_1"

echo "Vault setup complete!"
echo "Application Token: $APP_TOKEN"
echo ""
echo "Add the following to your .env file:"
echo "VAULT_ADDR=http://vault:8200"
echo "VAULT_TOKEN=$APP_TOKEN"
echo ""
echo "Make sure to update your application code to use Vault for secrets."