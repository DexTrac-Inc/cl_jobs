# Chainlink Job Manager

An automated system for managing and approving Chainlink node jobs and bridges. This application includes a job scheduler that runs at configurable intervals, a unified job manager that handles listing, cancellation, and reapproval of jobs, and bridge management functionality.

## Disclaimer

⚠️ **IMPORTANT**: This script is provided "as is" without warranties or guarantees of any kind. Always use the dry run mode first (omit the --execute flag) to verify which jobs will be affected before performing any actions. While job cancellations can be undone using the reapproval command, it's best practice to verify which jobs will be affected before making changes to avoid potential disruptions to your Chainlink node operations.

## Features

- Unified command interface for job and bridge management
- Automated job approval across multiple Chainlink nodes
- Configurable execution schedule (default: runs every 15 minutes)
- Job cancellation using feed IDs or name patterns
- Job reapproval for cancelled jobs
- Job listing and status reporting
- Bridge management (list, create, update, delete, batch)
- Slack notifications for job approval status
- PagerDuty integration for error tracking and alerts
- Docker support for easy deployment

## Prerequisites

- Python 3.x or Docker
- Access to Chainlink nodes
- Slack Webhook URL (optional)
- PagerDuty Integration Key (optional)

## Running with Docker (Recommended)

The application can be run using Docker and Docker Compose for easier deployment and management.

### Prerequisites

- Docker and Docker Compose installed
- Configuration files set up properly

### Setting Up

1. Copy the example environment file and update it with your credentials:

```bash
cp .env.example .env
# Edit .env with your credentials
```

2. Make sure your configuration files are in the config directory:

```bash
mkdir -p config
cp cl_hosts.json config/
cp cl_bridges.json config/
```

### Running the Services

To start all services:

```bash
docker compose up -d
```

To run a specific command with the CLI:

```bash
docker compose run --rm cl_jobs python cl_jobs_manager.py bridge list --service ocr --node tron
```

To view logs:

```bash
docker compose logs -f cl_jobs
docker compose logs -f slack_manager
```

### Setting Scheduler Interval

You can configure how often the job scheduler runs by setting the `SCHEDULER_INTERVAL_MINUTES` environment variable:

```bash
# In .env file
SCHEDULER_INTERVAL_MINUTES=30

# Or when starting the container
SCHEDULER_INTERVAL_MINUTES=5 docker compose up -d cl_jobs
```

The default interval is 15 minutes if not specified.

### Directory Structure

- `logs/`: Persistent logs directory 
- `config/`: Configuration files (read-only in containers)
- `.env`: Environment variables (loaded at runtime)

## Running Locally (Without Docker)

### Installation

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Usage

The main CLI can be used as follows:

```bash
python cl_jobs_manager.py [command] [options]
```

Example commands:

```bash
# List bridges
python cl_jobs_manager.py bridge list --service ocr --node tron

# Create bridge
python cl_jobs_manager.py bridge create --service ocr --node tron --name bridge-test-1 --url https://example.com

# List jobs
python cl_jobs_manager.py job list --service ocr --node tron

# Cancel jobs
python cl_jobs_manager.py job cancel --service ocr --node tron --address 0x1234567890abcdef1234567890abcdef12345678
```

## Configuration

### Environment Variables (.env)

- `EMAIL`: Login email for Chainlink nodes
- `PASSWORD_0`, `PASSWORD_1`: Passwords for different node configurations
- `SLACK_WEBHOOK`: Webhook URL for Slack notifications
- `PAGERDUTY_INTEGRATION_KEY`: Integration key for PagerDuty alerts
- `EXECUTE`: Set to 1 to enable automatic job approval (0 for dry-run mode)
- `SCHEDULER_INTERVAL_MINUTES`: How often the scheduler should run (default: 15)

### Node Configuration (cl_hosts.json)

The configuration file supports multiple chainlink nodes. Each entry requires:
- `url`: Node endpoint URL
- `password`: Index of the password to use (corresponds to PASSWORD_X in .env)
- `bridge_group` or `bridge_groups`: Bridge group(s) to use for this node

Example:
```json
{
  "services": {
    "bootstrap": {
      "ethereum": { 
        "url": "https://0.0.0.0", 
        "password": 0, 
        "bridge_group": "group_1" 
      },
      "polygon": {
        "url": "https://1.1.1.1",
        "password": 0,
        "bridge_groups": ["group_1", "group_2"]
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

## Slack Integration

The Slack bot allows interaction with Chainlink nodes through Slack. It supports both Socket Mode and HTTP mode.

### Socket Mode (Recommended)

1. Set up environment variables in `.env`:
   ```
   SLACK_BOT_TOKEN=xoxb-your-token
   SLACK_APP_TOKEN=xapp-your-token
   SLACK_AUTHORIZED_USERS=U1234567,U7654321
   ```

2. Run the Slack bot (or use Docker):
   ```bash
   python slack_job_manager/slack_job_manager.py
   ```

### HTTP Mode

1. Set up environment variables without the `SLACK_APP_TOKEN`.
2. Set the `PORT` environment variable.
3. Use a reverse proxy or ngrok to expose the service.

## License

See the LICENSE file for details.