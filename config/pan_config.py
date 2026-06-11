"""
项目配置 —— 所有路径、凭证、常量集中管理
"""
from pathlib import Path

# ── 项目路径 ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "hk_streetscape360"
PANORAMA_OUTPUT = DATA_DIR / "pan_download"
EXTRACTOR_SCRIPT = PROJECT_ROOT / "pan_tools" / "frontend" / "extract_gtpanos.js"

# ── GeoJSON 数据文件 ──────────────────────────────────
GEOJSON_PATH = DATA_DIR / "streetscape-360-api-wholehk.geojson"

# ── .env 加载 ─────────────────────────────────────────
_ENV_PATH = DATA_DIR / ".env"


def _load_env():
    env = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


_ENV = _load_env()
API_KEY = _ENV.get("API_KEY", "")
SHARE_CODE = _ENV.get("SHARE_CODE", "")

# ── MMS API ───────────────────────────────────────────
GEOTWIN_HOST = "https://services1.map.gov.hk/api/mms"
PANORAMA_LAYER_IDS = [34, 35, 40, 41, 42, 44, 39, 38, 37, 36, 46, 50, 51, 49, 48, 45, 47]

# ── 下载参数 ──────────────────────────────────────────
DOWNLOAD_WORKERS = 8
