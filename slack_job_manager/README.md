# Slack Chainlink Job Manager

A Slack bot that provides a complete interface to the Chainlink Job Manager through Slack messages. It supports both structured command-based interaction and natural language job deletion requests.

## Features

### Command-Based Interface
- Provides structured commands for all job manager operations
- Supports job listing, cancellation, and reapproval
- Offers bridge management (list, create, update, delete)
- Includes built-in help system with command examples

### Natural Language Job Deletion
- Monitors Slack messages for job deletion requests
- Parses network and contract address information from requests
- Matches requests to the appropriate Chainlink node configuration

### Common Features
- Only allows authorized users to interact with the system
- Provides job previews before making changes
- Confirms deletions via interactive buttons
- Formats responses clearly for Slack
- Runs as a systemd service for continuous operation

## Prerequisites

- Python 3.x
- Access to Chainlink nodes
- A Slack workspace
- A Slack bot with appropriate permissions

## Installation

1. Install the required Python packages:
   ```bash
   pip install slack-bolt
   ```

2. Create a Slack app at https://api.slack.com/apps
   - Click "Create New App" > "From scratch"
   - Name your app (e.g., "Chainlink Job Manager") and select your workspace
   - Go to "OAuth & Permissions" and add these Bot Token Scopes:
     - `channels:history` - Read message history in public channels
     - `chat:write` - Send messages as the app
     - `groups:history` - Read message history in private channels
     - `im:history` - Read message history in direct messages
     - `mpim:history` - Read message history in group direct messages
     - `users:read` - View users in the workspace (needed for detailed logging)
   - Go to "Socket Mode" and enable it (recommended)
     - Click "Enable Socket Mode" and generate an App Token
     - Save this token as SLACK_APP_TOKEN in your .env file
   - Go to "Event Subscriptions" and enable events
     - Click "Enable Events" (no URL needed with Socket Mode)
     - Under "Subscribe to bot events" add these events:
       - `message.channels` (public channels)
       - `message.groups` (private channels)
       - `message.im` (direct messages)
       - `message.mpim` (group direct messages)
   - Go to "Interactive Components" and enable it
     - Toggle "Interactivity" ON (no URL needed with Socket Mode)
   - Go to "Install App" and click "Install to Workspace"
     - Authorize the requested permissions
     - Copy the "Bot User OAuth Token" (starts with xoxb-)
     - Save this as SLACK_BOT_TOKEN in your .env file
   - In Slack, invite the bot to relevant channels using `/invite @YourBotName`

3. Configure the environment:

   **Option A: Using the .env file (recommended)**
   ```bash
   # Add the Slack configuration to your main .env file
   nano <path_to_cl_jobs>/.env
   ```

   Add these lines to your existing .env file:
   ```
   # Slack integration settings
   SLACK_BOT_TOKEN="xoxb-your-bot-token"
   SLACK_APP_TOKEN="xapp-your-app-token"  # Only for Socket Mode
   SLACK_AUTHORIZED_USERS="U01234567,U89012345"  # Comma-separated Slack user IDs
   PORT=3000  # Only needed if not using Socket Mode
   ```
   
   **Docker Setup Note**
   
   If running via Docker, make sure these variables are included in your .env file that's mounted to the container. Also ensure your configuration files are placed correctly:
   
   ```bash
   # Create config directory if it doesn't exist
   mkdir -p config
   
   # Make sure configuration files are in the config directory
   cp cl_hosts.json config/
   cp cl_bridges.json config/
   
   # Create logs directory if it doesn't exist
   mkdir -p logs
   
   # Make sure the directories are writable by the container
   chmod 777 logs
   ```

   **Option B: Using systemd environment variables**
   If you prefer not to use the .env file, you can uncomment and set the environment variables directly in the service file:
   ```bash
   # Edit the service file
   nano slack_job_manager.service
   
   # Uncomment and set these lines:
   #Environment=SLACK_BOT_TOKEN=xoxb-your-token-here
   #Environment=SLACK_APP_TOKEN=xapp-your-token-here
   #Environment=SLACK_AUTHORIZED_USERS=U01234567,U89012345
   ```

4. Install dependencies:
   ```bash
   # Make sure you're using the same Python environment as the main cl_jobs
   pip install slack-bolt
   ```

5. Set up the systemd service:
   ```bash
   # Edit the service file to replace placeholders
   # Replace <your_username> with your system username
   # Replace <path_to_cl_jobs> with the absolute path to your cl_jobs directory
   
   cp slack_job_manager.service slack_job_manager.service.local
   nano slack_job_manager.service.local
   
   # Install the service
   sudo cp slack_job_manager.service.local /etc/systemd/system/slack_job_manager.service
   sudo systemctl daemon-reload
   sudo systemctl enable slack_job_manager
   sudo systemctl start slack_job_manager
   ```

## Usage

### Command-Based Interface

The bot understands structured commands similar to the CLI interface. Here are some examples:

**Listing Jobs**
```
list jobs --service bootstrap --node ethereum --status APPROVED
```

**Cancelling Jobs**
```
cancel jobs --service bootstrap --node ethereum --address 0x0Aaf3EAcc3088691be6921fd33Bad8075590aE85
```

**Reapproving Jobs**
```
reapprove jobs --service bootstrap --node ethereum --address 0x0Aaf3EAcc3088691be6921fd33Bad8075590aE85
```

**Bridge Management**
```
list bridges --service ocr --node bsc
create bridge --service ocr --node bsc --name my-bridge --url https://example.com
update bridge --service ocr --node bsc --name my-bridge --url https://updated-url.com
delete bridge --service ocr --node bsc --name my-bridge
```

**Getting Help**
```
help
```

### Natural Language Commands

The bot also supports more conversational natural language commands:

**Listing Jobs**
```
list approved jobs on arbitrum ocr
list jobs on ethereum bootstrap
```

**Cancelling/Deleting Jobs**
```
cancel jobs 0x123abc on ethereum bootstrap
delete jobs 0x123abc0def456789 on ethereum bootstrap
```

**Reapproving Jobs**
```
reapprove jobs 0x123abc on ethereum bootstrap
```

**Bridge Management**
```
list bridges on arbitrum ocr
delete bridge my-bridge-name on arbitrum ocr
create bridge on arbitrum ocr with name my-new-bridge and url https://example.com
```

### Legacy Natural Language Job Deletion

For backward compatibility, the bot also understands the original style of natural language job deletion requests:

1. In a Slack channel where the bot is present, post a message in this format:
   ```
   please remove the 1 job listed below.
   :warning: Please double/triple check that the contract address and blockchain network matches the below, so that you do not accidentally remove a similar-looking job.
   :fantom-mainnet: 0x0Aaf3EAcc3088691be6921fd33Bad8075590aE85 fantom-mainnet OHM Index contractVersion 4
   ```

2. The bot will:
   - Parse the request
   - Check if you're authorized
   - Find matching jobs
   - Show a preview with confirmation buttons

3. Click "Confirm Deletion" to proceed or "Cancel" to abort

4. The bot will execute the deletion and report results

## Job Matching Logic

The bot identifies jobs based on:
1. The contract address exactly as provided
2. The network name from the message

Jobs are matched using the same logic as the `cancel_cmd.py` command.

## Authorization

Only users listed in the `SLACK_AUTHORIZED_USERS` environment variable can delete jobs. User IDs must be specified in the format `U01234567` (Slack user IDs).

To find a user's ID in Slack:
1. Click on the user's profile picture
2. Click the "..." (three dots) in their profile
3. Select "Copy member ID"
4. Add this ID to the comma-separated list in your .env file:
   ```
   SLACK_AUTHORIZED_USERS="U01234567,U89012345"
   ```

## Monitoring and Logging

Logs are written to:
- Console output
- `chainlink_slack_manager.log` in the main directory (or in logs/ when running in Docker)
- System journal (via syslog) with identifier `slack_job_manager`

The logs now include detailed information about:
- Which user initiated each command
- Command parameters and arguments
- Execution timing information
- Success/failure status of operations
- Error details with context

To check the logs:
```bash
# View service logs
sudo journalctl -u slack_job_manager

# View log file (standalone mode)
cat <path_to_cl_jobs>/chainlink_slack_manager.log

# View log file (Docker mode)
cat <path_to_cl_jobs>/logs/chainlink_slack_manager.log
```

## Troubleshooting

1. **Bot doesn't respond to messages**
   - Check if the bot is in the channel
   - Verify the app is installed to your workspace
   - Check the logs for errors

2. **Authorization failures**
   - Verify user IDs are correct in `.env`
   - Remember that user IDs begin with "U" followed by alphanumeric characters

3. **Missing user information in logs**
   - Check if you've added the `users:read` permission to your Slack app
   - Look for "missing_scope" errors in the logs
   - If found, update your Slack app permissions and reinstall it to your workspace

4. **No matching jobs found**
   - Verify the contract address is correct
   - Check that the network name matches a configured node

5. **Configuration not found errors**
   - Ensure cl_hosts.json and cl_bridges.json are in the correct location
   - For Docker mode, they should be in the `config/` directory
   - For standalone mode, they can be in the root directory

6. **Service won't start**
   - Check logs with `journalctl -u slack_job_manager`
   - Verify all environment variables are set correctly
   - Make sure the paths in the service file are correct

7. **Docker logs not appearing**
   - Check that the logs directory is mounted correctly in docker-compose.yml
   - Make sure the container has write permissions to the logs directory
   - Restart the container after making changes