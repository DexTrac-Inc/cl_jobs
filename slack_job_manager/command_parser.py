#!/usr/bin/env python3
import re
import shlex
import argparse
from typing import Dict, List, Optional, Tuple, Any

class SlackCommandParser:
    """Parse Slack messages into job manager commands"""
    
    COMMAND_PATTERNS = {
        # Format: command: regex
        "list": r"(?:show|list|get)\s+jobs",
        "cancel": r"(?:cancel|delete|remove)\s+(?:job|jobs)",
        "reapprove": r"(?:reapprove|approve|restore)\s+(?:job|jobs)",
        "bridge_list": r"(?:show|list|get)\s+bridges",
        "bridge_create": r"(?:create|add)\s+bridge",
        "bridge_update": r"(?:update|edit)\s+bridge",
        "bridge_delete": r"(?:delete|remove)\s+bridge",
        "help": r"help|commands|usage"
    }
    
    def __init__(self):
        self.parsers = self._create_parsers()
    
    def _create_parsers(self) -> Dict[str, argparse.ArgumentParser]:
        """Create argument parsers for each command"""
        parsers = {}
        
        # List command
        list_parser = argparse.ArgumentParser(prog="list", add_help=False)
        list_parser.add_argument("--service", required=True, help="Service name (e.g., bootstrap, ocr)")
        list_parser.add_argument("--node", required=True, help="Node name (e.g., arbitrum, ethereum)")
        list_parser.add_argument("--status", help="Filter jobs by status (e.g., APPROVED, CANCELLED, PENDING)")
        list_parser.add_argument("--has-updates", action="store_true", help="Show only jobs with pending updates")
        list_parser.add_argument("--sort", default="name", help="Sort by column: 'name' (default), 'id', 'spec_id', or 'updates'")
        list_parser.add_argument("--reverse", action="store_true", help="Reverse the sort order")
        parsers["list"] = list_parser
        
        # Cancel command
        cancel_parser = argparse.ArgumentParser(prog="cancel", add_help=False)
        cancel_parser.add_argument("--service", required=True, help="Service name (e.g., bootstrap, ocr)")
        cancel_parser.add_argument("--node", required=True, help="Node name (e.g., arbitrum, ethereum)")
        cancel_parser.add_argument("--address", help="Contract address to cancel")
        cancel_parser.add_argument("--name-pattern", help="Pattern to match job names")
        parsers["cancel"] = cancel_parser
        
        # Reapprove command
        reapprove_parser = argparse.ArgumentParser(prog="reapprove", add_help=False)
        reapprove_parser.add_argument("--service", required=True, help="Service name (e.g., bootstrap, ocr)")
        reapprove_parser.add_argument("--node", required=True, help="Node name (e.g., arbitrum, ethereum)")
        reapprove_parser.add_argument("--address", help="Contract address to reapprove")
        reapprove_parser.add_argument("--name-pattern", help="Pattern to match job names")
        parsers["reapprove"] = reapprove_parser
        
        # Bridge List command
        bridge_list_parser = argparse.ArgumentParser(prog="bridge-list", add_help=False)
        bridge_list_parser.add_argument("--service", required=True, help="Service name (e.g., bootstrap, ocr)")
        bridge_list_parser.add_argument("--node", required=True, help="Node name (e.g., arbitrum, ethereum)")
        parsers["bridge_list"] = bridge_list_parser
        
        # Bridge Create command
        bridge_create_parser = argparse.ArgumentParser(prog="bridge-create", add_help=False)
        bridge_create_parser.add_argument("--service", required=True, help="Service name (e.g., bootstrap, ocr)")
        bridge_create_parser.add_argument("--node", required=True, help="Node name (e.g., arbitrum, ethereum)")
        bridge_create_parser.add_argument("--name", required=True, help="Bridge name")
        bridge_create_parser.add_argument("--url", required=True, help="Bridge URL")
        parsers["bridge_create"] = bridge_create_parser
        
        # Bridge Update command
        bridge_update_parser = argparse.ArgumentParser(prog="bridge-update", add_help=False)
        bridge_update_parser.add_argument("--service", required=True, help="Service name (e.g., bootstrap, ocr)")
        bridge_update_parser.add_argument("--node", required=True, help="Node name (e.g., arbitrum, ethereum)")
        bridge_update_parser.add_argument("--name", required=True, help="Bridge name")
        bridge_update_parser.add_argument("--url", required=True, help="New bridge URL")
        parsers["bridge_update"] = bridge_update_parser
        
        # Bridge Delete command
        bridge_delete_parser = argparse.ArgumentParser(prog="bridge-delete", add_help=False)
        bridge_delete_parser.add_argument("--service", required=True, help="Service name (e.g., bootstrap, ocr)")
        bridge_delete_parser.add_argument("--node", required=True, help="Node name (e.g., arbitrum, ethereum)")
        bridge_delete_parser.add_argument("--name", required=True, help="Bridge name")
        parsers["bridge_delete"] = bridge_delete_parser
        
        return parsers
    
    def detect_command(self, text: str) -> Optional[str]:
        """
        Detect which command is being requested in a message
        
        Args:
            text: The message text
            
        Returns:
            The command name or None if no command detected
        """
        text = text.lower().strip()
        
        # Check for command pattern matches
        for cmd, pattern in self.COMMAND_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                return cmd
                
        return None
    
    def parse_arguments(self, command: str, text: str) -> Dict[str, Any]:
        """
        Parse arguments for a command from text
        
        Args:
            command: The command name
            text: The message text
            
        Returns:
            Dictionary of parsed arguments
        """
        if command not in self.parsers:
            return {}
            
        parser = self.parsers[command]
        args = {}
        
        # First check for "on [node] [service]" pattern in all commands
        on_pattern_match = re.search(r'on\s+(\w+)\s+(\w+)', text, re.IGNORECASE)
        if on_pattern_match:
            # First word after "on" is typically the node, second is the service
            node = on_pattern_match.group(1)
            service = on_pattern_match.group(2)
            args["node"] = node
            args["service"] = service
        
        # Check for inverted format "on [service] [node]" as well - this helps with ambiguity
        # We might need to adjust this logic based on how users typically phrase commands
        
        # Extract potential arguments with regex based on command
        if command == "cancel" or command == "reapprove":
            # Look for job ID in the command
            job_id_match = re.search(r'(?:--job-id|-j)\s+(\d+)', text)
            if job_id_match:
                job_id = job_id_match.group(1)
                args["job_id"] = job_id
            
            # Look for contract addresses (both with and without 0x prefix)
            # Look for all hex addresses, not just 40 characters (some might be different lengths)
            address_matches = re.findall(r'(0x[a-fA-F0-9]{6,})', text)
            
            # Look for explicit feed_ids flag
            feed_ids_match = re.search(r'(?:--feed-ids)\s+(0x[a-fA-F0-9]{6,})', text)
            if feed_ids_match:
                args["feed_ids"] = [feed_ids_match.group(1)]
            # If no explicit flag but we found addresses in text
            elif address_matches:
                # Process all found addresses to normalize case
                normalized_addresses = []
                for addr in address_matches:
                    # Convert to lowercase to ensure case-insensitive matching
                    # The get_jobs_to_cancel function converts to lowercase too
                    normalized_addresses.append(addr.lower())
                
                # Use the first address found
                args["address"] = normalized_addresses[0]
                # Also set feed_ids for both cancel and reapprove
                args["feed_ids"] = normalized_addresses
            
            # Look for name patterns in quotes
            name_pattern_match = re.search(r'(?:--name-pattern|-n)\s+"([^"]+)"', text)
            if not name_pattern_match:
                name_pattern_match = re.search(r"(?:--name-pattern|-n)\s+'([^']+)'", text)
            # Also look for name pattern without explicit flag but in quotes
            if not name_pattern_match:
                name_pattern_match = re.search(r'"([^"]+)"', text)
                if not name_pattern_match:
                    name_pattern_match = re.search(r"'([^']+)'", text)
            
            name_pattern = name_pattern_match.group(1) if name_pattern_match else None
            
            # Look for explicit service and node flags
            service_match = re.search(r'(?:--service|-s)\s+(\w+)', text)
            if service_match:
                args["service"] = service_match.group(1)
            
            node_match = re.search(r'(?:--node|-n)\s+(\w+)', text)
            if node_match:
                args["node"] = node_match.group(1)
            
            # Look for execute flag
            if re.search(r'(?:--execute|-e|-x)\b', text):
                args["execute"] = True
            
            if name_pattern:
                args["name_pattern"] = name_pattern
                
            # If we didn't find service/node via flags or "on" pattern, look for common formats
            if "service" not in args or "node" not in args:
                # Try to extract from format like "reapprove job on ethereum bootstrap"
                service_node_match = re.search(r'(?:on|for|in|from)\s+(\w+)\s+(\w+)', text, re.IGNORECASE)
                if service_node_match:
                    # Assume first is node, second is service (most common case)
                    if "node" not in args:
                        args["node"] = service_node_match.group(1)
                    if "service" not in args:
                        args["service"] = service_node_match.group(2)
            
            # Validate we have required arguments
            if not args.get("service") or not args.get("node"):
                # Try harder - look for any two words that might be service/node
                words = re.findall(r'\b(\w+)\b', text)
                # Filter out common words and commands
                common_words = {'job', 'jobs', 'bridge', 'bridges', 'list', 'show', 'get', 'delete', 'remove', 
                               'cancel', 'reapprove', 'on', 'for', 'in', 'from', 'the', 'a', 'an'}
                potential_names = [w for w in words if w.lower() not in common_words]
                
                # If we have at least two words that aren't common, use them
                if len(potential_names) >= 2 and "service" not in args and "node" not in args:
                    args["node"] = potential_names[0]
                    args["service"] = potential_names[1]
                
            return args
            
        # For bridge commands, handle natural language patterns
        elif command.startswith("bridge_"):
            # Extract bridge name from text
            bridge_name_match = re.search(r'bridge\s+(?:named|called|named|with name)?\s*["\']?([a-zA-Z0-9_-]+)["\']?', text, re.IGNORECASE)
            if bridge_name_match:
                args["name"] = bridge_name_match.group(1)
            
            # Extract URL for create/update
            url_match = re.search(r'(?:url|address|endpoint)\s+["\']?(https?://[^\s"\']+)["\']?', text, re.IGNORECASE)
            if url_match:
                args["url"] = url_match.group(1)
                
            # Continue with traditional argument parsing
        
        # For all commands, also try traditional CLI-style arguments
        try:
            # Get everything after the command name
            arg_str = ""
            for pattern in self.COMMAND_PATTERNS.values():
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    start = match.end()
                    arg_str = text[start:].strip()
                    break
            
            # Split into tokens respecting quotes
            try:
                tokens = shlex.split(arg_str)
            except ValueError:
                # Handle unclosed quotes
                tokens = arg_str.split()
                
            # Parse with appropriate parser
            try:
                parsed_args, _ = parser.parse_known_args(tokens)
                # Update our args dictionary with parsed args, preserving any values we found via regex
                for key, value in vars(parsed_args).items():
                    if value is not None and (key not in args or args[key] is None):
                        args[key] = value
            except Exception:
                # If parsing fails, we'll rely on the regex-based extraction
                pass
                
        except Exception:
            # If there's any error in CLI-style parsing, still return what we found via regex
            pass
            
        return args
    
    def get_help_text(self, command: str = None) -> str:
        """Get help text for commands"""
        if command and command in self.parsers:
            # Format help for specific command
            parser = self.parsers[command]
            help_text = f"*Usage for {command}:*\n"
            
            # Add arguments
            for action in parser._actions:
                if action.dest != "help":
                    opt_str = ", ".join(action.option_strings) if action.option_strings else action.dest
                    required = " (required)" if action.required else ""
                    default = f" (default: {action.default})" if action.default is not None else ""
                    help_text += f"• `{opt_str}{required}{default}`: {action.help}\n"
                    
            return help_text
        else:
            # General help
            help_text = "*Available commands:*\n"
            help_text += "• `list`: List and filter jobs\n"
            help_text += "• `cancel`: Cancel jobs based on criteria\n"
            help_text += "• `reapprove`: Reapprove cancelled jobs\n"
            help_text += "• `bridge-list`: List bridges\n"
            help_text += "• `bridge-create`: Create a new bridge\n"
            help_text += "• `bridge-update`: Update an existing bridge\n"
            help_text += "• `bridge-delete`: Delete a bridge\n\n"
            
            help_text += "*Examples:*\n"
            help_text += "• `list --service bootstrap --node ethereum --status APPROVED`\n"
            help_text += "• `cancel --service bootstrap --node ethereum --address 0x123...`\n"
            help_text += "• `reapprove --service bootstrap --node ethereum --address 0x123...`\n"
            help_text += "• `bridge-list --service ocr --node bsc`\n"
            
            return help_text