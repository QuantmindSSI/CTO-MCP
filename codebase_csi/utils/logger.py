"""
Logging utilities for AI code detection.

Provides structured logging with JSON support for production environments.
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


# ANSI color codes for terminal output
class Colors:
    RESET = '\033[0m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output."""
    
    COLORS = {
        'DEBUG': Colors.CYAN,
        'INFO': Colors.GREEN,
        'WARNING': Colors.YELLOW,
        'ERROR': Colors.RED,
        'CRITICAL': Colors.RED + Colors.BOLD
    }
    
    def format(self, record):
        # Add color to level name
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{Colors.RESET}"
        
        # Format the message
        result = super().format(record)
        
        # Reset colors
        record.levelname = levelname
        
        return result


def setup_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
    json_format: bool = False,
    verbose: bool = False
) -> None:
    """
    Configure logging for the application.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for log output
        json_format: Use JSON format for structured logging
        verbose: Enable verbose output (DEBUG level)
    """
    # Determine log level
    if verbose:
        log_level = logging.DEBUG
    else:
        log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Create formatters
    if json_format:
        # JSON formatter for production
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}'
        )
    else:
        # Human-readable formatter for development
        console_formatter = ColoredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    root_logger.handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    if json_format:
        console_handler.setFormatter(formatter)
    else:
        console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (if specified)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        if json_format:
            file_handler.setFormatter(formatter)
        else:
            file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    # Log initial message
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized at {level} level")


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class LoggerAdapter(logging.LoggerAdapter):
    """
    Custom logger adapter that adds context to log messages.
    
    Example:
        >>> logger = LoggerAdapter(get_logger(__name__), {'scan_id': '123'})
        >>> logger.info("Scanning file", extra={'file': 'test.py'})
    """
    
    def process(self, msg, kwargs):
        # Merge extra context
        extra = kwargs.get('extra', {})
        extra.update(self.extra)
        kwargs['extra'] = extra
        return msg, kwargs
