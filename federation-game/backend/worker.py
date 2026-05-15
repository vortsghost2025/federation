import os
import time
import logging
import redis

logging.basicConfig(level=logging.INFO)

def main():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = redis.from_url(redis_url)
    while True:
        # Example background task: clean up expired sessions (placeholder)
        logging.info("Worker heartbeat – checking background tasks")
        # Implement real background jobs here
        time.sleep(30)

if __name__ == "__main__":
    main()
