import functools
import logging


def log_errors(log: logging.Logger):
    """keep a tasks.loop alive when one iteration raises

    discord.ext.tasks stops a loop for good on any exception that is not a
    gateway/network error, e.g. a pymongo error while MongoDB restarts.
    The bot then stays online but never delivers reminders again.
    Log the error and let the next iteration run instead.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                log.exception(f'{func.__name__} failed, retrying on the next iteration')
                try:
                    # imported here: lib.Analytics has a circular import with lib.Reminder
                    from lib.Analytics import Analytics
                    Analytics.register_exception(e)
                except Exception:
                    log.exception('failed to record the exception in analytics')
        return wrapper
    return decorator
