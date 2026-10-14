import logging
import sys
from datetime import datetime

from utils.config import REPO_ROOT, read_env_file


def setup_logging():
    settings = read_env_file(REPO_ROOT / ".env")
    log_level = str(settings.get("LOG_LEVEL", "INFO")).upper()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    log_dir = REPO_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"insider_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
        force=True,
    )
    if str(settings.get("IRC_DEBUG", "false")).lower() in ("true", "1", "yes"):
        logging.getLogger("irc").setLevel(logging.DEBUG)
        logging.getLogger("irc.client").setLevel(logging.DEBUG)
        logging.getLogger("irc.connection").setLevel(logging.DEBUG)
    return logging.getLogger("insiderbot")
