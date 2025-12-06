import logging
import uuid

import pytest
import structlog

from hololinked.config import global_config


@pytest.mark.parametrize(
    "log_level",
    [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL],
)
def test_01_loglevel(log_level: int):
    global_config.LOG_LEVEL = log_level
    global_config.setup()

    logger = structlog.get_logger()  # type: structlog.stdlib.BoundLogger
    logger.debug("Caching on first use")

    assert logger.get_effective_level() == log_level


@pytest.mark.parametrize("use_log_file", [True, False])  # first True then False
def test_02_log_to_file(use_log_file: bool):
    global_config.LOG_LEVEL = logging.INFO
    global_config.USE_LOG_FILE = use_log_file
    global_config.LOG_FILENAME = "test_log.log"
    global_config.setup()

    logger = structlog.get_logger()  # type: structlog.stdlib.BoundLogger

    debug_id = uuid.uuid4()
    info_id = uuid.uuid4()

    logger.debug("This is a debug log message", id=debug_id)  # should not appear
    logger.info("This is a test log message to file", id=info_id)

    with open(global_config.LOG_FILENAME, "r") as f:
        log_contents = f.read()

    if use_log_file:
        assert str(info_id) in log_contents
    else:
        assert str(info_id) not in log_contents
    assert str(debug_id) not in log_contents


def test_03_allow_pickle():
    from hololinked.serializers import PickleSerializer

    serializer = PickleSerializer()
    global_config.ALLOW_PICKLE = True
    value = serializer.dumps({"test": 123})  # should not raise
    assert isinstance(value, bytes)

    global_config.ALLOW_PICKLE = False
    with pytest.raises(RuntimeError):
        serializer.dumps({"test": 123})


def test_04_allow_cors():
    from hololinked.server.http import HTTPServer

    global_config.ALLOW_CORS = True
    server = HTTPServer(port=8080)
    assert server.config.cors

    global_config.ALLOW_CORS = False
    server = HTTPServer(port=8080)
    assert not server.config.cors
