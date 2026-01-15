#!/usr/bin/env python3
"""
Run Action - Executes the selected action on a VM/Container
With real-time task polling and confirmation notifications
"""

import json
import sys
import ssl
import time
import urllib.request
import urllib.parse
import plistlib
import subprocess
import webbrowser
import os
from pathlib import Path
from proxmox_api import ProxmoxAPI

def get_usage_file():
    """Get path to usage data file in Alfred's workflow data directory"""
    data_dir = os.environ.get('alfred_workflow_data', '')
    # Only use Alfred's data dir if it's for our workflow
    if data_dir and 'com.pve.manager' in data_dir:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        return Path(data_dir) / 'usage.json'
    # Fallback to script directory
    return Path(__file__).parent.absolute() / 'usage.json'

def increment_usage(vmid):
    """Increment usage count for a VM/container"""
    usage_file = get_usage_file()
    counts = {}
    if usage_file.exists():
        try:
            with open(usage_file, 'r') as f:
                counts = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    
    vmid_str = str(vmid)
    counts[vmid_str] = counts.get(vmid_str, 0) + 1
    
    try:
        with open(usage_file, 'w') as f:
            json.dump(counts, f)
    except IOError:
        pass

def get_action_usage_file():
    """Get path to action usage data file"""
    data_dir = os.environ.get('alfred_workflow_data', '')
    if data_dir and 'com.pve.manager' in data_dir:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        return Path(data_dir) / 'action_usage.json'
    return Path(__file__).parent.absolute() / 'action_usage.json'

def increment_action_usage(action):
    """Increment usage count for an action"""
    usage_file = get_action_usage_file()
    counts = {}
    if usage_file.exists():
        try:
            with open(usage_file, 'r') as f:
                counts = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    
    counts[action] = counts.get(action, 0) + 1
    
    try:
        with open(usage_file, 'w') as f:
            json.dump(counts, f)
    except IOError:
        pass

def get_config():
    """Get config from info.plist"""
    script_dir = Path(__file__).parent.absolute()
    info_plist = script_dir / 'info.plist'
    
    if info_plist.exists():
        with open(info_plist, 'rb') as f:
            plist = plistlib.load(f)
            variables = plist.get('variables', {})
            return {
                'host': variables.get('PVE_HOST', ''),
                'port': variables.get('PVE_PORT', '8006'),
                'token_id': variables.get('PVE_TOKEN_ID', ''),
                'token_secret': variables.get('PVE_TOKEN_SECRET', ''),
            }
    return {}

def api_request(method, endpoint, data=None):
    """Make API request to Proxmox, returns response data"""
    cfg = get_config()
    url = f"https://{cfg['host']}:{cfg['port']}/api2/json{endpoint}"
    
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    
    headers = {
        'Authorization': f"PVEAPIToken={cfg['token_id']}={cfg['token_secret']}",
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    if data:
        data = urllib.parse.urlencode(data).encode('utf-8')
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
        return json.loads(resp.read().decode('utf-8'))

def notify(title, message, sound=True):
    """Show notification via Alfred's native notification system"""
    # Use AppleScript to trigger Alfred's external trigger
    notification_text = f"{title}: {message}" if title != "Proxmox" else message
    notification_escaped = notification_text.replace('\\', '\\\\').replace('"', '\\"')
    
    script = f'tell application id "com.runningwithcrayons.Alfred" to run trigger "notify" in workflow "com.pve.manager" with argument "{notification_escaped}"'
    subprocess.run(['osascript', '-e', script], capture_output=True)

def get_task_status(node, upid):
    """Get the status of a Proxmox task by UPID"""
    # URL encode the UPID since it contains special characters
    encoded_upid = urllib.parse.quote(upid, safe='')
    endpoint = f"/nodes/{node}/tasks/{encoded_upid}/status"
    result = api_request('GET', endpoint)
    return result.get('data', {})

def wait_for_task(node, upid, action_name, vm_name, timeout=120):
    """
    Poll task status until completion.
    Shows notification when task starts and when it completes.
    """
    start_time = time.time()
    notified_running = False
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            notify("Proxmox", f"⏱️ {action_name} timed out for {vm_name}")
            return False
        
        try:
            status = get_task_status(node, upid)
            task_status = status.get('status', '')
            exit_status = status.get('exitstatus', '')
            
            # Task completed
            if task_status == 'stopped':
                if exit_status == 'OK':
                    notify("Proxmox", f"✅ {action_name} completed for {vm_name}")
                    return True
                else:
                    notify("Proxmox", f"❌ {action_name} failed: {exit_status}")
                    return False
            
            # Poll every second
            time.sleep(1)
            
        except Exception as e:
            # If we can't get status, wait and retry
            time.sleep(1)
    
    return False

def execute_action_with_tracking(action, node, vmtype, vmid, name):
    """Execute an action and track the task to completion"""
    action_labels = {
        'start': ('▶️ Starting', 'Start'),
        'stop': ('⏹️ Stopping', 'Stop'),
        'shutdown': ('⏻ Shutting down', 'Shutdown'),
        'restart': ('🔄 Restarting', 'Restart'),
        'reboot': ('🔄 Restarting', 'Restart'),
    }
    
    emoji_label, action_name = action_labels.get(action, ('🔧 Running', action.capitalize()))
    
    # Map action to endpoint
    endpoint_action = 'reboot' if action == 'restart' else action
    endpoint = f"/nodes/{node}/{vmtype}/{vmid}/status/{endpoint_action}"
    
    # Execute the action
    result = api_request('POST', endpoint)
    upid = result.get('data', '')
    
    if upid:
        # Notify that action was initiated
        notify("Proxmox", f"{emoji_label} {name}...", sound=False)
        # Wait for task completion
        wait_for_task(node, upid, action_name, name)
    else:
        # No UPID returned, just show simple notification
        notify("Proxmox", f"{emoji_label} {name}...")

def main():
    if len(sys.argv) < 2 or not sys.argv[1] or sys.argv[1] in ['{query}', '(null)']:
        notify("Proxmox", "⚠️ No action specified")
        return
    
    # Parse: action:node:type:vmid:name or action:node:type:vmid:name:::description
    arg = sys.argv[1]
    
    description = None
    if ':::' in arg:
        main_part, description = arg.split(':::', 1)
        # If description is empty string, make it None
        if not description:
            description = None
        parts = main_part.split(':')
    else:
        parts = arg.split(':')
    
    if len(parts) < 5:
        notify("Proxmox Error", f"❌ Invalid format: {arg[:30]}")
        return
    
    action = parts[0]
    node = parts[1]
    vmtype = parts[2]
    vmid = parts[3]
    name = ':'.join(parts[4:])
    
    cfg = get_config()
    api = ProxmoxAPI()
    
    # Track usage for smart ordering
    increment_usage(vmid)
    increment_action_usage(action)
    
    try:
        if action == 'ssh':
            # Use the container/VM name as hostname (assumes DNS or /etc/hosts configured)
            # Append .local for VMs (qemu), but usually not for LXC
            hostname = name if vmtype == 'lxc' else f"{name}.local"
            ssh_cmd = f'ssh root@{hostname}'
            # Open Terminal with SSH command
            script = f'''
            tell application "Terminal"
                activate
                do script "{ssh_cmd}"
            end tell
            '''
            subprocess.run(['osascript', '-e', script], capture_output=True)
            notify("Proxmox", f"🔗 Opening SSH to {name}")
            
        elif action == 'rollback':
            # Use osascript to call the External Trigger for snapshot selection
            # Trigger ID: show_snapshots
            # Workflow Bundle ID: com.pve.manager
            bundle_id = os.environ.get('alfred_workflow_bundleid', 'com.pve.manager')
            trigger_arg = f"rollback:{node}:{vmtype}:{vmid}:{name}"
            
            # Escape quotes in argument
            trigger_arg = trigger_arg.replace('"', '\\"')
            
            script = f'''
            tell application id "com.runningwithcrayons.Alfred"
                run trigger "show_snapshots" in workflow "{bundle_id}" with argument "{trigger_arg}"
            end tell
            '''
            subprocess.run(['osascript', '-e', script])
            # Don't notify, just open the new view
            
        elif action in ['start', 'stop', 'shutdown', 'restart', 'reboot']:
            execute_action_with_tracking(action, node, vmtype, vmid, name)
            
        elif action in ['snapshot', 'snapshot_ram', 'snapshot_with_desc', 'snapshot_ram_with_desc']:
            include_ram = 'ram' in action
            # Create meaningful snapshot name: snapN
            try:
                snapshots = api.get_snapshots(node, vmtype, vmid)
                
                max_snap_num = 0
                for snap in snapshots:
                    snap_name_from_list = snap.get('name', '')
                    if snap_name_from_list.startswith('snap') and snap_name_from_list[4:].isdigit():
                        try:
                            num = int(snap_name_from_list[4:])
                            if num > max_snap_num:
                                max_snap_num = num
                        except ValueError:
                            pass
                
                next_snap_num = max_snap_num + 1
                snap_name = f"snap{next_snap_num}"
                
                # Create snapshot and get UPID
                snap_type = "RAM snapshot" if include_ram else "snapshot"
                notify("Proxmox", f"📸 Creating {snap_type} '{snap_name}' for {name}...", sound=False)
                
                # Use description if we parsed one
                result = api.create_snapshot(node, vmtype, vmid, snap_name, description=description, vmstate=include_ram)
                upid = result.get('data', '')
                
                if upid:
                    wait_for_task(node, upid, f"{snap_type.capitalize()} '{snap_name}'", name)
                else:
                    notify("Proxmox", f"📸 {snap_type.capitalize()} '{snap_name}' created for {name}")
                
            except Exception as e:
                notify("❌ Snapshot Failed", str(e)[:50])
                sys.exit(1)
        
        elif action == 'webui':
            # Open the Proxmox web interface for this VM/container
            cfg = get_config()
            # URL format: #v1:0:=lxc%2F107 or #v1:0:=qemu%2F100
            url = f"https://{cfg['host']}:{cfg['port']}/#v1:0:={vmtype}%2F{vmid}"
            webbrowser.open(url)
            notify("Proxmox", f"🌐 Opening Web UI for {name}")
        
        elif action == 'console':
            # Open the Proxmox web console directly for this VM/container
            cfg = get_config()
            # URL format: #v1:0:=lxc%2F107-:4::::::=consolejs:
            url = f"https://{cfg['host']}:{cfg['port']}/#v1:0:={vmtype}%2F{vmid}-:4::::::=consolejs:"
            webbrowser.open(url)
            notify("Proxmox", f"🖥️ Opening Console for {name}")
        
        elif action == 'rollback_exec':
            # Rollback to a specific snapshot
            # arg format: rollback_exec:node:type:vmid:name:::snapname:::was_running:::has_vmstate
            try:
                # Parse the special format with ::: separator
                # The original parts are: action, node, type, vmid, name
                # Then we have :::snapname:::was_running:::has_vmstate
                # We already parsed description from ::: earlier, but let's re-parse fully
                full_arg = sys.argv[1]
                triple_parts = full_arg.split(':::')
                
                if len(triple_parts) < 4:
                    notify("Proxmox Error", f"❌ Invalid rollback format")
                    return
                
                # First part contains action:node:type:vmid:name, rest are snapname, was_running, has_vmstate
                main_parts = triple_parts[0].split(':')
                snap_name = triple_parts[1]
                was_running = triple_parts[2].lower() == 'true'
                has_vmstate = triple_parts[3] == '1'
                
                # Get current status to check if running
                status_result = api_request('GET', f"/nodes/{node}/{vmtype}/{vmid}/status/current")
                current_status = status_result.get('data', {}).get('status', 'unknown')
                currently_running = current_status == 'running'
                
                notify("Proxmox", f"⏪ Rolling back {name} to '{snap_name}'...", sound=False)
                
                # Perform rollback
                result = api.rollback_snapshot(node, vmtype, vmid, snap_name)
                upid = result.get('data', '')
                
                if upid:
                    success = wait_for_task(node, upid, f"Rollback to '{snap_name}'", name)
                    
                    # If rollback was successful, was running before, and snapshot doesn't have RAM state, start it
                    if success and (was_running or currently_running) and not has_vmstate:
                        # Wait a moment for rollback to fully complete
                        time.sleep(1)
                        notify("Proxmox", f"▶️ Starting {name} after rollback...", sound=False)
                        start_result = api_request('POST', f"/nodes/{node}/{vmtype}/{vmid}/status/start")
                        start_upid = start_result.get('data', '')
                        if start_upid:
                            wait_for_task(node, start_upid, "Start after rollback", name)
                else:
                    notify("Proxmox", f"⏪ Rollback to '{snap_name}' initiated for {name}")
                    
            except Exception as e:
                notify("❌ Rollback Failed", str(e)[:50])
                sys.exit(1)
        
        else:
            notify("Proxmox Error", f"❌ Unknown action: {action}")
            
    except urllib.error.HTTPError as e:
        error_msg = e.read().decode('utf-8')[:50] if e.fp else str(e.code)
        notify("Proxmox Error", f"❌ API Error: {error_msg}")
        
    except Exception as e:
        notify("Proxmox Error", f"❌ {str(e)[:50]}")

if __name__ == '__main__':
    main()
