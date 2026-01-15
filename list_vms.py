#!/usr/bin/env python3
"""
PVE Manager - Alfred Script Filter
Lists VMs and Containers with polished emoji UI
"""

import json
import sys
import os
import ssl
import urllib.request
from pathlib import Path

def get_usage_file():
    """Get path to usage data file in Alfred's workflow data directory"""
    # Alfred provides workflow data directory via env var
    data_dir = os.environ.get('alfred_workflow_data', '')
    # Only use Alfred's data dir if it's for our workflow
    if data_dir and 'com.pve.manager' in data_dir:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        return Path(data_dir) / 'usage.json'
    # Fallback to script directory
    return Path(__file__).parent.absolute() / 'usage.json'

def load_usage_counts():
    """Load usage counts from file"""
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
    return {
        'host': os.environ.get('PVE_HOST', ''),
        'port': os.environ.get('PVE_PORT', '8006'),
        'token_id': os.environ.get('PVE_TOKEN_ID', ''),
        'token_secret': os.environ.get('PVE_TOKEN_SECRET', ''),
    }

def format_bytes(bytes_val):
    """Format bytes to human readable"""
    if not bytes_val:
        return "0B"
    if bytes_val < 1024:
        return f"{bytes_val}B"
    elif bytes_val < 1024**2:
        return f"{bytes_val/1024:.0f}KB"
    elif bytes_val < 1024**3:
        return f"{bytes_val/1024**2:.1f}MB"
    else:
        return f"{bytes_val/1024**3:.1f}GB"

def get_status_emoji(status):
    """Get status emoji"""
    return {
        'running': '🟢',
        'stopped': '🔴',
        'paused': '🟡',
        'suspended': '🟠'
    }.get(status, '⚪')

def get_type_emoji(vmtype):
    """Get type emoji"""
    return '📦' if vmtype == 'lxc' else '🖥️'

def main():
    items = []
    raw_query = sys.argv[1] if len(sys.argv) > 1 else ''
    query = '' if raw_query in ['{query}', '(null)', 'null', None] else raw_query.lower().strip()
    
    try:
        cfg = get_config()
        host = cfg.get('host', '')
        port = cfg.get('port', '8006')
        token_id = cfg.get('token_id', '')
        token_secret = cfg.get('token_secret', '')
        
        if not host or not token_id:
            items.append({
                'title': '⚠️  Configuration Required',
                'subtitle': 'Open workflow settings to add your Proxmox credentials',
                'valid': False
            })
        else:
            url = f"https://{host}:{port}/api2/json/cluster/resources"
            
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            
            headers = {
                'Authorization': f'PVEAPIToken={token_id}={token_secret}'
            }
            
            req = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                resources = data.get('data', [])
                vms = [r for r in resources if r.get('type') in ('qemu', 'lxc')]
                
                # Load usage counts and sort by usage (most used first), then by vmid
                usage_counts = load_usage_counts()
                vms.sort(key=lambda x: (-usage_counts.get(str(x.get('vmid', 0)), 0), x.get('vmid', 0)))
                
                for vm in vms:
                    vmid = vm.get('vmid', '')
                    name = vm.get('name', f'VM {vmid}')
                    status = vm.get('status', 'unknown')
                    node = vm.get('node', '')
                    vmtype = vm.get('type', 'qemu')
                    
                    # Filter by query
                    search_str = f"{vmid} {name}".lower()
                    if query and query not in search_str:
                        continue
                    
                    # Format resources
                    cpu = vm.get('cpu', 0)
                    maxcpu = vm.get('maxcpu', 1)
                    mem = vm.get('mem', 0)
                    
                    cpu_pct = f"{cpu * 100 / maxcpu:.0f}%" if maxcpu else "N/A"
                    mem_used = format_bytes(mem)
                    
                    status_emoji = get_status_emoji(status)
                    type_emoji = get_type_emoji(vmtype)
                    type_label = 'Container' if vmtype == 'lxc' else 'VM'
                    
                    # Title with type emoji
                    title = f"{status_emoji}  {type_emoji}  {vmid} {name}"
                    
                    # Subtitle with status and resources
                    subtitle = f"{status_emoji} {status.capitalize()}  •  CPU: {cpu_pct}  •  RAM: {mem_used}"
                    
                    # Variables for the next script filter
                    variables = {
                        'node': node,
                        'type': vmtype,
                        'vmid': str(vmid),
                        'name': name
                    }
                    
                    # Argument for direct actions (mods) needs to keep the old format
                    full_arg = f"{node}:{vmtype}:{vmid}:{name}"
                    
                    # Dynamic modifier based on status
                    start_stop = {
                        'subtitle': f"{'⏹️ Stop' if status == 'running' else '▶️ Start'} {name}",
                        'arg': f"{'stop' if status == 'running' else 'start'}:{full_arg}",
                        'valid': True
                    }
                    
                    items.append({
                        'uid': f"pve-{vmid}",
                        'title': title,
                        'subtitle': subtitle,
                        'variables': variables,
                        'arg': '',  # Clear arg so the next script filter has a clean search box
                        'autocomplete': name,
                        'icon': {'path': 'icon.png'},
                        'mods': {
                            'cmd': {
                                'subtitle': f"🔄 Restart {name}" if status == 'running' else f"▶️ Start {name}",
                                'arg': f"restart:{full_arg}" if status == 'running' else f"start:{full_arg}",
                                'valid': True
                            },
                            'alt': {
                                'subtitle': f"🖥️ Open Console in Browser",
                                'arg': f"console:{full_arg}",
                                'valid': True
                            },
                            'ctrl': start_stop,
                            'shift': {
                                'subtitle': f"⏻ Graceful Shutdown {name}",
                                'arg': f"shutdown:{full_arg}",
                                'valid': True
                            }
                        }
                    })
                
                if not items:
                    if query:
                        items.append({
                            'title': f'🔍  No matches for "{query}"',
                            'subtitle': 'Try a different search term',
                            'valid': False
                        })
                    else:
                        items.append({
                            'title': '📭  No VMs or containers found',
                            'subtitle': 'Your Proxmox server has no VMs or containers',
                            'valid': False
                        })
                    
    except urllib.error.URLError as e:
        items.append({
            'title': '🔌  Connection Failed',
            'subtitle': f"Could not reach Proxmox: {str(e.reason)[:60]}",
            'valid': False
        })
    except Exception as e:
        items.append({
            'title': '❌  Error',
            'subtitle': str(e)[:80],
            'valid': False
        })
    
    print(json.dumps({'items': items}))

if __name__ == '__main__':
    main()
