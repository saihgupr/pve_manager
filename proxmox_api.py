#!/usr/bin/env python3
"""
Proxmox VE API Client for Alfred Workflow
Handles authentication and API calls to Proxmox VE
"""

import urllib.request
import urllib.parse
import json
import ssl
import os
import sys

# Add script directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import get_config


class ProxmoxAPI:
    def __init__(self):
        config = get_config()
        self.host = config['host']
        self.port = config['port']
        self.token_id = config['token_id']
        self.token_secret = config['token_secret']
        self.verify_ssl = config['verify_ssl']
        
        self.base_url = f"https://{self.host}:{self.port}/api2/json"
        
        # SSL context
        if self.verify_ssl:
            self.ssl_context = ssl.create_default_context()
        else:
            self.ssl_context = ssl.create_default_context()
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE
    
    def _request(self, method, endpoint, data=None):
        """Make an API request to Proxmox"""
        url = f"{self.base_url}{endpoint}"
        
        headers = {
            'Authorization': f'PVEAPIToken={self.token_id}={self.token_secret}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        if data:
            data = urllib.parse.urlencode(data).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else str(e)
            raise Exception(f"API Error {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise Exception(f"Connection Error: {e.reason}")
    
    def get_resources(self, resource_type=None):
        """Get all VMs and containers"""
        result = self._request('GET', '/cluster/resources')
        resources = result.get('data', [])
        
        # Filter to VMs and containers only
        filtered = [r for r in resources if r.get('type') in ('qemu', 'lxc')]
        
        if resource_type:
            filtered = [r for r in filtered if r.get('type') == resource_type]
        
        # Sort by VMID
        filtered.sort(key=lambda x: x.get('vmid', 0))
        
        return filtered
    
    def get_vm_status(self, node, vmtype, vmid):
        """Get status of a specific VM or container"""
        endpoint = f"/nodes/{node}/{vmtype}/{vmid}/status/current"
        result = self._request('GET', endpoint)
        return result.get('data', {})
    
    def start_vm(self, node, vmtype, vmid):
        """Start a VM or container"""
        endpoint = f"/nodes/{node}/{vmtype}/{vmid}/status/start"
        return self._request('POST', endpoint)
    
    def stop_vm(self, node, vmtype, vmid):
        """Stop a VM or container"""
        endpoint = f"/nodes/{node}/{vmtype}/{vmid}/status/stop"
        return self._request('POST', endpoint)
    
    def shutdown_vm(self, node, vmtype, vmid):
        """Gracefully shutdown a VM or container"""
        endpoint = f"/nodes/{node}/{vmtype}/{vmid}/status/shutdown"
        return self._request('POST', endpoint)
    
    def reboot_vm(self, node, vmtype, vmid):
        """Reboot a VM or container"""
        endpoint = f"/nodes/{node}/{vmtype}/{vmid}/status/reboot"
        return self._request('POST', endpoint)
    
    def create_snapshot(self, node, vmtype, vmid, name=None, description=None, vmstate=False):
        """Create a snapshot of a VM or container. Set vmstate=True for RAM snapshot."""
        endpoint = f"/nodes/{node}/{vmtype}/{vmid}/snapshot"
        data = {}
        if name:
            data['snapname'] = name
        if description:
            data['description'] = description
        if vmstate and vmtype == 'qemu':  # vmstate only works for VMs, not containers
            data['vmstate'] = 1
        return self._request('POST', endpoint, data)
    
    def get_snapshots(self, node, vmtype, vmid):
        """Get list of snapshots for a VM or container"""
        endpoint = f"/nodes/{node}/{vmtype}/{vmid}/snapshot"
        result = self._request('GET', endpoint)
        return result.get('data', [])
    
    def rollback_snapshot(self, node, vmtype, vmid, snapname):
        """Rollback a VM or container to a specific snapshot"""
        endpoint = f"/nodes/{node}/{vmtype}/{vmid}/snapshot/{snapname}/rollback"
        return self._request('POST', endpoint)
    
    def get_console_url(self, node, vmtype, vmid):
        """Generate console URL for web access"""
        return f"https://{self.host}:{self.port}/?console={vmtype}&novnc=1&vmid={vmid}&node={node}"


def get_api():
    """Get a configured API instance"""
    return ProxmoxAPI()
