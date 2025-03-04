#!/usr/bin/env python3
import json
import sys
import os
from core.chainlink_api import ChainlinkAPI
from utils.helpers import load_config, load_feed_ids, confirm_action
from utils.bridge_ops import create_missing_bridges, check_bridge_config

def register_arguments(subparsers):
    """
    Register the reapprove command arguments
    """
    parser = subparsers.add_parser('reapprove', help='Reapprove canceled Chainlink jobs matching specific criteria')
    parser.add_argument('--service', required=True, help='Service name (e.g., bootstrap, ocr)')
    parser.add_argument('--node', required=True, help='Node name (e.g., arbitrum, ethereum)')
    parser.add_argument('--name-pattern', help='Pattern to match job names (case-insensitive)')
    parser.add_argument('--feed-ids', nargs='+', help='List of feed IDs to reapprove')
    parser.add_argument('--feed-ids-file', help='File containing feed IDs to reapprove (one per line)')
    parser.add_argument('--force', action='store_true', help='Force reapproval regardless of job status')
    parser.add_argument('--execute', action='store_true', help='Execute changes (default: dry run)')
    
    return parser

def execute(args, chainlink_api=None):
    """
    Execute the reapprove command
    """
    # Only initialize if no ChainlinkAPI instance was provided
    if not chainlink_api:
        # Load configuration
        config_result = load_config("cl_hosts.json", args.service, args.node)
        if not config_result:
            return False
            
        node_url, password_index = config_result
        
        # Initialize ChainlinkAPI
        chainlink_api = ChainlinkAPI(node_url, os.getenv("EMAIL"))
        
        # Get password
        password = os.getenv(f"PASSWORD_{password_index}")
        if not password:
            print(f"❌ Error: PASSWORD_{password_index} environment variable not set")
            return False
            
        # Authenticate
        if not chainlink_api.authenticate(password):
            print(f"❌ Authentication failed for {args.service.upper()} {args.node.upper()} ({node_url})")
            return False
        else:
            print(f"✅ Authentication successful")
    # If we received a ChainlinkAPI instance, we assume it's already authenticated
    # in cl_jobs_manager.py and we don't attempt to authenticate again
    
    print(f"🔍 Reapproving jobs on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    # Load feed IDs if specified
    feed_ids = []
    non_hex_patterns = []
    
    if args.feed_ids:
        feed_ids.extend([feed_id.lower() for feed_id in args.feed_ids])
    
    if args.feed_ids_file:
        file_feed_ids, file_patterns = load_feed_ids(args.feed_ids_file)
        feed_ids.extend([feed_id.lower() for feed_id in file_feed_ids])
        non_hex_patterns.extend(file_patterns)
    
    # Add name pattern if specified
    if args.name_pattern:
        non_hex_patterns.append(args.name_pattern)
    
    # Remove duplicates
    feed_ids = list(set(feed_ids))
    non_hex_patterns = list(set(non_hex_patterns))
    
    # Display criteria
    criteria = []
    if feed_ids:
        if len(feed_ids) <= 3:
            criteria.append(f"{len(feed_ids)} feed IDs: {', '.join(feed_ids)}")
        else:
            # Show the first few feed IDs when there are many
            feed_list = ', '.join(feed_ids[:3])
            criteria.append(f"{len(feed_ids)} feed IDs: {feed_list}, ... and {len(feed_ids)-3} more")
    if non_hex_patterns:
        criteria.append(f"{len(non_hex_patterns)} pattern(s): {', '.join(non_hex_patterns)}")
    
    if criteria:
        print(f"🔍 Using {' and '.join(criteria)} for job matching")
    else:
        print("⚠️ No matching criteria specified - will check all jobs")
    
    # Get all feeds managers
    feeds_managers = chainlink_api.get_all_feeds_managers()
    if not feeds_managers:
        print("❌ No feeds managers found")
        return False
    
    all_matched_feed_ids = set()
    all_matched_patterns = set()
    total_jobs = 0
    total_successful = 0
    total_failed = 0
    jobs_to_reapprove = []
    
    for fm in feeds_managers:
        print(f"\n📋 Processing feeds manager: {fm['name']}")
        
        # Fetch all jobs for this feeds manager
        jobs = chainlink_api.fetch_jobs(fm["id"])
        
        # Find jobs that match our criteria
        matching_jobs, matched_feed_ids, matched_patterns = get_jobs_to_reapprove(
            jobs, feed_ids, non_hex_patterns, args.force
        )
        
        all_matched_feed_ids.update(matched_feed_ids)
        all_matched_patterns.update(matched_patterns)
        
        for job in matching_jobs:
            # Include feed manager info
            job['feeds_manager'] = fm['name']
            jobs_to_reapprove.append(job)
    
    # Display jobs that will be reapproved
    if not jobs_to_reapprove:
        print("\n✅ No jobs need to be reapproved")
        
        # Report unmatched identifiers
        all_unmatched_feed_ids = [feed_id for feed_id in feed_ids if feed_id not in all_matched_feed_ids]
        all_unmatched_patterns = [pattern for pattern in non_hex_patterns if pattern not in all_matched_patterns]
        
        if all_unmatched_feed_ids:
            print(f"\n⚠️ Found {len(all_unmatched_feed_ids)} feed IDs with no matching jobs:")
            for feed_id in sorted(all_unmatched_feed_ids):
                print(f"  - {feed_id}")
                
        if all_unmatched_patterns:
            print(f"\n⚠️ Found {len(all_unmatched_patterns)} patterns with no matching jobs:")
            for pattern in sorted(all_unmatched_patterns):
                print(f"  - {pattern}")
                
        return True
    
    print(f"\n📋 Found {len(jobs_to_reapprove)} jobs to reapprove:")
    print("-" * 80)
    print("{:<15} {:<30} {:<20} {:<15}".format("Spec ID", "Name", "Status", "Feeds Manager"))
    print("-" * 80)
    
    for job in jobs_to_reapprove:
        print("{:<15} {:<30} {:<20} {:<15}".format(
            job['spec_id'][:12] + "..." if len(job['spec_id']) > 15 else job['spec_id'], 
            job['name'][:27] + "..." if len(job['name']) > 30 else job['name'],
            job['status'],
            job['feeds_manager'][:12] + "..." if len(job['feeds_manager']) > 15 else job['feeds_manager']
        ))
    
    # Confirm and execute reapprovals
    if not args.execute:
        print("\n⚠️ Dry run mode. No changes will be made.")
        print("💡 Run with --execute to actually reapprove the jobs.")
        return True
    
    # No confirmation prompt - just proceed with execution when --execute is used
    
    # Actually approve the jobs
    print("\n🔄 Reapproving jobs...")
    
    for job in jobs_to_reapprove:
        try:
            print(f"⏳ Reapproving job spec ID: {job['spec_id']} ({job['name']})")
            success = chainlink_api.approve_job(job['spec_id'], force=True)
            
            if success:
                print(f"✅ Reapproved job: {job['name']}")
                total_successful += 1
            else:
                error_response = getattr(chainlink_api.session, '_last_response', None)
                error_text = ""
                if error_response and hasattr(error_response, 'text'):
                    error_text = error_response.text
                
                print(f"❌ Failed to reapprove job: {job['name']}")
                print(f"   Error: {error_text}")
                
                # Handle bridge errors
                if "bridge check: not all bridges exist" in error_text:
                    print("🔄 Attempting to create missing bridges...")
                    if create_missing_bridges(chainlink_api, error_text, args.service, args.node, log_to_console=True):
                        print("🔄 Retrying job approval...")
                        if chainlink_api.approve_job(job['spec_id'], force=True):
                            print(f"✅ Successfully reapproved job after creating bridges: {job['name']}")
                            total_successful += 1
                            continue
                
                total_failed += 1
        except Exception as e:
            print(f"❌ Exception when approving job {job['spec_id']}: {str(e)}")
            total_failed += 1
    
    # Print summary
    print("\n" + "=" * 60)
    print(f"📊 Job Reapproval Summary:")
    print(f"  Total jobs processed: {len(jobs_to_reapprove)}")
    print(f"  Successfully reapproved: {total_successful}")
    print(f"  Failed to reapprove: {total_failed}")
    
    return True

def get_jobs_to_reapprove(jobs, feed_ids, patterns, force=False):
    """
    Identify Jobs to Reapprove based on feed IDs or patterns
    
    Returns:
    - Tuple of (jobs_to_reapprove, matched_feed_ids, matched_patterns)
    """
    jobs_to_reapprove = []
    matched_feed_ids = set()
    matched_patterns = set()
    
    for job in jobs:
        job_name = job.get("name", "").lower()
        job_status = job.get("status", "").upper()
        
        # Determine if this job should be considered
        should_process = False
        
        # Force option overrides status checks
        if force:
            should_process = True
        # Check for pending update
        elif job.get('pendingUpdate', False):
            should_process = True
        # Check for cancelled status
        elif job_status in ["CANCELLED", "CANCELED"]:
            should_process = True
            
        if not should_process:
            continue
            
        # Check if job matches our criteria
        matched = False
        match_reason = None
        
        # If no criteria, match all jobs
        if not feed_ids and not patterns:
            matched = True
            match_reason = "all jobs"
        else:
            # Try to match feed IDs
            for feed_id in feed_ids:
                if feed_id in job_name:
                    matched = True
                    match_reason = f"feed ID {feed_id}"
                    matched_feed_ids.add(feed_id)
                    break
                    
            # If no feed ID matched, try patterns
            if not matched and patterns:
                for pattern in patterns:
                    if pattern.lower() in job_name:
                        matched = True
                        match_reason = f"pattern '{pattern}'"
                        matched_patterns.add(pattern)
                        break
        
        if matched:
            # Get the latest spec for this job
            latest_spec = None
            if job.get('specs'):
                # Sort specs by version (highest first)
                sorted_specs = sorted(job['specs'], key=lambda x: x.get('version', 0), reverse=True)
                if sorted_specs:
                    latest_spec = sorted_specs[0]
                    
            if latest_spec:
                jobs_to_reapprove.append({
                    'id': job.get('id', 'Unknown'),
                    'name': job.get('name', 'Unknown'),
                    'spec_id': latest_spec.get('id', 'Unknown'),
                    'status': job.get('status', 'Unknown'),
                    'match_reason': match_reason
                })
    
    return jobs_to_reapprove, matched_feed_ids, matched_patterns

def extract_feed_id(job):
    """
    Extract feed ID from job name (helper function)
    
    Parameters:
    - job: Job data
    
    Returns:
    - Feed ID or None if not found
    """
    # Common pattern: Look for 0x followed by hex characters in the job name
    name = job.get('name', '')
    import re
    match = re.search(r'(0x[0-9a-fA-F]+)', name)
    if match:
        return match.group(1)
    return None