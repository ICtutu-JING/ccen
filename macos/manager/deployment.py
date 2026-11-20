"""Keep editable deployment settings outside the macOS application bundle."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
DATA = Path(os.environ.get('CCEN_DATA_DIR', Path.home() / 'Library/Application Support/ClaudeConnectionManager'))
DEPLOYMENT_FILE = DATA / 'deployment.json'
DEPLOYMENT = json.loads(DEPLOYMENT_FILE.read_text(encoding='utf-8-sig'))
REMOTE_ENABLED = DEPLOYMENT['remote_enabled']
HOST = DEPLOYMENT['ssh_alias'] if REMOTE_ENABLED else ''
RESIDENTIAL_PORT = DEPLOYMENT['residential_port']
ORDINARY_PORT = DEPLOYMENT['ordinary_port']
EXPECTED_IP = DEPLOYMENT['expected_ip']
EXPECTED_COUNTRY = DEPLOYMENT['expected_country']
EXPECTED_COLO = DEPLOYMENT['expected_colo']
REMOTE_PATH = DEPLOYMENT['remote_path'] if REMOTE_ENABLED else ''
