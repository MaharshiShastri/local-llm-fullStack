from celery import Celery
import os
from kombu import Queue

celery = Celery(
    "chronos_tasks",
    broker=os.getenv("REDIS_URL", "redis://localhost:6373/0"),
    backend = os.getenv("REDIS_URL", "redis://localhost:6373/0")
)

celery.conf.update(
    task_default_queue="default",
    task_Queues=(
        Queue("chat_queue", routing_key="chat.#"),
        Queue("plan_queue", routing_key="plan.#"),
    ),
    task_routes = {
        "app.services.tasks.process_chat": {"queue": "chat_queue"},
        "app.services.tasks.process_plan": {"queue": "plan_queue"},
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