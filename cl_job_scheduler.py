#!/opt/cl-jobs/venv/bin/python3
import os
import sys
import logging
import time
from datetime import datetime, timedelta
import subprocess

# Setup logging
logger = logging.getLogger("ChainlinkScheduler")
logger.setLevel(logging.INFO)

# Define log format
log_format = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

# Console logging
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)
logger.addHandler(console_handler)

# File logging
file_handler = logging.FileHandler("chainlink_scheduler.log")
file_handler.setFormatter(log_format)
file_handler.setLevel(logging.INFO)
logger.addHandler(file_handler)

def run_job_approvals():
    """Run the job approvals script"""
    try:
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cl_jobs.py')
        logger.info("Attempting to run job approval script")
        
        result = subprocess.run(
            [sys.executable, script_path], 
            capture_output=True, 
            text=True
        )
        
        if result.returncode != 0:
            logger.error(f"Job approval script failed with return code {result.returncode}")
            logger.error(f"Error output: {result.stderr}")
        else:
            logger.info("Job approval run completed successfully")
            
    except Exception as e:
        logger.error(f"Error running job approval script: {e}")

def get_next_scheduled_time():
    """Calculate the next scheduled time (00, 15, 30, 45)"""
    now = datetime.now()
    minutes = now.minute
    
    # Determine the next scheduled time
    if minutes < 15:
        target_minute = 15
    elif minutes < 30:
        target_minute = 30
    elif minutes < 45:
        target_minute = 45
    else:
        target_minute = 0
        
    # Create target time
    target_time = now.replace(minute=target_minute, second=0, microsecond=0)
    
    # If target time is in the past, move to next hour
    if target_time <= now:
        if target_minute == 0:
            target_time += timedelta(hours=1)
        else:
            target_time = target_time.replace(hour=(now.hour + 1) % 24)
    
    return target_time

def main():
    logger.info("Starting Chainlink Job Approval Scheduler")
    logger.info("Scheduled to run at 00, 15, 30, and 45 minutes past each hour")
    
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