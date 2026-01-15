#!/usr/bin/env python3
"""
VM Actions Menu - Shows available actions for a selected VM/Container
"""

import json
import sys
import ssl
import os
import urllib.request
from pathlib import Path

def get_usage_file():
    """Get path to action usage data file"""
    data_dir = os.environ.get('alfred_workflow_data', '')
    # Only use Alfred's data dir if it's for our workflow
    if data_dir and 'com.pve.manager' in data_dir:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        return Path(data_dir) / 'action_usage.json'
    return Path(__file__).parent.absolute() / 'action_usage.json'

def load_action_usage():
    """Load action usage counts from file"""
    usage_file = get_usage_file()
    if usage_file.exists():
        try:
            with open(usage_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}

def get_config():
    """Get config from environment variables (set by Alfred at runtime)"""
    # Alfred passes workflow variables as environment variables
    # This ensures configuration changes in Alfred's UI are respected
    
    def is_true(value, default='true'):
        """Check if a value is truthy - handles '1', 'true', True, etc."""
        if value is None or value == '':
            value = default
        return str(value).lower() in ('1', 'true', 'yes')
    
    return {
        'host': os.environ.get('PVE_HOST', ''),
        'port': os.environ.get('PVE_PORT', '8006'),
        'token_id': os.environ.get('PVE_TOKEN_ID', ''),
        'token_secret': os.environ.get('PVE_TOKEN_SECRET', ''),
        # Action toggles - read from environment variables
        # Default to true if not set (so actions show by default)
        'action_power': is_true(os.environ.get('ACTION_POWER')),
        'action_ssh': is_true(os.environ.get('ACTION_SSH')),
        'action_snapshot': is_true(os.environ.get('ACTION_SNAPSHOT')),
        'action_rollback': is_true(os.environ.get('ACTION_ROLLBACK')),
        'action_webui': is_true(os.environ.get('ACTION_WEBUI')),
        'action_console': is_true(os.environ.get('ACTION_CONSOLE')),
    }

def get_vm_status(node, vmtype, vmid):
    """Get current status of a VM"""
    try:
        cfg = get_config()
        url = f"https://{cfg['host']}:{cfg['port']}/api2/json/nodes/{node}/{vmtype}/{vmid}/status/current"
        
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        
        headers = {
            'Authorization': f"PVEAPIToken={cfg['token_id']}={cfg['token_secret']}"
        }
        
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('data', {}).get('status', 'unknown')
    except:
        return 'unknown'

def main():
    items = []
    cfg = get_config()
    
    # Try to get VM details from environment variables (new method)
    env_node = os.environ.get('node')
    env_type = os.environ.get('type')
    env_vmid = os.environ.get('vmid')
    env_name = os.environ.get('name')
    
    query = ""
    
    if env_node and env_type and env_vmid:
        # We have context in variables!
        node = env_node
        vmtype = env_type
        vmid = env_vmid
        name = env_name or f"VM {vmid}"
        arg = f"{node}:{vmtype}:{vmid}:{name}"
        
        # The argument is now the search query (filter)
        query = sys.argv[1] if len(sys.argv) > 1 else ''
        if query in ['{query}', '(null)', 'null']:
            query = ""
            
    else:
        # Fallback to legacy parsing (parsing the argument string)
        # Parse arg: node:type:vmid:name
        arg = sys.argv[1] if len(sys.argv) > 1 else ''
        
        # If arg looks like it has a filter appended (e.g. colon count mismatch or known structure)
        # It's hard to distinguish "pve:lxc:107:dockers" (name=dockers) vs "pve:lxc:107:docker" + "s"
        # Since we are switching to variables, we assume the legacy path just parses what it gets.
        
        parts = arg.split(':')
        if len(parts) < 4:
            items.append({
                'title': '❌  Invalid selection',
                'subtitle': f'Unexpected format: {arg}',
                'valid': False
            })
            print(json.dumps({'items': items}))
            return
        
        node, vmtype, vmid, name = parts[0], parts[1], parts[2], ':'.join(parts[3:])
        # In legacy mode, we don't support filtering because we can't separate the query from the name easily
        query = ""
    type_emoji = '📦' if vmtype == 'lxc' else '🖥️'
    type_label = 'Container' if vmtype == 'lxc' else 'VM'
    
    # Get current status
    status = get_vm_status(node, vmtype, vmid)
    is_running = status == 'running'
    
    # Build action list based on status and config
    actions = []
    
    # Power actions (based on running state)
    if cfg.get('action_power', True):
        if is_running:
            actions.extend([
                ('🔄', 'Restart', f'restart:{arg}', f'Reboot this {type_label}'),
                ('⏻', 'Shutdown', f'shutdown:{arg}', 'Graceful shutdown (ACPI)'),
                ('⏹️', 'Stop', f'stop:{arg}', 'Force stop (like pulling power)'),
            ])
        else:
            actions.append(('▶️', 'Start', f'start:{arg}', f'Power on this {type_label}'))
    
    # SSH - only when running
    if cfg.get('action_ssh', True) and is_running:
        actions.append(('🔗', 'SSH', f'ssh:{arg}', 'Connect via SSH in Terminal'))
    
    # Web UI - always available (can view stopped VMs)
    if cfg.get('action_webui', True):
        actions.append(('🌐', 'Web UI', f'webui:{arg}', 'Open in Proxmox web interface'))
    
    # Console - only when running
    if cfg.get('action_console', True) and is_running:
        actions.append(('🖥️', 'Console', f'console:{arg}', 'Open web console directly'))
    
    # Snapshot - always available (can snapshot stopped VMs too)
    if cfg.get('action_snapshot', True):
        actions.append(('📸', 'Snapshot', f'snapshot:{arg}', 'Create timestamped snapshot'))
    
    # Rollback - always available
    if cfg.get('action_rollback', True):
        actions.append(('⏪', 'Rollback', f'rollback:{arg}', 'Rollback to a snapshot'))
    
    # Sort actions by usage count (most used first)
    action_usage = load_action_usage()
    # Extract action name from arg (e.g., "restart:node:..." -> "restart")
    actions.sort(key=lambda x: -action_usage.get(x[2].split(':')[0], 0))
    
    # Filter actions if query exists
    # Special handling for "Description: <desc>"
    snapshot_desc = ""
    if query and query.lower().startswith('description:'):
        # We are in snapshot description mode
        snapshot_desc = query[12:].strip() # Remove "description:" prefix
        
        # Override actions to just show the "Create Snapshot" action with the description
        actions = []
        if cfg.get('action_snapshot', True):
             # arg format: snapshot_desc:node:type:vmid:name:description
             # We need to escape description if it has colons, or put it last and handle parsing carefully
             # The existing parser in run_action joins parts[4:] for name.
             # We should use a new action 'snapshot_with_desc' and pass description.
             # run_action.py needs update to handle this.
             # Let's use a delimiter for description? Or assume last part is description?
             # Let's do: snapshot_with_desc:node:type:vmid:name:::description
             # And update run_action to split by ':::'
             # Actually, simpler: define action as 'snapshot_with_desc'
             # And in run_action, if action is that, look for description.
             
             # Arg construction:
             # We will use a special separator that is unlikely to be in the name.
             # But let's stick to the existing loop structure slightly.
             desc_display = snapshot_desc if snapshot_desc else "(type description)"
             actions.append(('📸', 'Create Snapshot', f'snapshot_with_desc:{arg}:::{snapshot_desc}', f'With description: {desc_display}'))
    
    elif query:
        query = query.lower().strip()
        filtered_actions = []
        for action in actions:
            # action tuple: (emoji, label, arg, desc)
            label_lower = action[1].lower()
            desc_lower = action[3].lower()
            
            if query in label_lower or query in desc_lower:
                # Calculate match score: starts with = 2, contains = 1
                match_score = 0
                if label_lower.startswith(query):
                    match_score = 2  # Best: starts with query
                elif query in label_lower:
                    match_score = 1  # Good: contains query
                
                filtered_actions.append((action, match_score))
        
        # Sort by match score (descending), then by usage count (descending)
        action_usage = load_action_usage()
        filtered_actions.sort(key=lambda x: (
            -x[1],  # Match score (higher = better match)
            -action_usage.get(x[0][2].split(':')[0], 0)  # Usage count
        ))
        
        # Extract just the actions
        actions = [a[0] for a in filtered_actions]
    
    # Build items from actions
    for emoji, label, action_arg, desc in actions:
        item = {
            'title': f'{emoji}  {label}',
            'subtitle': desc,
            'arg': action_arg,
            'valid': True,
            'icon': {'path': 'icon.png'}
        }
        
        # Add autocomplete for Snapshot to allow entering description
        if label == 'Snapshot':
            item['autocomplete'] = 'Description: '
            
        # Add modifier for snapshot to enable RAM snapshot with ⌘+Enter
        if (label == 'Snapshot' or label == 'Create Snapshot') and is_running:
            # Determine the action for the modifier
            if label == 'Create Snapshot':
                # We are in description mode
                # The arg is already built as 'snapshot_with_desc:{arg}:::{desc}'
                # We need to construct 'snapshot_ram_with_desc:{arg}:::{desc}'
                # extract base arg and desc
                parts = action_arg.split(':', 1) # split off 'snapshot_with_desc'
                suffix = parts[1]
                ram_arg = f"snapshot_ram_with_desc:{suffix}"
            else:
                # Normal mode
                ram_arg = f'snapshot_ram:{arg}'
            
            item['mods'] = {
                'cmd': {
                    'subtitle': '📸 Create snapshot with RAM state',
                    'arg': ram_arg,
                    'valid': True
                }
            }
        items.append(item)
    
    print(json.dumps({'items': items}))

if __name__ == '__main__':
    main()

