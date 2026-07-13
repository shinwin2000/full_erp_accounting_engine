import logging
from functools import wraps

logger = logging.getLogger(__name__)

class MappingError(Exception):
    """Base exception for mapping errors."""
    pass

def safe_map(func):
    """Decorator to add consistent error handling to mapper functions."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Mapping failed in {func.__name__}: {e}", exc_info=True)
            raise MappingError(f"Mapping failed in {func.__name__}") from e
    return wrapper
