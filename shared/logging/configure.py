import logging
import sys
from shared.logging.formatter import JSONFormatter

def configure_logging(service_name: str) -> None:
    root_logger = logging.getLogger()
    
    # Remove existing handlers
    while root_logger.handlers:
        root_logger.removeHandler(root_logger.handlers[0])
    
    root_logger.setLevel(logging.INFO)
    
    handler = logging.StreamHandler(sys.stdout)
    formatter = JSONFormatter(service_name)
    handler.setFormatter(formatter)
    
    root_logger.addHandler(handler)
