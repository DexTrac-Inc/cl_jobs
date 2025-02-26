#!/usr/bin/env python3
import json
from utils.helpers import filter_jobs

def register_arguments(subparsers):
    """
    Register the list command arguments
    
    Parameters:
    - subparsers: Subparsers object from argparse
    """
    parser = subparsers.add_parser('list', help='List Chainlink jobs with their status')
    parser.add_argument('--service', required=True, help='Service name (e.g. bootstrap, ocr)')
    parser.add_argument('--node', required=True, help='Node name (e.g. arbitrum, ethereum)')
    parser.add_argument('--status', help='Filter jobs by status (e.g. APPROVED, CANCELLED, PENDING)')
    parser.add_argument('--has-updates', action='store_true', help='Show only jobs with pending updates')
    parser.add_argument('--output', help='Save output to JSON file')
    parser.add_argument('--format', choices=['table', 'json'], default='table', help='Output format (default: table)')
    parser.add_argument('--full-width', action='store_true', help='Do not restrict table width for wide terminals')
    parser.add_argument('--sort', choices=['name', 'id', 'spec_id', 'updates'], default='name', 
                    help='Sort column (default: name)')
    parser.add_argument('--reverse', action='store_true', help='Reverse sort order')
    
    return parser

def execute(args, chainlink_api):
    """
    Execute the list command
    
    Parameters:
    - args: Parsed arguments
    - chainlink_api: Initialized ChainlinkAPI instance
    """
    print("\n" + "=" * 60)
    print(f"🔍 Listing jobs on {args.service.upper()} {args.node.upper()} ({chainlink_api.node_url})")
    
    # Apply any filters to the description
    filter_desc = []
    if args.status:
        filter_desc.append(f"status={args.status.upper()}")
    if args.has_updates:
        filter_desc.append("with pending updates")
    
    if filter_desc:
        print(f"🔍 Filtering jobs: {', '.join(filter_desc)}")
    
    # Show sorting info
    sort_desc = f"sorted by {args.sort}"
    if args.reverse:
        sort_desc += " (reversed)"
    print(f"🔍 {sort_desc}")
    
    # Authenticate with the Chainlink Node
    if not chainlink_api.authenticate():
        return False
    
    # Get all feeds managers
    feeds_managers = chainlink_api.get_all_feeds_managers()
    if not feeds_managers:
        print(f"✅ No feeds managers found")
        return True
    
    all_jobs = []
    
    for fm in feeds_managers:
        print(f"🔍 Fetching job proposals for {fm['name']}")

        jobs = chainlink_api.fetch_jobs(fm["id"])
        filtered_jobs = filter_jobs(jobs, args.status, args.has_updates)
        
        # Add manager info to each job for JSON output
        for job in filtered_jobs:
            job["manager"] = fm["name"]
            job["manager_id"] = fm["id"]
        
        all_jobs.extend(filtered_jobs)
        
        # Display table output if requested
        if args.format == 'table':
            display_jobs_table(filtered_jobs, fm['name'], args)
    
    # Generate JSON output if requested
    if args.format == 'json' or args.output:
        json_output = {
            "service": args.service,
            "node": args.node,
            "url": chainlink_api.node_url,
            "total_jobs": len(all_jobs),
            "jobs": all_jobs
        }
        
        if args.format == 'json':
            print(json.dumps(json_output, indent=2))
        
        if args.output:
            try:
                with open(args.output, 'w') as outfile:
                    json.dump(json_output, outfile, indent=2)
                print(f"\n✅ Output saved to {args.output}")
            except Exception as e:
                print(f"\n❌ Error saving output to file: {e}")
    
    # Print summary
    print("\n" + "=" * 60)
    print(f"📊 Total Jobs: {len(all_jobs)}")
    
    return True


def display_jobs_table(jobs, manager_name, args):
    """
    Display jobs in a formatted table
    
    Parameters:
    - jobs: List of jobs to display
    - manager_name: Name of the feeds manager
    - args: Command line arguments
    """
    if not jobs:
        print(f"✅ No matching jobs found for {manager_name}")
        return
    
    # Count jobs by status
    status_counts = {}
    jobs_by_status = {}
    
    for job in jobs:
        status = job.get("status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
        
        if status not in jobs_by_status:
            jobs_by_status[status] = []
        
        jobs_by_status[status].append(job)
    
    # Print status summary
    print(f"\n📊 Job Status Summary for {manager_name}:")
    for status, count in status_counts.items():
        print(f"  {status}: {count} jobs")
    
    # Determine column widths based on whether full-width is enabled
    if args.full_width:
        name_width = 200  # Very wide to accommodate any name length
        table_width = 250
    else:
        name_width = 90   # Default width for standard terminals
        table_width = 120
    
    # Define sort key functions
    sort_keys = {
        'name': lambda j: j.get("name", "").lower(),
        'id': lambda j: int(j.get("id", "0")),
        'spec_id': lambda j: int(j.get("latestSpec", {}).get("id", "0")),
        'updates': lambda j: j.get("pendingUpdate", False)
    }
    
    # Get the appropriate sort key function
    sort_key = sort_keys.get(args.sort, sort_keys['name'])
    
    # Process each status group
    for status, status_jobs in sorted(jobs_by_status.items()):
        print(f"\n{status} JOBS ({len(status_jobs)}):")
        print("-" * table_width)
        print("{:<5} {:<{name_width}} {:<15} {:<10}".format(
            "ID", "Name", "Updates", "Spec ID", name_width=name_width))
        print("-" * table_width)
        
        # Sort jobs using the selected sort key and direction
        status_jobs.sort(key=sort_key, reverse=args.reverse)
        
        # Print job info for this status
        for job in status_jobs:
            job_id = job.get("id", "N/A")
            job_name = job.get("name", "N/A")
            has_updates = "Yes" if job.get("pendingUpdate", False) else "No"
            spec_id = job.get("latestSpec", {}).get("id", "N/A")
            
            # Only truncate if not in full-width mode
            if not args.full_width and len(job_name) > name_width:
                truncated_name = job_name[:name_width-3] + "..."
            else:
                truncated_name = job_name
            
            print("{:<5} {:<{name_width}} {:<15} {:<10}".format(
                job_id, truncated_name, has_updates, spec_id, name_width=name_width
            ))