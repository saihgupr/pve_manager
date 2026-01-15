#!/usr/bin/env python3
"""
Configuration loader for Proxmox Alfred Workflow
Reads from workflow variables or falls back to hardcoded defaults
"""

import os
import json
import plistlib
from pathlib import Path

def get_config():
    """Get configuration from workflow info.plist or environment"""
    config = {
        'host': os.environ.get('PVE_HOST', ''),
        'port': os.environ.get('PVE_PORT', '8006'),
        'token_id': os.environ.get('PVE_TOKEN_ID', ''),
        'token_secret': os.environ.get('PVE_TOKEN_SECRET', ''),
        'verify_ssl': os.environ.get('PVE_VERIFY_SSL', 'false').lower() == 'true'
    }
    
    # If environment variables are not set, try to read from info.plist
    if not config['host'] or not config['token_id']:
        script_dir = Path(__file__).parent.absolute()
        info_plist = script_dir / 'info.plist'
        
        if info_plist.exists():
            try:
                with open(info_plist, 'rb') as f:
                    plist = plistlib.load(f)
                    variables = plist.get('variables', {})
                    
                    config['host'] = variables.get('PVE_HOST', config['host'])
                    config['port'] = variables.get('PVE_PORT', config['port'])
                    config['token_id'] = variables.get('PVE_TOKEN_ID', config['token_id'])
                    config['token_secret'] = variables.get('PVE_TOKEN_SECRET', config['token_secret'])
                    verify_ssl_str = variables.get('PVE_VERIFY_SSL', 'false')
                    config['verify_ssl'] = verify_ssl_str.lower() == 'true'
            except Exception:
                pass
    
    return config
