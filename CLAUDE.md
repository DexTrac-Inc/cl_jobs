# Chainlink Jobs Manager Information

## Commands

### Building and Running
```bash
# Run job manager directly
python cl_jobs_manager.py [command] [options]

# Run bridge commands
python cl_jobs_manager.py bridge list --service ocr --node tron
python cl_jobs_manager.py bridge create --service ocr --node tron --name bridge-name --url https://example.com

# Docker Commands
docker compose build
docker compose up -d
docker compose logs -f cl_jobs
docker compose run --rm cl_jobs python cl_jobs_manager.py [command] [options]
```

## Coding Style

1. Use Python's PEP 8 style guide
2. Keep functions focused and single-purpose
3. Use descriptive variable and function names
4. Add docstrings for all functions and classes
5. Use f-strings for string formatting when possible

## Environment Setup

The application uses these environment files:
- `.env` - Main configuration file with credentials
- `cl_hosts.json` - Node configuration
- `cl_bridges.json` - Bridge configuration

## Scheduler Configuration

The job scheduler interval can be configured using the `SCHEDULER_INTERVAL_MINUTES` environment variable:
```
# In .env file
SCHEDULER_INTERVAL_MINUTES=30

# Or when starting containers
SCHEDULER_INTERVAL_MINUTES=5 docker compose up -d cl_jobs
```

## Docker Integration

Docker support is available with persistent storage for logs and config files.
Volume mounts:
- ./logs:/app/logs
- ./config:/app/config
- ./.env:/app/.env