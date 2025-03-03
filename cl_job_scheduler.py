#!/usr/bin/env python3
import os
import sys
import logging
import time
import argparse
from datetime import datetime, timedelta
import subprocess

# Get the minutes interval from environment or use default
DEFAULT_INTERVAL = 15
INTERVAL_MINUTES = int(os.environ.get("SCHEDULER_INTERVAL_MINUTES", DEFAULT_INTERVAL))

# Set DOCKER_CONTAINER environment variable for logging
os.environ['DOCKER_CONTAINER'] = str(os.path.exists('/.dockerenv')).lower()

# Import helpers for consistent logging
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.helpers import setup_logging

# Determine log file path
log_file = "logs/chainlink_scheduler.log" if os.path.exists('/.dockerenv') else "chainlink_scheduler.log"

# Setup logging using the common helper
logger = setup_logging(
    logger_name="ChainlinkScheduler", 
    log_file=log_file, 
    level=logging.INFO, 
    docker_mode=os.path.exists('/.dockerenv')
)

def run_job_approvals():
    """Run the job approvals script"""
    try:
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cl_jobs.py')
        logger.info("Attempting to run job approval script")
        
        # Run subprocess without capturing output so logs from cl_jobs.py go to Docker logs
        result = subprocess.run(
            [sys.executable, script_path], 
            capture_output=False,  # Don't capture, let it go to stdout/stderr
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"Job approval script failed with return code {result.returncode}")
        else:
            logger.info("Job approval run completed successfully")
            
    except Exception as e:
        logger.error(f"Error running job approval script: {e}")

def get_next_scheduled_time():
    """
    Calculate the next scheduled time based on INTERVAL_MINUTES
    
    For a 15-minute interval, this will be 00, 15, 30, 45 minutes past each hour
    For other intervals, it will be properly distributed (e.g., 0, 20, 40 for a 20-minute interval)
    """
    now = datetime.now()
    minutes = now.minute
    
    # Calculate which interval slot we need
    interval_slot = minutes // INTERVAL_MINUTES
    target_minute = (interval_slot + 1) * INTERVAL_MINUTES % 60
    
    # Create target time
    target_time = now.replace(minute=target_minute, second=0, microsecond=0)
    
    # If target time is in the past or exactly now, move to next interval
    if target_time <= now:
        # If we're moving to the next hour
        if target_minute == 0:
            target_time += timedelta(hours=1)
        # Special handling for custom intervals that might span to the next hour
        elif target_minute < minutes:
            target_time += timedelta(hours=1)
    
    return target_time

def main():
    # Parse command-line args if provided
    parser = argparse.ArgumentParser(description='Chainlink Job Approval Scheduler')
    parser.add_argument('--interval', type=int, help='Interval in minutes between job runs')
    parser.add_argument('--run-now', action='store_true', help='Run job immediately at startup')
    args = parser.parse_args()
    
    # Command line args override environment variables
    global INTERVAL_MINUTES
    if args.interval:
        INTERVAL_MINUTES = args.interval
    
    logger.info(f"Starting Chainlink Job Approval Scheduler with {INTERVAL_MINUTES} minute intervals")
    
    # Generate the schedule description
    if 60 % INTERVAL_MINUTES == 0:
        # If it evenly divides the hour, list all times
        times = []
        for m in range(0, 60, INTERVAL_MINUTES):
            times.append(f"{m:02d}")
        schedule_desc = f"Scheduled to run at {', '.join(times)} minutes past each hour"
    else:
        schedule_desc = f"Scheduled to run every {INTERVAL_MINUTES} minutes"
    
    logger.info(schedule_desc)
    
    # Run immediately if requested
    if args.run_now:
        logger.info("Running initial job at startup")
        run_job_approvals()
    
    while True:
        try:
            # Calculate next run time
            next_run_time = get_next_scheduled_time()
            
            # Calculate wait time
            now = datetime.now()
            wait_seconds = max(0, (next_run_time - now).total_seconds())
            
            logger.info(f"Next scheduled run at: {next_run_time}")
            
            # Wait until the next scheduled time
            time.sleep(wait_seconds)
            
            # Run the job
            run_job_approvals()
            
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
            time.sleep(60)  # Prevent rapid error looping

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Scheduler error: {e}")
        sys.exit(1)