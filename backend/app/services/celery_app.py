from celery import Celery
import os
from kombu import Queue
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6373/0")
r_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
celery = Celery(
    "chronos_tasks",
    broker=REDIS_URL,
    backend = REDIS_URL
)

celery.conf.update(
    task_default_queue="default",
    task_Queues=(
        Queue("chat_queue", routing_key="chat.#"),
        Queue("plan_queue", routing_key="plan.#"),
    ),
    task_routes = {
        "mission.process_chat": {"queue": "chat_queue"},
        "mission.process_plan": {"queue": "plan_queue"},
        "mission.execute_lifecycle": {"queue": "plan_queue"},
    },
    worker_prefetch_multiplier=1,
    task_track_started = True,
)
celery.conf.update(
    task_track_started=True,
    task_serialization="json",
    result_persistent=True,
    worker_prefetch_multiplier = 1
)