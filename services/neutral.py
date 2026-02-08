import os
import json

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA_DIR = os.path.join(ROOT, 'data')
NEUTRAL_FILE = os.path.join(DATA_DIR, 'neutral_positions.json')

def ensure_data_dir():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass

def load_neutral():
    ensure_data_dir()
    if not os.path.exists(NEUTRAL_FILE):
        return {}
    try:
        with open(NEUTRAL_FILE, 'r', encoding='utf8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_neutral(mapping):
    ensure_data_dir()
    try:
        with open(NEUTRAL_FILE, 'w', encoding='utf8') as f:
            json.dump(mapping, f, indent=2)
        return True
    except Exception:
        return False
