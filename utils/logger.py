import logging
import os
from rich.logging import RichHandler
from config import LOG_FILE

def get_logger(name: str) -> logging.Logger:
    """
    Returns a configured rich logger that logs to both console and file.
    """
    logger = logging.getLogger(name)
    
    if logger.hasHandlers():
        return logger
        
    logger.setLevel(logging.DEBUG)
    
    # Ensure data directory exists for log file
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
        
    # File handler
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_format)
    
    # Console handler (Rich)
    rich_handler = RichHandler(rich_tracebacks=True, markup=True)
    rich_handler.setLevel(logging.INFO)
    rich_format = logging.Formatter('%(message)s')
    rich_handler.setFormatter(rich_format)
    
    logger.addHandler(file_handler)
    logger.addHandler(rich_handler)
    
    return logger
