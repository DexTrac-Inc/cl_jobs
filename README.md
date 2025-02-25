# Chainlink Job Manager

An automated system for managing and approving Chainlink node jobs. This application includes a job scheduler that runs every 15 minutes and a job manager that handles the approval process.

## Features

- Automated job approval across multiple Chainlink nodes
- Configurable execution schedule (runs at 00, 15, 30, and 45 minutes past each hour)
- Job cancellation using feed IDs
- Job reapproval for cancelled jobs
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

3. Cancel Jobs:
   ```bash
   python cl_delete_jobs.py --service bootstrap --node ethereum --feed-ids-file feed_ids.txt
   ```

4. Reapprove Cancelled Jobs:
   ```bash
   python cl_reapprove_jobs.py --service bootstrap --node ethereum --feed-ids-file feed_ids.txt
   ```

### Job Cancellation

The `cl_delete_jobs.py` script allows you to cancel specific jobs based on their feed IDs:

```bash
python cl_delete_jobs.py --service SERVICE --node NODE --feed-ids-file FEED_IDS_FILE [--execute] [--config CONFIG_FILE]
```

Parameters:
- `--service`: Service name from cl_hosts.json (e.g., bootstrap, ocr)
- `--node`: Node name from cl_hosts.json (e.g., arbitrum, ethereum)
- `--feed-ids-file`: Path to a file containing feed IDs to cancel
- `--execute`: Optional flag to actually perform cancellations (without this flag, runs in dry-run mode)
- `--config`: Optional path to the config file (defaults to cl_hosts.json)

Feed IDs file format:
- One feed ID per line is recommended
- The script will extract all 0x addresses from each line
- Duplicate feed IDs will be detected and reported

Example:
```bash
# Dry-run mode (shows what would be cancelled without making changes)
python cl_delete_jobs.py --service bootstrap --node ethereum --feed-ids-file feeds_to_cancel.txt

# Execute mode (performs actual cancellations)
python cl_delete_jobs.py --service bootstrap --node ethereum --feed-ids-file feeds_to_cancel.txt --execute
```

The script will:
1. Connect to the specified Chainlink node
2. Find jobs that match the feed IDs in the file
3. Report any feed IDs that couldn't be matched to jobs
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
- `--feed-ids-file`: Path to a file containing feed IDs to reapprove
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

Both the cancellation and reapproval scripts use connection retry logic to handle large batches of jobs and temporary network issues.

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

## Contributing

Please submit issues and pull requests for any improvements or bug fixes.
