#!/usr/bin/env python3
"""
List Snapshots - Shows available snapshots for rollback
"""

import json
import ssl
import os
import urllib.request
from datetime import datetime

def get_config():
    """Get config from environment variables (set by Alfred at runtime)"""
    return {
        'host': os.environ.get('PVE_HOST', ''),
        'port': os.environ.get('PVE_PORT', '8006'),
        'token_id': os.environ.get('PVE_TOKEN_ID', ''),
        'token_secret': os.environ.get('PVE_TOKEN_SECRET', ''),
    }

def api_request(method, endpoint):
    """Make API request to Proxmox"""
    cfg = get_config()
    url = f"https://{cfg['host']}:{cfg['port']}/api2/json{endpoint}"
    
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    
    headers = {
        'Authorization': f"PVEAPIToken={cfg['token_id']}={cfg['token_secret']}"
    }
    
    req = urllib.request.Request(url, headers=headers, method=method)
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))

def format_timestamp(snaptime):
    """Format snapshot timestamp to readable date"""
    if not snaptime:
        return ""
    try:
        dt = datetime.fromtimestamp(snaptime)
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        return ""

def main():
    items = []
    
    # Get the vm_context from environment variable (set by Arg and Vars utility)
    vm_context = os.environ.get('vm_context', '')
    
    # Parse the context: rollback:node:type:vmid:name
    if not vm_context or not vm_context.startswith('rollback:'):
        items.append({
            'title': '❌ Missing VM context',
            'subtitle': f'vm_context: {vm_context[:50] if vm_context else "(empty)"}',
            'valid': False
        })
        print(json.dumps({'items': items}))
        return
    
    parts = vm_context.split(':')
    if len(parts) < 5:
        items.append({
            'title': '❌ Invalid context format',
            'subtitle': f'Expected rollback:node:type:vmid:name, got: {vm_context[:50]}',
            'valid': False
        })
        print(json.dumps({'items': items}))
        return
    
    node = parts[1]
    vmtype = parts[2]
    vmid = parts[3]
    name = ':'.join(parts[4:])  # Name might contain colons
    
    try:
        # Check if VM is currently running
        status_endpoint = f"/nodes/{node}/{vmtype}/{vmid}/status/current"
        status_result = api_request('GET', status_endpoint)
        current_status = status_result.get('data', {}).get('status', 'unknown')
        is_running = current_status == 'running'
        
        # Get snapshots
        endpoint = f"/nodes/{node}/{vmtype}/{vmid}/snapshot"
        result = api_request('GET', endpoint)
        snapshots = result.get('data', [])
        
        # Filter out 'current' and sort by timestamp (newest first)
        real_snapshots = [s for s in snapshots if s.get('name') != 'current']
        real_snapshots.sort(key=lambda x: x.get('snaptime', 0), reverse=True)
        
        if not real_snapshots:
            items.append({
                'title': '📭 No snapshots available',
                'subtitle': f'No snapshots found for {name}',
                'valid': False
            })
        else:
            for snap in real_snapshots:
                snap_name = snap.get('name', 'unknown')
                snap_desc = snap.get('description', '')
                snap_time = format_timestamp(snap.get('snaptime'))
                has_vmstate = False
                raw_vmstate = snap.get('vmstate')
                if raw_vmstate:
                    # Handle various truthy values (1, '1', True, 'true', etc.)
                    if isinstance(raw_vmstate, str):
                        has_vmstate = raw_vmstate.lower() in ('1', 'true', 'yes', 'on')
                    else:
                        has_vmstate = bool(raw_vmstate)

                # Build subtitle
                subtitle_parts = []
                if snap_time:
                    subtitle_parts.append(snap_time)
                if snap_desc:
                    subtitle_parts.append(snap_desc)
                if has_vmstate:
                    # Using RAM emoji and explicit text to make it obvious
                    subtitle_parts.append('🐏 RAM')
                
                subtitle = ' • '.join(subtitle_parts) if subtitle_parts else 'No description'
                
                # Build arg: rollback_exec:node:type:vmid:name:::snapname:::was_running:::has_vmstate
                was_running_str = 'true' if is_running else 'false'
                rollback_arg = f"rollback_exec:{node}:{vmtype}:{vmid}:{name}:::{snap_name}:::{was_running_str}:::{1 if has_vmstate else 0}"
                
                # Determine emoji based on state
                emoji = '🐏' if has_vmstate else '📷'
                
                items.append({
                    'title': f'{emoji} {snap_name}',
                    'subtitle': subtitle,
                    'arg': rollback_arg,
                    'valid': True,
                    'icon': {'path': 'icon.png'}
                })
                
    except Exception as e:
        items.append({
            'title': '❌ Error fetching snapshots',
            'subtitle': str(e)[:80],
            'valid': False
        })
    
    print(json.dumps({'items': items}))

if __name__ == '__main__':
    main()
