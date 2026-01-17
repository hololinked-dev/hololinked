import logging
import os
import uuid

import pytest
import structlog

from hololinked.config import global_config
from hololinked.server.security import APIKeySecurity


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


def test_05_temp_data_folders():
    global_config.set_db_folder("test_db_folder")
    assert global_config.TEMP_DIR_DB.endswith("test_db_folder")
    assert global_config.TEMP_DIR_DB.startswith(global_config.TEMP_DIR)

    global_config.set_logs_folder("test_logs_folder")
    assert global_config.TEMP_DIR_LOGS.endswith("test_logs_folder")
    assert global_config.TEMP_DIR_LOGS.startswith(global_config.TEMP_DIR)

    global_config.set_secrets_folder("test_secrets_folder")
    assert global_config.TEMP_DIR_SECRETS.endswith("test_secrets_folder")
    assert global_config.TEMP_DIR_SECRETS.startswith(global_config.TEMP_DIR)

    global_config.set_sockets_folders("test_sockets_folder")
    assert global_config.TEMP_DIR_SOCKETS.endswith("test_sockets_folder")
    assert global_config.TEMP_DIR_SOCKETS.startswith(global_config.TEMP_DIR)

    for folder in [
        global_config.TEMP_DIR_DB,
        global_config.TEMP_DIR_LOGS,
        global_config.TEMP_DIR_SECRETS,
        global_config.TEMP_DIR_SOCKETS,
    ]:
        assert os.path.exists(folder)
        assert os.path.isdir(folder)

    assert not os.path.exists(os.path.join(global_config.TEMP_DIR_SECRETS, "apikeys.json"))
    security = APIKeySecurity(name="test-api-key-security")
    security.create(print_value=False)
    assert os.path.exists(os.path.join(global_config.TEMP_DIR_SECRETS, "apikeys.json"))


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
