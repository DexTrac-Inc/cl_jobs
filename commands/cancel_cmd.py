#!/usr/bin/env python3
import json
from utils.helpers import load_feed_ids

def register_arguments(subparsers):
    """
    Register the cancel command arguments
    
    Parameters:
    - subparsers: Subparsers object from argparse
    """
    parser = subparsers.add_parser('cancel', help='Cancel Chainlink jobs matching specific patterns')
    parser.add_argument('--service', required=True, help='Service name (e.g. bootstrap, ocr)')
    parser.add_argument('--node', required=True, help='Node name (e.g. arbitrum, ethereum)')
    parser.add_argument('--execute', action='store_true', help='Execute cancellations (default: dry run)')
    parser.add_argument('--feed-ids-file', help='Path to file containing feed IDs to cancel (one per line)')
    parser.add_argument('--name-pattern', help='Cancel jobs with names matching this pattern (e.g. "cron-capabilities")')
    parser.add_argument('--job-id', help='Cancel job with specific ID')
    
    return parser

def execute(args, chainlink_api):
    """
    Execute the cancel command
    
    Parameters:
    - args: Parsed arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - True if successful, False otherwise
    """
    # Validate arguments - need at least one way to identify jobs
    if not args.feed_ids_file and not args.name_pattern and not args.job_id:
        print("❌ Error: You must specify either --feed-ids-file, --name-pattern, or --job-id")
        return False
    
    print("\n" + "=" * 60)
    print(f"🔍 Checking jobs on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    # Load feed IDs and patterns
    feed_ids_to_cancel = []
    non_hex_patterns = []
    
    if args.feed_ids_file:
        feed_ids_to_cancel, non_hex_patterns = load_feed_ids(args.feed_ids_file)
    
    if args.name_pattern:
        non_hex_patterns.append(args.name_pattern)
    
    # Display criteria
    criteria = []
    if args.job_id:
        criteria.append(f"job ID: {args.job_id}")
    if feed_ids_to_cancel:
        criteria.append(f"{len(feed_ids_to_cancel)} feed IDs")
    if non_hex_patterns:
        criteria.append(f"{len(non_hex_patterns)} pattern(s): {', '.join(non_hex_patterns)}")
    
    print(f"🔍 Cancellation criteria: {' and '.join(criteria)}")
    
    # Authenticate with the Chainlink Node
    if not chainlink_api.authenticate():
        return False
    
    # Get all feeds managers
    feeds_managers = chainlink_api.get_all_feeds_managers()
    if not feeds_managers:
        print(f"✅ No feeds managers found")
        return True
    
    found_jobs = False
    all_jobs_to_cancel = []
    total_jobs = 0
    total_successful = 0
    total_failed = 0
    
    # Track all matched patterns globally across feed managers
    all_matched_patterns = set()
    all_matched_feed_ids = set()
    
    for fm in feeds_managers:
        print(f"🔍 Fetching job proposals for {fm['name']}")

        jobs = chainlink_api.fetch_jobs(fm["id"])
        jobs_to_cancel, matched_feed_ids, matched_patterns = get_jobs_to_cancel(
            jobs, feed_ids_to_cancel, non_hex_patterns, args.job_id
        )
        
        # Add to the overall list of jobs to cancel
        all_jobs_to_cancel.extend(jobs_to_cancel)
        
        # Track all matched identifiers globally
        all_matched_feed_ids.update(matched_feed_ids)
        all_matched_patterns.update(matched_patterns)
        
        if not jobs_to_cancel:
            print(f"✅ No cancellations needed for {fm['name']}")
            continue
        
        found_jobs = True
        print(f"📋 Found {len(jobs_to_cancel)} jobs to cancel for {fm['name']}")
        total_jobs += len(jobs_to_cancel)
        
        # Just list the jobs if not in execute mode
        if not args.execute:
            print("📃 Jobs that would be cancelled (dry run):")
            for job_id, job_name, identifier, match_reason in jobs_to_cancel:
                print(f"  - {job_name} (ID: {job_id}, Match: {match_reason})")
        else:
            # Add a progress counter
            print(f"⏳ Starting cancellation of {len(jobs_to_cancel)} jobs...")
            successful, failed = cancel_jobs(chainlink_api, jobs_to_cancel)
            total_successful += successful
            total_failed += failed
    
    # Compute truly unmatched identifiers globally
    all_unmatched_feed_ids = [feed_id for feed_id in feed_ids_to_cancel if feed_id not in all_matched_feed_ids]
    all_unmatched_patterns = [pattern for pattern in non_hex_patterns if pattern not in all_matched_patterns]
    
    # Report on unmatched feed IDs
    if all_unmatched_feed_ids:
        print("\n" + "=" * 60)
        print(f"⚠️ Found {len(all_unmatched_feed_ids)} feed IDs with no matching jobs:")
        for feed_id in sorted(all_unmatched_feed_ids):
            print(f"  - {feed_id}")
    
    # Report on unmatched patterns
    if all_unmatched_patterns:
        print("\n" + "=" * 60)
        print(f"⚠️ Found {len(all_unmatched_patterns)} patterns with no matching jobs:")
        for pattern in sorted(all_unmatched_patterns):
            print(f"  - {pattern}")
    
    # Print summary
    if args.execute and found_jobs:
        print("\n" + "=" * 60)
        print(f"📊 Job Cancellation Summary:")
        print(f"  Total jobs processed: {total_jobs}")
        print(f"  Successfully cancelled: {total_successful}")
        print(f"  Failed to cancel: {total_failed}")
            
    if not found_jobs:
        print("✅ No matching jobs found for cancellation")
    elif not args.execute:
        print("\n⚠️ Dry run completed. Use --execute flag to perform actual cancellations.")
    
    return True


def get_jobs_to_cancel(jobs, feed_ids_to_cancel, non_hex_patterns, job_id):
    """
    Identify jobs to cancel based on criteria
    
    Parameters:
    - jobs: List of jobs to filter
    - feed_ids_to_cancel: List of feed IDs to match
    - non_hex_patterns: List of text patterns to match
    - job_id: Specific job ID to match
    
    Returns:
    - Tuple of (jobs_to_cancel, matched_feed_ids, matched_patterns)
    """
    jobs_to_cancel = []
    matched_feed_ids = set()
    matched_patterns = set()
    
    # Convert all feed IDs to lowercase for case-insensitive comparison
    feed_ids_lower = [feed_id.lower() for feed_id in feed_ids_to_cancel]
    
    for job in jobs:
        if job["status"] != "APPROVED":
            continue
            
        job_id_value = job.get("id", "")
        job_name = job.get("name", "")
        job_name_lower = job_name.lower()
        match_reason = None
        matched_identifier = None
        
        # Check for specific job ID match
        if job_id and job_id_value == job_id:
            match_reason = f"job ID {job_id}"
            matched_identifier = job_id
        
        # Check for feed ID matches
        elif feed_ids_to_cancel:
            for i, feed_id_lower in enumerate(feed_ids_lower):
                if feed_id_lower in job_name_lower:
                    match_reason = f"feed ID {feed_ids_to_cancel[i]}"
                    matched_identifier = feed_ids_to_cancel[i]
                    matched_feed_ids.add(matched_identifier)
                    break
        
        # Check for non-hex pattern matches if no feed ID matched
        if not match_reason and non_hex_patterns:
            for pattern in non_hex_patterns:
                if pattern.lower() in job_name_lower:
                    match_reason = f"pattern '{pattern}'"
                    matched_identifier = pattern
                    matched_patterns.add(pattern)
                    break
        
        # If we found a match, add the job to our cancel list
        if match_reason:
            latest_spec_id = job.get("latestSpec", {}).get("id")
            if latest_spec_id:
                jobs_to_cancel.append((latest_spec_id, job_name, matched_identifier, match_reason))
            else:
                print(f"⚠️ Warning: Job '{job_name}' has no latest spec ID, skipping")
    
    # Sort jobs by name alphabetically
    jobs_to_cancel.sort(key=lambda x: x[1])
    
    return jobs_to_cancel, matched_feed_ids, matched_patterns


def cancel_jobs(chainlink_api, jobs_to_cancel):
    """
    Cancel a list of jobs
    
    Parameters:
    - chainlink_api: ChainlinkAPI instance
    - jobs_to_cancel: List of jobs to cancel
    
    Returns:
    - Tuple of (successful_count, failed_count)
    """
    successful = 0
    failed = 0
    
    for job_id, job_name, identifier, match_reason in jobs_to_cancel:
        try:
            print(f"⏳ Cancelling job ID: {job_id} ({job_name})")
            
            if chainlink_api.cancel_job(job_id):
                print(f"✅ Cancelled job ID: {job_id}")
                successful += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Exception when cancelling job {job_id}: {e}")
            failed += 1
    
    return successful, failed