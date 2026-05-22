import os
import sys

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(__file__)
sys.path.insert(0, BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))

from database import cargar_polizas  # noqa: E402
from notifier import init_firebase  # noqa: E402

_initialized = False


def init_runtime() -> None:
    global _initialized
    if _initialized:
        return

    seed_path = os.getenv("SEED_PATH") or os.path.join(BASE_DIR, "seed_polizas.json")
    cargar_polizas(seed_path)
    init_firebase()
    _initialized = True
