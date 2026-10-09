import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 1. Determine Project Root directory
BASE_DIR = Path(__file__).resolve().parent.parent

# 2. Load .env file immediately
env_file = BASE_DIR / ".env"
if env_file.exists():
    load_dotenv(dotenv_path=str(env_file), override=False)
else:
    load_dotenv()

# 3. Resolve Database Path
env_db_path = os.environ.get("ANTIGRAVITY_DB_PATH")
if not env_db_path or (os.name == "nt" and env_db_path.startswith("/opt/")):
    DB_PATH = str(BASE_DIR / "antigravity.db")
else:
    DB_PATH = env_db_path

# 4. Resolve Workspace Directory
env_workspace = os.environ.get("ANTIGRAVITY_WORKSPACE")
if not env_workspace or (os.name == "nt" and env_workspace.startswith("/opt/")):
    WORKSPACE_DIR = str(BASE_DIR / "workspace")
else:
    WORKSPACE_DIR = env_workspace

os.makedirs(WORKSPACE_DIR, exist_ok=True)
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)

# 5. Security & Authentication
AUTH_TOKEN = os.environ.get("ANTIGRAVITY_AUTH_TOKEN", os.environ.get("ANTIGRAVITY_PASSWORD", ""))
if not AUTH_TOKEN:
    import secrets
    AUTH_TOKEN = secrets.token_hex(16)


# 6. Gateway & Router defaults
AI_GATEWAY_URL = os.environ.get("AI_GATEWAY_URL", "http://127.0.0.1:8500/v1")
AI_GATEWAY_KEY = os.environ.get("AI_GATEWAY_KEY", "ag-pool-key")
