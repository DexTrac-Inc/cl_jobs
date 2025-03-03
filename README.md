# Chainlink Jobs Manager

This application provides utilities for managing Chainlink nodes, jobs, and bridges.

## Features

- Create, update, and delete bridges
- List, approve, and cancel jobs
- Batch operations for multiple nodes
- Slack integration for job management

## Running with Docker

The application can be run using Docker and Docker Compose.

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
cp cl_hosts.json config/
cp cl_bridges.json config/
```

### Running the Services

To start all services:

```bash
docker-compose up -d
```

To run a specific command with the CLI:

```bash
docker-compose run --rm cl_jobs bridge list --service ocr --node tron
```

To view logs:

```bash
docker-compose logs -f slack_manager
```

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

## Slack Integration

The Slack bot allows interaction with Chainlink nodes through Slack. It supports both Socket Mode and HTTP mode.

### Socket Mode (Recommended)

1. Set up environment variables in `.env`:
   ```
   SLACK_BOT_TOKEN=xoxb-your-token
   SLACK_APP_TOKEN=xapp-your-token
   SLACK_AUTHORIZED_USERS=U1234567,U7654321
   ```

2. Run the Slack bot:
   ```bash
   python slack_job_manager/slack_job_manager.py
   ```

### HTTP Mode

1. Set up environment variables without the `SLACK_APP_TOKEN`.
2. Set the `PORT` environment variable.
3. Use a reverse proxy or ngrok to expose the service.

## License

See the LICENSE file for details.