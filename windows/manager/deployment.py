"""Deployment parameters live beside the executable, outside the source tree."""
import json
import sys
from pathlib import Path

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
DEPLOYMENT_FILE = (Path(sys.executable).parent if getattr(sys, 'frozen', False)
                   else Path(__file__).resolve().parent) / 'deployment.json'
DEPLOYMENT = json.loads(DEPLOYMENT_FILE.read_text(encoding='utf-8-sig'))
HOST = DEPLOYMENT['ssh_alias']
EXPECTED_IP = DEPLOYMENT['expected_ip']
EXPECTED_COUNTRY = DEPLOYMENT['expected_country']
EXPECTED_COLO = DEPLOYMENT['expected_colo']
REMOTE_PATH = DEPLOYMENT['remote_path']
