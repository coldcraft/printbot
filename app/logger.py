"""
Centralized logging — logs to file, NAS, and stdout
"""

import logging
import os
from datetime import datetime
from pathlib import Path

def setup_logger(name: str):
    """
    Setup logger with file and console handlers.
    Logs to /logs/printbot.log locally and NAS path.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Avoid adding duplicate handlers if logger already configured
    if logger.handlers:
        return logger

    # Create formatters
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Local file handler
    local_log_dir = os.getenv("LOG_DIR", "/logs")
    Path(local_log_dir).mkdir(parents=True, exist_ok=True)
    local_log_file = os.path.join(local_log_dir, "printbot.log")
    
    try:
        file_handler = logging.FileHandler(local_log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not create local log file: {e}")

    # NAS file handler (mounted by Docker from Windows path)
    nas_log_path = "/nas_logs"  # Mounted in Docker at /nas_logs
    if nas_log_path and os.path.exists(nas_log_path):
        Path(nas_log_path).mkdir(parents=True, exist_ok=True)
        nas_log_file = os.path.join(nas_log_path, "printbot.log")
        
        try:
            nas_handler = logging.FileHandler(nas_log_file)
            nas_handler.setLevel(logging.DEBUG)
            nas_handler.setFormatter(formatter)
            logger.addHandler(nas_handler)
        except Exception as e:
            logger.warning(f"Could not create NAS log file: {e}")

    return logger
