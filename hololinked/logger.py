import copy
import logging
import logging.handlers
import sys
import types

from typing import Any

import structlog

from structlog.dev import KeyValueColumnFormatter


default_label_formatter = None


def normalize_component_name(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """cast component name to upper case and format event message with it"""

    global default_label_formatter
    component = event_dict.pop("component", "")
    if default_label_formatter:
        component_label = f"{default_label_formatter('component', component.upper())} " if component else ""
    else:
        component_label = f"[{component.upper()}] " if component else ""
    event_dict["event"] = f"{component_label}{event_dict.get('event', '')}"
    return event_dict


def setup_logging(
    log_level: int = logging.INFO,
    colored_logs: bool = False,
    log_file: str = None,
    **kwargs,
) -> None:
    """
    Setup structured logging using structlog. Not a flexible setup, except the values configurable in `global_config`,
    Override the entire function if you want a different logging configuration by monkey patching this method.

    Parameters
    ----------
    log_level: int
        logging level to use
    colored_logs: bool
        whether to use colored logs in console, usually harder to pick it up in fluentd
    log_file: str
        optional log file to log into
    **kwargs
        additional keyword arguments

        - `rotate_log_files`: `bool`, whether to rotate log files daily (default True)
        - `logfile_backup_count`: `int`, number of backup log files to keep (default 14)
    """
    handlers = []
    if log_file:
        if kwargs.get("rotate_log_files", True):
            filehandler = logging.handlers.TimedRotatingFileHandler(
                log_file,
                when="midnight",
                backupCount=kwargs.get("logfile_backup_count", 14),
            )
        else:
            filehandler = logging.FileHandler(log_file)
        filehandler.setFormatter(logging.Formatter("%(message)s"))
        handlers.append(filehandler)
    iostream_handler = logging.StreamHandler(sys.stdout)
    iostream_handler.setFormatter(logging.Formatter("%(message)s"))
    handlers.append(iostream_handler)

    logging.basicConfig(level=log_level, handlers=handlers, force=True)

    global default_label_formatter
    console_renderer = structlog.dev.ConsoleRenderer(colors=colored_logs)
    for column in console_renderer.columns:
        if column.key == "logger_name" and isinstance(column.formatter, KeyValueColumnFormatter):
            default_label_formatter = copy.deepcopy(column.formatter)
            default_label_formatter.key_style = None

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="%d-%m-%YT%H:%M:%S.%fZ"),
            normalize_component_name,
            console_renderer,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        context_class=dict,
        cache_logger_on_first_use=True,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )

    import asyncio  # noqa: F401

    asyncio_log = structlog.get_logger().bind(component="library|asyncio")
    for name, module in sys.modules.items():
        if name.startswith("asyncio.") and isinstance(module, types.ModuleType):
            if hasattr(module, "logger"):
                module.logger = asyncio_log

    try:
        import httpx  # noqa: F401

        # httpx_log = structlog.get_logger().bind(component="library|httpx")
        logging.getLogger("httpcore").setLevel(logging.WARNING if log_level <= logging.WARNING else log_level)
        logging.getLogger("httpx").setLevel(logging.WARNING if log_level <= logging.WARNING else log_level)
    except ImportError:
        pass

    try:
        import tornado.log

        tornado_log = structlog.get_logger().bind(component="library|tornado")
        tornado.log.access_log = tornado_log
        tornado.log.app_log = tornado_log
        tornado.log.gen_log = tornado_log
    except ImportError:
        pass
