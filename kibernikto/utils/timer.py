import logging
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def timer(description: str = "Execution time"):
    """
    Context manager to measure execution time of code blocks.

    Args:
        description: Description for the timer output

    Returns:
        float: The elapsed time in seconds
    """
    start = time.perf_counter()
    yield
    elapsed_time = time.perf_counter() - start
    logger.info(f"{description}: {elapsed_time:.3f} seconds")
    return elapsed_time
