#!/usr/bin/env python3
import json
from utils.helpers import load_feed_ids

def register_arguments(subparsers):
    """
    Register the reapprove command arguments
    
    Parameters:
    - subparsers: Subparsers object from argparse
    """
    parser = subparsers.add_parser('reapprove', help='Reapprove canceled Chainlink jobs matching specific feed IDs or patterns')
    parser.add_argument('--service', required=True, help='Service name (e.g. bootstrap, ocr)')
    parser.add_argument('--node', required=True, help='Node name (e.g. arbitrum, ethereum)')
    parser.add_argument('--execute', action='store_true', help='Execute reapprovals (default: dry run)')
    parser.add_argument('--feed-ids-file', required=True, help='Path to file containing feed IDs or patterns (one per line)')
    
    return parser

def execute(args, chainlink_api):
    """
    Execute the reapprove command
    
    Parameters:
    - args: Parsed arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - True if successful, False otherwise
    """
    print("\n" + "=" * 60)
    print(f"🔍 Checking for canceled jobs on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    # Load feed IDs and patterns
    feed_ids_to_reapprove, non_hex_patterns = load_feed_ids(args.feed_ids_file)
    
    if not feed_ids_to_reapprove and not non_hex_patterns:
        print("❌ Error: No valid identifiers found in file")
        return False
    
    # Display criteria
    criteria = []
    if feed_ids_to_reapprove:
        criteria.append(f"{len(feed_ids_to_reapprove)} feed IDs")
    if non_hex_patterns:
        criteria.append(f"{len(non_hex_patterns)} pattern(s): {', '.join(non_hex_patterns)}")
    
    print(f"🔍 Using {' and '.join(criteria)} for job matching")
    
    # Authenticate with the Chainlink Node
    if not chainlink_api.authenticate():
        return False
    
    # Get all feeds managers
    feeds_managers = chainlink_api.get_all_feeds_managers()
    if not feeds_managers:
        print(f"✅ No feeds managers found")
        return True
    
    found_jobs = False
    all_unmatched_feed_ids = []
    all_unmatched_patterns = []
    total_jobs = 0
    total_successful = 0
    total_failed = 0
    
    # Track all matched patterns globally across feed managers
    all_matched_feed_ids = set()
    all_matched_patterns = set()
    
    for fm in feeds_managers:
        print(f"🔍 Fetching job proposals for {fm['name']}")

        jobs = chainlink_api.fetch_jobs(fm["id"])
        jobs_to_reapprove, matched_feed_ids, matched_patterns = get_jobs_to_reapprove(
            jobs, feed_ids_to_reapprove, non_hex_patterns
        )
        
        # Track all matched identifiers globally
        all_matched_feed_ids.update(matched_feed_ids)
        all_matched_patterns.update(matched_patterns)

        if not jobs_to_reapprove:
            print(f"✅ No jobs to reapprove for {fm['name']}")
            continue
        
        found_jobs = True
        print(f"📋 Found {len(jobs_to_reapprove)} jobs to reapprove for {fm['name']}")
        total_jobs += len(jobs_to_reapprove)
        
        # Just list the jobs if not in execute mode
        if not args.execute:
            print("📃 Jobs that would be reapproved (dry run):")
            for spec_id, job_name, identifier, match_reason, job_id in jobs_to_reapprove:
                print(f"  - {job_name} (Job ID: {job_id}, Spec ID: {spec_id}, Match: {match_reason})")
        else:
            # Add a progress counter
            print(f"⏳ Starting reapproval of {len(jobs_to_reapprove)} jobs...")
            successful, failed = reapprove_jobs(chainlink_api, jobs_to_reapprove)
            total_successful += successful
            total_failed += failed
    
    # Compute truly unmatched identifiers globally
    all_unmatched_feed_ids = [feed_id for feed_id in feed_ids_to_reapprove if feed_id not in all_matched_feed_ids]
    all_unmatched_patterns = [pattern for pattern in non_hex_patterns if pattern not in all_matched_patterns]
    
    # Report on unmatched feed IDs
    if all_unmatched_feed_ids:
        print("\n" + "=" * 60)
        print(f"⚠️ Found {len(all_unmatched_feed_ids)} feed IDs with no matching canceled jobs:")
        
        # Show all unmatched feed IDs (no limit)
        for feed_id in sorted(all_unmatched_feed_ids):
            print(f"  - {feed_id}")
    
    # Report on unmatched patterns
    if all_unmatched_patterns:
        print("\n" + "=" * 60)
        print(f"⚠️ Found {len(all_unmatched_patterns)} patterns with no matching canceled jobs:")
        
        # Show all unmatched patterns (no limit)
        for pattern in sorted(all_unmatched_patterns):
            print(f"  - {pattern}")
    
    # Print summary
    if args.execute and found_jobs:
        print("\n" + "=" * 60)
        print(f"📊 Job Reapproval Summary:")
        print(f"  Total jobs processed: {total_jobs}")
        print(f"  Successfully reapproved: {total_successful}")
        print(f"  Failed to reapprove: {total_failed}")
            
    if not found_jobs:
        print("✅ No matching jobs found for reapproval")
    elif not args.execute:
        print("\n⚠️ Dry run completed. Use --execute flag to perform actual reapprovals.")
    
    return True

def get_jobs_to_reapprove(jobs, feed_ids, non_hex_patterns):
    """
    Identify Jobs to Reapprove based on feed IDs or patterns
    
    Parameters:
    - jobs: List of jobs from the API
    - feed_ids: List of feed IDs to match
    - non_hex_patterns: List of patterns to match
    
    Returns:
    - Tuple of (jobs_to_reapprove, matched_feed_ids, matched_patterns)
    """
    jobs_to_reapprove = []
    matched_feed_ids = set()
    matched_patterns = set()
    
    # Convert all feed IDs and patterns to lowercase for case-insensitive comparison
    feed_ids_lower = [feed_id.lower() for feed_id in feed_ids]
    
    for job in jobs:
        # Check for "CANCELLED" or "CANCELED" status (handle different spellings)
        job_status = job.get("status", "").upper()
        if job_status in ["CANCELLED", "CANCELED"]:
            job_name = job.get("name", "")
            job_name_lower = job_name.lower()
            match_reason = None
            matched_identifier = None
            
            # Check for feed ID matches
            for i, feed_id_lower in enumerate(feed_ids_lower):
                if feed_id_lower in job_name_lower:
                    match_reason = f"feed ID {feed_ids[i]}"
                    matched_identifier = feed_ids[i]
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
            
            # If we found a match, add the job to our reapprove list
            if match_reason:
                # We need the latest spec ID - this is what we'll try to approve
                latest_spec_id = job.get("latestSpec", {}).get("id")
                if latest_spec_id:
                    jobs_to_reapprove.append((latest_spec_id, job_name, matched_identifier, match_reason, job["id"]))
                else:
                    print(f"⚠️ Warning: Job '{job_name}' has no latest spec ID")
    
    # Sort jobs by name alphabetically
    jobs_to_reapprove.sort(key=lambda x: x[1])
    
    return jobs_to_reapprove, matched_feed_ids, matched_patterns

def reapprove_jobs(chainlink_api, jobs_to_reapprove):
    """
    Reapprove a list of jobs
    
    Parameters:
    - chainlink_api: ChainlinkAPI instance
    - jobs_to_reapprove: List of jobs to reapprove
    
    Returns:
    - Tuple of (successful_count, failed_count)
    """
    successful = 0
    failed = 0
    
    for spec_id, job_name, identifier, match_reason, job_id in jobs_to_reapprove:
        try:
            print(f"⏳ Reapproving job spec ID: {spec_id} for job proposal ID: {job_id} ({job_name})")
            
            if chainlink_api.approve_job(spec_id, force=True):
                print(f"✅ Reapproved job spec ID: {spec_id} for job ({job_name})")
                successful += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Exception when reapproving job {spec_id}: {e}")
            failed += 1
    
    return successful, failed