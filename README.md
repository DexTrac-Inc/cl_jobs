# Chainlink Job Manager

An automated system for managing and approving Chainlink node jobs. This application includes a job scheduler that runs every 15 minutes and a job manager that handles the approval process.

## Disclaimer

⚠️ **IMPORTANT**: This script is provided "as is" without warranties or guarantees of any kind. Always use the dry run mode first (omit the --execute flag) to verify which jobs will be affected before performing any actions. While job cancellations can be undone using the reapproval script, it's best practice to verify which jobs will be affected before making changes to avoid potential disruptions to your Chainlink node operations.

## Features

- Automated job approval across multiple Chainlink nodes
- Configurable execution schedule (runs at 00, 15, 30, and 45 minutes past each hour)
- Job cancellation using feed IDs or name patterns
- Job reapproval for cancelled jobs
- Job listing and status reporting
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
   cp cl_host.json.example cl_hosts.json
   ```

3. Update the configuration files:
   - `.env`: Add your credentials and integration keys
   - `cl_hosts.json`: Configure your Chainlink node endpoints (add or remove services and nodes as needed)

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

## Usage

The application runs in multiple modes:

1. Scheduler Mode:
   ```bash
   python cl_job_scheduler.py
   ```

2. Manual Job Check:
   ```bash
   python cl_jobs.py
   ```

3. List Jobs:
   ```bash
   python cl_list_jobs.py --service bootstrap --node ethereum
   ```

4. Cancel Jobs:
   ```bash
   python cl_delete_jobs.py --service bootstrap --node ethereum --feed-ids-file feed_ids.txt
   ```

5. Reapprove Cancelled Jobs:
   ```bash
   python cl_reapprove_jobs.py --service bootstrap --node ethereum --feed-ids-file feed_ids.txt
   ```

### Job Listing

The `cl_list_jobs.py` script allows you to list and filter jobs on a node:

```bash
python cl_list_jobs.py --service SERVICE --node NODE [--status STATUS] [--has-updates] [--sort COLUMN] [--reverse] [--format FORMAT] [--full-width] [--output FILE] [--config CONFIG_FILE]
```

Parameters:
- `--service`: Service name from cl_hosts.json (e.g., bootstrap, ocr)
- `--node`: Node name from cl_hosts.json (e.g., arbitrum, ethereum)
- `--status`: Optional filter for job status (e.g., APPROVED, CANCELLED, PENDING)
- `--has-updates`: Optional flag to show only jobs with pending updates
- `--sort`: Sort by column: 'name' (default), 'id', 'spec_id', or 'updates'
- `--reverse`: Reverse the sort order
- `--full-width`: Display full job names without truncation (for wide terminals)
- `--format`: Output format: 'table' (default) or 'json'
- `--output`: Optional path to save output as JSON
- `--config`: Optional path to the config file (defaults to cl_hosts.json)

Example:
```bash
# List all jobs on a node in table format
python cl_list_jobs.py --service bootstrap --node ethereum

# List only cancelled jobs
python cl_list_jobs.py --service bootstrap --node ethereum --status CANCELLED

# Show jobs with pending updates
python cl_list_jobs.py --service bootstrap --node ethereum --has-updates

# Sort jobs by ID instead of name
python cl_list_jobs.py --service bootstrap --node ethereum --sort id

# Export job data to JSON file
python cl_list_jobs.py --service bootstrap --node ethereum --output jobs.json

# Show full job names without truncation
python cl_list_jobs.py --service bootstrap --node ethereum --full-width
```

The script provides:
- Jobs grouped by status (APPROVED, CANCELLED, PENDING, etc.)
- Sorting options for different columns
- Summary of jobs by status
- Detailed listing of jobs with their IDs, names, and update information
- Option to save results to a JSON file for further processing
- Filtering capabilities to focus on specific job types

### Job Cancellation

⚠️ **IMPORTANT**: Always run in dry-run mode first (without the `--execute` flag) to verify which jobs will be affected before performing any actual cancellations.

The `cl_delete_jobs.py` script allows you to cancel specific jobs using various criteria:

```bash
python cl_delete_jobs.py --service SERVICE --node NODE [--feed-ids-file FILE | --name-pattern PATTERN | --job-id ID] [--execute] [--config CONFIG_FILE]
```

Parameters:
- `--service`: Service name from cl_hosts.json (e.g., bootstrap, ocr)
- `--node`: Node name from cl_hosts.json (e.g., arbitrum, ethereum)
- `--feed-ids-file`: Path to file containing identifiers to match (0x addresses or text patterns)
- `--name-pattern`: Cancel jobs with names matching this pattern (e.g., "cron-capabilities")
- `--job-id`: Cancel a specific job by its ID
- `--execute`: Optional flag to actually perform cancellations (without this flag, runs in dry-run mode)
- `--config`: Optional path to the config file (defaults to cl_hosts.json)

Feed IDs file format:
- One identifier per line
- Can contain both 0x addresses and regular text patterns
- Lines without 0x addresses will be used as text patterns to match in job names
- Blank lines and lines starting with # are ignored
- Duplicate identifiers will be detected and reported

Example:
```bash
# Dry-run mode with feed IDs file (shows what would be cancelled without making changes)
python cl_delete_jobs.py --service bootstrap --node ethereum --feed-ids-file feeds_to_cancel.txt

# Cancel jobs matching a specific name pattern
python cl_delete_jobs.py --service bootstrap --node ethereum --name-pattern "cron-capabilities" --execute

# Cancel a specific job by ID
python cl_delete_jobs.py --service bootstrap --node ethereum --job-id 248 --execute

# Use a file with mixed patterns and feed IDs
python cl_delete_jobs.py --service bootstrap --node ethereum --feed-ids-file mixed_patterns.txt --execute
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

The script will:
1. Connect to the specified Chainlink node
2. Find jobs that match the provided criteria (feed IDs, name patterns, or specific job ID)
3. Report any identifiers that couldn't be matched to jobs
4. In dry-run mode, show jobs that would be cancelled
5. In execute mode, cancel the identified jobs

### Job Reapproval

The `cl_reapprove_jobs.py` script allows you to reapprove cancelled jobs based on their feed IDs:

```bash
python cl_reapprove_jobs.py --service SERVICE --node NODE --feed-ids-file FEED_IDS_FILE [--execute] [--config CONFIG_FILE]
```

Parameters:
- `--service`: Service name from cl_hosts.json (e.g., bootstrap, ocr)
- `--node`: Node name from cl_hosts.json (e.g., arbitrum, ethereum)
- `--feed-ids-file`: Path to file containing feed IDs to reapprove
- `--execute`: Optional flag to actually perform reapprovals (without this flag, runs in dry-run mode)
- `--config`: Optional path to the config file (defaults to cl_hosts.json)

Feed IDs file format:
- Same as for the cancellation script (one ID per line recommended)
- The script extracts all 0x addresses from each line
- Duplicate feed IDs will be detected and reported

Example:
```bash
# Dry-run mode (shows what would be reapproved without making changes)
python cl_reapprove_jobs.py --service bootstrap --node ethereum --feed-ids-file feeds_to_reapprove.txt

# Execute mode (performs actual reapprovals)
python cl_reapprove_jobs.py --service bootstrap --node ethereum --feed-ids-file feeds_to_reapprove.txt --execute
```

The script will:
1. Connect to the specified Chainlink node
2. Find cancelled jobs that match the feed IDs in the file
3. Report any feed IDs that couldn't be matched to cancelled jobs
4. In dry-run mode, show jobs that would be reapproved
5. In execute mode, reapprove the identified jobs

All scripts use connection retry logic to handle large batches of jobs and temporary network issues.

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
├── cl_job_scheduler.py # Scheduler script
├── cl_jobs.py # Main job management script
├── cl_list_jobs.py # Job listing script
├── cl_delete_jobs.py # Job cancellation script
├── cl_reapprove_jobs.py # Job reapproval script
├── cl_hosts.json # Node configuration
├── .env # Environment variables
├── requirements.txt # Python dependencies
└── cl_job_scheduler.service # Systemd service file
```

## Error Handling

The application includes comprehensive error handling:
- Authentication failures
- Network connectivity issues
- Job approval failures
- Job cancellation failures
- Job reapproval failures
- Configuration errors

Each error is logged and, when configured, triggers appropriate notifications through Slack and PagerDuty.

## Best Practices

1. **Always use dry run mode first**: Before executing any job cancellations or modifications, run the script without the `--execute` flag to see which jobs would be affected.

2. **Back up your node configuration**: Before making changes to multiple jobs, consider backing up your node configuration.

3. **Use specific patterns**: When using pattern matching, be as specific as possible to avoid unintended matches.

4. **Review the logs**: Always review the logs after operations to ensure everything executed as expected.

## Contributing

Please submit issues and pull requests for any improvements or bug fixes.
