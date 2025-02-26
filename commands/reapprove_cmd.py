#!/usr/bin/env python3
import json
import sys
from core.chainlink_api import ChainlinkAPI
from utils.helpers import confirm_action
from utils.bridge_ops import create_missing_bridges, check_bridge_config

def register_arguments(subparsers):
    """
    Register the reapprove command arguments
    
    Parameters:
    - subparsers: Subparsers object from argparse
    """
    parser = subparsers.add_parser('reapprove', help='Reapprove cancelled jobs')
    parser.add_argument('--service', required=True, help='Service name (e.g., bootstrap, ocr)')
    parser.add_argument('--node', required=True, help='Node name (e.g., arbitrum, ethereum)')
    parser.add_argument('--name-pattern', help='Pattern to match job names (case-insensitive)')
    parser.add_argument('--feed-ids', nargs='+', help='List of feed IDs to reapprove')
    parser.add_argument('--feed-ids-file', help='File containing feed IDs to reapprove (one per line)')
    parser.add_argument('--execute', action='store_true', help='Execute changes')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    
    return parser

def execute(args, chainlink_api):
    """
    Execute the reapprove command
    
    Parameters:
    - args: Command line arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    
    Returns:
    - int: Exit code (0 for success, non-zero for errors)
    """
    print(f"🔍 Reapproving jobs on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    # Collect feed IDs if specified
    feed_ids = set()
    
    if args.feed_ids:
        feed_ids.update([feed_id.lower() for feed_id in args.feed_ids])
        
    if args.feed_ids_file:
        try:
            with open(args.feed_ids_file, 'r') as f:
                file_feed_ids = [line.strip().lower() for line in f if line.strip()]
                feed_ids.update(file_feed_ids)
        except Exception as e:
            print(f"❌ Error reading feed IDs file: {str(e)}")
            return 1
    
    # Process each feeds manager
    feeds_managers = chainlink_api.get_all_feeds_managers()
    
    if not feeds_managers:
        print("❌ No feeds managers found")
        return 1
    
    jobs_to_reapprove = []
    
    for fm in feeds_managers:
        print(f"\n📋 Processing feeds manager: {fm['name']}")
        
        # Fetch all jobs for this feeds manager
        jobs = chainlink_api.fetch_jobs(fm["id"])
        
        for job in jobs:
            # Default to false for jobs without a pendingUpdate field
            if not job.get('pendingUpdate', False):
                continue
                
            # Apply name filter if specified
            if args.name_pattern and args.name_pattern.lower() not in job.get('name', '').lower():
                continue
                
            # Apply feed ID filter if specified
            if feed_ids:
                job_feed_id = extract_feed_id(job)
                if not job_feed_id or job_feed_id.lower() not in feed_ids:
                    continue
            
            # Find the latest spec
            latest_spec = None
            if job.get('specs'):
                # Sort specs by version (highest first)
                sorted_specs = sorted(job['specs'], key=lambda x: x.get('version', 0), reverse=True)
                if sorted_specs:
                    latest_spec = sorted_specs[0]
            
            if latest_spec:
                job_details = {
                    'id': job.get('id', 'Unknown'),
                    'name': job.get('name', 'Unknown'),
                    'spec_id': latest_spec.get('id', 'Unknown'),
                    'status': job.get('status', 'Unknown')
                }
                jobs_to_reapprove.append(job_details)
    
    # Display jobs that will be reapproved
    if not jobs_to_reapprove:
        print("\n✅ No jobs need to be reapproved")
        return 0
        
    print(f"\n📋 Found {len(jobs_to_reapprove)} jobs to reapprove:")
    print("-" * 80)
    print("{:<44} {:<30} {:<12}".format("Job ID", "Name", "Status"))
    print("-" * 80)
    
    for job in jobs_to_reapprove:
        print("{:<44} {:<30} {:<12}".format(
            job['id'], 
            job['name'] if len(job['name']) < 27 else job['name'][:24] + "...",
            job['status']
        ))
    
    # Confirm and execute reapprovals
    if not args.execute:
        print("\n⚠️ Dry run mode. No changes will be made.")
        print("💡 Run with --execute to actually reapprove the jobs.")
        return 0
        
    if not args.yes and not confirm_action("Do you want to reapprove these jobs?"):
        print("❌ Operation cancelled by user")
        return 0
    
    # Actually approve the jobs
    print("\n🔄 Reapproving jobs...")
    
    success_count = 0
    error_count = 0
    
    for job in jobs_to_reapprove:
        spec_id = job['spec_id']
        print(f"  Reapproving {job['name']} (Spec ID: {spec_id})...")
        
        try:
            success = chainlink_api.approve_job(spec_id, force=True)
            
            if success:
                print(f"  ✅ Successfully reapproved {job['name']}")
                success_count += 1
            else:
                # Check the error response for bridge-related issues
                error_response = getattr(chainlink_api.session, '_last_response', None)
                if error_response and hasattr(error_response, 'text'):
                    error_text = error_response.text
                    if "bridge check: not all bridges exist" in error_text:
                        print(f"  🔄 Bridge error detected. Attempting to create missing bridges...")
                        
                        # Create missing bridges and retry
                        if create_missing_bridges(chainlink_api, error_text, args.service, args.node, log_to_console=True):
                            print(f"  ✅ Missing bridges created successfully. Retrying approval...")
                            
                            # Retry approval
                            retry_success = chainlink_api.approve_job(spec_id, force=True)
                            if retry_success:
                                print(f"  ✅ Successfully reapproved {job['name']} after adding missing bridges")
                                success_count += 1
                                continue
                            else:
                                print(f"  ❌ Failed to reapprove {job['name']} even after adding bridges")
                        else:
                            print(f"  ❌ Failed to create missing bridges for {job['name']}")
                            
                            # Check if bridges exist in other groups
                            missing_bridges, other_group_bridges = check_bridge_config(error_text, args.service, args.node, log_to_console=True)
                            
                            if missing_bridges:
                                print(f"  ❌ These bridges are not configured in any group: {', '.join(missing_bridges)}")
                                
                            if other_group_bridges:
                                print(f"  ℹ️ Some bridges exist in other bridge groups:")
                                for bridge, groups in other_group_bridges:
                                    print(f"    - {bridge} found in groups: {', '.join(groups)}")
                
                # If we get here, the job approval failed
                print(f"  ❌ Failed to reapprove {job['name']}")
                error_count += 1
                
        except Exception as e:
            print(f"  ❌ Exception when reapproving {job['name']}: {str(e)}")
            error_count += 1
    
    # Summary
    print("\n" + "=" * 60)
    print(f"Reapproval completed: {success_count} successful, {error_count} failed")
    print("=" * 60)
    
    return 0 if error_count == 0 else 1

def extract_feed_id(job):
    """
    Extract feed ID from a job
    
    Parameters:
    - job: Job data from the API
    
    Returns:
    - Feed ID string or None if not found
    """
    name = job.get('name', '')
    
    # Some jobs have the feed ID in the name with a prefix like "feed-id:"
    for prefix in ['feed-id:', 'feed_id:', 'feedid:']:
        if prefix in name.lower():
            parts = name.split(prefix, 1)
            if len(parts) > 1:
                # The feed ID is after the prefix, get the first word
                feed_id = parts[1].strip().split()[0].strip()
                return feed_id
                
    # For jobs without a clear feed ID marker, just use the name
    # This relies on the feed_ids provided by the user
    return name