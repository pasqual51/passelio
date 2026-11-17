"""Separate cleanup process; do not run inside HTTP request threads."""
import logging
import time
from app import create_app

app = create_app()
logging.basicConfig(level=logging.INFO)
while True:
    try:
        logging.info("Expired/revoked files removed: %s", app.cleanup())
    except Exception:
        logging.exception("Cleanup failed; will retry in 5 minutes")
    time.sleep(300)
