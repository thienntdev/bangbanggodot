"""Optional diagnostic files, controlled by the authenticated local admin.

Default: no log files. Console warnings/errors remain visible. Enabling file
logging uses INFO, not raw DEBUG protocol payloads; rotation bounds disk use.
"""
from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import threading

LOG_DIR = Path(__file__).resolve().parents[1] / 'data' / 'packet_log'
LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR')
_lock = threading.RLock()
_handler = None
_base_level = 'WARNING'
_directory = LOG_DIR

def get_logger(name):
    return logging.getLogger('bangbang.' + name)

def status():
    with _lock:
        return dict(enabled=_handler is not None, level='INFO',
                    location='data/packet_log/diagnostic.log', max_bytes=5*1024*1024, backups=2)

def set_file_logging(enabled):
    global _handler
    if type(enabled) is not bool:
        raise ValueError('enabled must be boolean')
    with _lock:
        logger = logging.getLogger('bangbang')
        if enabled and _handler is None:
            _directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(_directory / 'diagnostic.log', maxBytes=5*1024*1024,
                                          backupCount=2, encoding='utf-8', delay=False)
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
            logger.addHandler(handler)
            logger.setLevel(min(logging.INFO, logging._nameToLevel[_base_level]))
            _handler = handler
            logger.info('Diagnostic file logging enabled')
        elif not enabled and _handler is not None:
            logger.removeHandler(_handler)
            _handler.close()
            _handler = None
            logger.setLevel(_base_level)
        return status()

def configure(level='WARNING', log_dir=None, stream=None):
    global _handler, _base_level, _directory
    if level not in LEVELS:
        raise ValueError('Unsupported log level')
    with _lock:
        logger = logging.getLogger('bangbang')
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        _handler = None
        _base_level = level
        _directory = Path(log_dir) if log_dir is not None else LOG_DIR
        logger.setLevel(level)
        logger.propagate = False
        console = logging.StreamHandler(stream)
        console.setLevel(level)
        console.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
        logger.addHandler(console)
