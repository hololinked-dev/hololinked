import logging
import structlog
import copy
from typing import Any
from structlog.dev import KeyValueColumnFormatter
import sys
import types

default_label_formatter = None


def normalize_component_name(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    global default_label_formatter
    component = event_dict.pop("component", "")
    if default_label_formatter:
        component_label = f"{default_label_formatter('component', component.upper())} " if component else ""
    else:
        component_label = f"[{component.upper()}] " if component else ""
    event_dict["event"] = f"{component_label}{event_dict.get('event', '')}"
    return event_dict


def setup_logging(log_level: int = logging.INFO) -> None:
    """Setup structured logging for hololinked library"""
    logging.basicConfig(format="%(message)s", level=log_level)

    global default_label_formatter
    console_renderer = structlog.dev.ConsoleRenderer()
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
    )

    import asyncio  # noqa: F401

    asyncio_log = structlog.get_logger().bind(component="library|asyncio")
    for name, module in sys.modules.items():
        if name.startswith("asyncio.") and isinstance(module, types.ModuleType):
            if hasattr(module, "logger"):
                module.logger = asyncio_log

    import tornado.log

    tornado_log = structlog.get_logger().bind(component="library|tornado")
    tornado.log.access_log = tornado_log
    tornado.log.app_log = tornado_log
    tornado.log.gen_log = tornado_log
