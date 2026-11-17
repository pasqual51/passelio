"""Separate outbox/cleanup process; no network delivery in HTTP threads."""
import logging
import time
from app import create_app

app = create_app()
logging.basicConfig(level=logging.INFO)
last_cleanup=0
while True:
    try:
        app.process_mail(limit=10)
        if time.monotonic()-last_cleanup>=300:
            logging.info("Expired/revoked files removed: %s", app.cleanup())
            last_cleanup=time.monotonic()
    except Exception:
        logging.error("Background cycle failed; will retry without logging secrets")
    time.sleep(5)
