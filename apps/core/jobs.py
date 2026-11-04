"""Queueing helper. A background job must never break the page that asked for it."""
import logging
import time

log = logging.getLogger("lumen.jobs")
PAUSE_SECONDS = 30
_down_until = 0.0  # per process: after a failure, stop trying for a while so each page does not wait on a dead broker


def dispatch(task, *args, **kwargs):
    """Queue a Celery task. If the broker (Redis) is unreachable, log it and carry on instead of raising into a web request.
    Returns True when the job was queued (or, in eager mode, has already run)."""
    global _down_until
    name = getattr(task, "name", task)
    if time.monotonic() < _down_until:
        log.warning("Skipped %s: the job queue is unreachable (will try again soon)", name)
        return False
    try:
        task.apply_async(args=args, kwargs=kwargs, retry=False)
        return True
    except Exception as exc:  # broker down, misconfigured...
        _down_until = time.monotonic() + PAUSE_SECONDS
        log.warning("Could not queue %s: %s", name, exc)
        return False
