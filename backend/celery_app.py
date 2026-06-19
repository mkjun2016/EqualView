import os
import sys
from pathlib import Path

from celery import Celery
from celery.signals import worker_init

BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = str(BASE_DIR)

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.chdir(BACKEND_DIR)

from config import REDIS_URL

celery_app = Celery("equalview", broker=REDIS_URL)

worker_pool = "solo" if sys.platform == "darwin" else "prefork"


@worker_init.connect
def _configure_worker_path(**kwargs):
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)
    os.chdir(BACKEND_DIR)


celery_app.conf.update(
    task_ignore_result=True,
    result_backend=None,
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    include=["tasks.video_pipeline"],
    worker_pool=worker_pool,
    worker_concurrency=1 if worker_pool == "solo" else None,
)
