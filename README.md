# Chainlink Job Manager

An automated system for managing and approving Chainlink node jobs and bridges. This application includes a job scheduler that runs every 15 minutes, a unified job manager that handles listing, cancellation, and reapproval of jobs, and bridge management functionality.

## Disclaimer

⚠️ **IMPORTANT**: This script is provided "as is" without warranties or guarantees of any kind. Always use the dry run mode first (omit the --execute flag) to verify which jobs will be affected before performing any actions. While job cancellations can be undone using the reapproval command, it's best practice to verify which jobs will be affected before making changes to avoid potential disruptions to your Chainlink node operations.

## Features

- Unified command interface for job and bridge management
- Automated job approval across multiple Chainlink nodes
- Configurable execution schedule (runs at 00, 15, 30, and 45 minutes past each hour)
- Job cancellation using feed IDs or name patterns
- Job reapproval for cancelled jobs
- Job listing and status reporting
- Bridge management (list, create, update, delete, batch)
- Slack notifications for job approval status
- PagerDuty integration for error tracking and alerts

## Prerequisites

- Python 3.x
- Access to Chainlink nodes
- Slack Webhook URL (optional)
- PagerDuty Integration Key (optional)

## Installation

1. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. Copy the example configuration files and update them with your settings:
   ```bash
   cp .env.example .env
   cp cl_hosts.json.example cl_hosts.json
   cp cl_bridges.json.example cl_bridges.json
   ```

3. Update the configuration files:
   - `.env`: Add your credentials and integration keys
   - `cl_hosts.json`: Configure your Chainlink node endpoints and bridge groups
   - `cl_bridges.json`: Define your bridge groups

4. Set up the systemd service:
   - Copy `cl_job_scheduler.service` to `/etc/systemd/system/`
   - Update the paths and user in the service file
   - Enable and start the service:
   ```bash
   sudo systemctl enable cl_job_scheduler
   sudo systemctl start cl_job_scheduler
   ```

## Configuration

### Environment Variables (.env)

- `EMAIL`: Login email for Chainlink nodes
- `PASSWORD_0`, `PASSWORD_1`: Passwords for different node configurations
- `SLACK_WEBHOOK`: Webhook URL for Slack notifications
- `PAGERDUTY_INTEGRATION_KEY`: Integration key for PagerDuty alerts
- `EXECUTE`: Set to 1 to enable automatic job approval (0 for dry-run mode)

### Node Configuration (cl_hosts.json)

The configuration file supports multiple chainlink nodes. Each entry requires:
- `url`: Node endpoint URL
- `password`: Index of the password to use (corresponds to PASSWORD_X in .env)
- `bridge_group`: Bridge group to use for this node

Example:
```json
{
  "services": {
    "bootstrap": {
      "ethereum": { 
        "url": "https://0.0.0.0", 
        "password": 0, 
        "bridge_group": "group_1" 
      }
    }
  }
}
```

### Bridge Configuration (cl_bridges.json)

The bridges configuration file defines groups of bridges with their URLs:

```json
{
    "bridges": {
        "group_1": {
            "bridge-example-1": "https://example1.adapters.cinternal.com",
            "bridge-example-2": "https://example2.adapters.cinternal.com"
        },
        "group_2": {
            "bridge-example-1": "https://alt1.adapters.cinternal.com",
            "bridge-example-2": "https://alt2.adapters.cinternal.com"
        }
    }
}
```

## Usage

The application provides two main interfaces:

1. **Automated job approval** using the scheduler:
   ```bash
   # Start the scheduler for automated job approvals
   python cl_job_scheduler.py
   
   # Run job check and approval manually
   python cl_jobs.py
   ```

2. **Manual job management** through the unified command interface:
   ```bash
   python cl_jobs_manager.py COMMAND [OPTIONS]
   ```

Available commands for manual management:
- `list`: List and filter jobs
- `cancel`: Cancel jobs based on criteria
- `reapprove`: Reapprove cancelled jobs
- `bridge`: Manage Chainlink bridges

Common options for all commands:
- `--service`: Service name from cl_hosts.json (e.g., bootstrap, ocr)
- `--node`: Node name from cl_hosts.json (e.g., arbitrum, ethereum)
- `--config`: Path to config file (default: cl_hosts.json)

### Automated Job Approval

The `cl_jobs.py` script handles automatic job checking and approval:

```bash
# Run with default settings (for automation)
python cl_jobs.py

# Run manually without sending notifications
python cl_jobs.py --suppress-notifications

# Force execution regardless of environment variable setting
python cl_jobs.py --execute

# Combine options
python cl_jobs.py --execute --suppress-notifications
```

Features:
- Automatically approves pending jobs across all configured nodes
- Tracks job approval failures and resolves them when fixed
- Sends formatted Slack notifications (can be suppressed for manual runs)
- PagerDuty integration for error tracking and incident management
- Shares core components with the job manager while remaining a separate tool

The script is designed to be run by the scheduler but can also be run manually with appropriate options. When run by the scheduler, notifications are enabled by default since they're important for automated operations.

Slack notifications are formatted clearly:
- ✅ Success notifications show approved jobs grouped by service/network
- ⚠️ Failure notifications include detailed error information with @channel alerts

The script leverages the ChainlinkAPI class and utility functions from the job manager components but operates independently as a standalone tool.

### Job Scheduler

The scheduler provides automated execution of the job approval process:

```bash
# Start the scheduler service
python cl_job_scheduler.py
```

The scheduler:
- Runs every 15 minutes (at 00, 15, 30, and 45 minutes past each hour)
- Executes the `cl_jobs.py` script automatically
- Ensures regular checking and approval of pending jobs
- Can be configured as a systemd service for persistent operation

To set up as a system service:
1. Edit the `cl_job_scheduler.service` file with your installation paths
2. Copy to `/etc/systemd/system/`
3. Enable and start with `systemctl` commands

### Job Listing

List and filter jobs on a node:

```bash
python cl_jobs_manager.py list --service SERVICE --node NODE [OPTIONS]
```

Options:
- `--status`: Filter jobs by status (e.g., APPROVED, CANCELLED, PENDING)
- `--has-updates`: Show only jobs with pending updates
- `--sort`: Sort by column: 'name' (default), 'id', 'spec_id', or 'updates'
- `--reverse`: Reverse the sort order
- `--full-width`: Display full job names without truncation (for wide terminals)
- `--format`: Output format: 'table' (default) or 'json'
- `--output`: Path to save output as JSON

Example:
```bash
# List all jobs on a node in table format
python cl_jobs_manager.py list --service bootstrap --node ethereum

# List only cancelled jobs
python cl_jobs_manager.py list --service bootstrap --node ethereum --status CANCELLED

# Show jobs with pending updates
python cl_jobs_manager.py list --service bootstrap --node ethereum --has-updates

# Sort jobs by ID instead of name
python cl_jobs_manager.py list --service bootstrap --node ethereum --sort id

# Export job data to JSON file
python cl_jobs_manager.py list --service bootstrap --node ethereum --output jobs.json
```

The command provides:
- Jobs grouped by status (APPROVED, CANCELLED, PENDING, etc.)
- Sorting options for different columns
- Summary of jobs by status
- Detailed listing of jobs with their IDs, names, and update information
- Option to save results to a JSON file for further processing

### Job Cancellation

⚠️ **IMPORTANT**: Always run in dry-run mode first (without the `--execute` flag) to verify which jobs will be affected before performing any actual cancellations.

Cancel specific jobs using various criteria:

```bash
python cl_jobs_manager.py cancel --service SERVICE --node NODE [OPTIONS]
```

Options:
- `--feed-ids-file`: Path to file containing identifiers to match (0x addresses or text patterns)
- `--name-pattern`: Cancel jobs with names matching this pattern (e.g., "cron-capabilities")
- `--job-id`: Cancel a specific job by its ID
- `--execute`: Flag to perform actual cancellations (without this flag, runs in dry-run mode)

Feed IDs file format:
- One identifier per line
- Can contain both 0x addresses and regular text patterns
- Lines without 0x addresses will be used as text patterns to match in job names
- Blank lines and lines starting with # are ignored
- Duplicate identifiers will be detected and reported

Example:
```bash
# Dry-run mode with feed IDs file (shows what would be cancelled without making changes)
python cl_jobs_manager.py cancel --service bootstrap --node ethereum --feed-ids-file feeds_to_cancel.txt

# Cancel jobs matching a specific name pattern
python cl_jobs_manager.py cancel --service bootstrap --node ethereum --name-pattern "cron-capabilities" --execute

# Cancel a specific job by ID
python cl_jobs_manager.py cancel --service bootstrap --node ethereum --job-id 248 --execute
```

Sample feeds_to_cancel.txt file:
```
# Feed IDs to cancel
0x0003fb80bf0e043e7bcc6e9808c9f62e722117afddb2b760ad6c58f6cc614444
0x0003481a2f7fe21c01d427f39035541d2b7a53db9c76234dc36082e6ad6db7f5

# Non-hex patterns to match
cron-capabilities-v2
WSTETH/USD-RefPrice
```

The command will:
1. Connect to the specified Chainlink node
2. Find jobs that match the provided criteria
3. Report any identifiers that couldn't be matched to jobs
4. In dry-run mode, show jobs that would be cancelled
5. In execute mode, cancel the identified jobs

### Job Reapproval

Reapprove cancelled jobs based on their feed IDs or patterns:

```bash
python cl_jobs_manager.py reapprove --service SERVICE --node NODE --feed-ids-file FEED_IDS_FILE [--execute]
```

Options:
- `--feed-ids-file`: Path to file containing feed IDs or patterns to reapprove (required)
- `--execute`: Flag to perform actual reapprovals (without this flag, runs in dry-run mode)

Feed IDs file format:
- Same as for the cancellation command (one ID per line recommended)
- The command extracts all 0x addresses from each line as well as non-hex patterns
- Duplicate feed IDs will be detected and reported

Example:
```bash
# Dry-run mode (shows what would be reapproved without making changes)
python cl_jobs_manager.py reapprove --service bootstrap --node ethereum --feed-ids-file feeds_to_reapprove.txt

# Execute mode (performs actual reapprovals)
python cl_jobs_manager.py reapprove --service bootstrap --node ethereum --feed-ids-file feeds_to_reapprove.txt --execute
```

The command will:
1. Connect to the specified Chainlink node
2. Find cancelled jobs that match the feed IDs or patterns in the file
3. Report any feed IDs or patterns that couldn't be matched to cancelled jobs
4. In dry-run mode, show jobs that would be reapproved
5. In execute mode, reapprove the identified jobs

# Multiple Bridge Groups Support

The system now supports configuring multiple bridge groups per node. This allows for better organization and flexibility in bridge management.

### Node Configuration with Multiple Bridge Groups (cl_hosts.json)

Nodes can now be configured with either a single bridge group or multiple bridge groups:

```json
{
  "services": {
    "bootstrap": {
      "ethereum": { 
        "url": "https://ethereum-node-url:6688", 
        "password": 0, 
        "bridge_groups": ["default_adapters", "ethereum_bridges"] 
      },
      "polygon": { 
        "url": "https://polygon-node-url:6688", 
        "password": 0, 
        "bridge_group": "default_adapters" 
      }
    }
  }
}
```

With `bridge_groups`, a node can use bridges from multiple groups. This allows for:
- Sharing common bridges across nodes
- Adding specialized bridges for specific networks
- Better organization of bridge definitions

The system will automatically combine all bridges from the specified groups when creating bridges for jobs.

### Bridge Configuration (cl_bridges.json)

The bridge configuration file remains unchanged, organizing bridges into logical groups:

```json
{
    "bridges": {
        "default_adapters": {
            "bridge-cmc": "https://adapters.domain.com:8081",
            "bridge-cg": "https://adapters.domain.com:8082"
        },
        "ethereum_bridges": {
            "bridge-ebalance": "https://adapters.domain.com:8083"
        }
    }
}
```

### Automatic Bridge Creation

The system now attempts to create missing bridges from all configured bridge groups:
1. If a job requires bridges that don't exist on the node, the system attempts to create them
2. Bridges are searched for in all of the node's configured bridge groups
3. If a required bridge isn't in any of the node's bridge groups, detailed diagnostic information is provided

## Bridge Management

The tool now provides enhanced bridge management capabilities:

### Listing Bridges

```
python cl_jobs_manager.py bridge list --service ocr --node bsc
```

This command will show all bridges on the node with proper formatting.

### Creating/Updating Bridges

```
python cl_jobs_manager.py bridge create --service ocr --node bsc --name my-bridge --url http://example.com
```

### Batch Creating Bridges

```
# Create all bridges from the node's configured bridge groups
python cl_jobs_manager.py bridge batch --service ocr --node bsc

# Create all bridges from a specific group
python cl_jobs_manager.py bridge batch --service ocr --node bsc --group group_name
```

The tool will automatically use bridge groups configured in cl_hosts.json, or you can specify a particular group.

### Batch Deleting Bridges

```
# Dry run - show bridges that would be deleted
python cl_jobs_manager.py bridge batch-delete --service ocr --node bsc

# Actually delete the bridges
python cl_jobs_manager.py bridge batch-delete --service ocr --node bsc --execute
```

The batch-delete command includes a safety mechanism requiring the --execute flag to perform actual deletion.

## Logging

Logs are written to multiple locations:
- Console output
- `chainlink_scheduler.log`
- `chainlink_jobs.log`
- System journal (via syslog)

## Monitoring

- Slack notifications for job approval status and failures
- PagerDuty alerts for critical errors and authentication failures
- Incident tracking with automatic resolution

## Directory Structure
```
├── cl_jobs_manager.py     # Main command interface script for manual management
├── cl_job_scheduler.py    # Scheduler script for automated operations
├── cl_jobs.py             # Main job checking/approval script for automated operations
├── commands/              # Command implementations for manual management
│   ├── __init__.py
│   ├── list_cmd.py        # List command functionality
│   ├── cancel_cmd.py      # Cancel command functionality
│   ├── reapprove_cmd.py   # Reapprove command functionality
│   └── bridge_cmd.py      # Bridge management functionality
├── core/                  # Core functionality
│   ├── __init__.py
│   └── chainlink_api.py   # Chainlink API interaction
├── utils/                 # Utility functions
│   ├── __init__.py
│   └── helpers.py         # Shared helper functions
├── cl_hosts.json          # Node configuration
├── cl_bridges.json        # Bridge groups configuration
├── .env                   # Environment variables
├── requirements.txt       # Python dependencies
└── cl_job_scheduler.service # Systemd service file
```

## Error Handling

The application includes comprehensive error handling:
- Authentication failures
- Network connectivity issues
- Job approval failures
- Job cancellation failures
- Job reapproval failures
- Bridge management failures
- Configuration errors

Each error is logged and, when configured, triggers appropriate notifications through Slack and PagerDuty.

## Best Practices

1. **Always use dry run mode first**: Before executing any job cancellations or modifications, run the command without the `--execute` flag to see which jobs would be affected.

2. **Back up your node configuration**: Before making changes to multiple jobs, consider backing up your node configuration.

3. **Use specific patterns**: When using pattern matching, be as specific as possible to avoid unintended matches.

4. **Review the logs**: Always review the logs after operations to ensure everything executed as expected.

5. **Organize bridges into logical groups**: Create bridge groups based on function or environment to make management easier.

## Contributing

Please submit issues and pull requests for any improvements or bug fixes.