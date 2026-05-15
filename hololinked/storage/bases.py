"""Base database class shared by all database engine implementations."""

from __future__ import annotations

import os
import threading

from typing import TYPE_CHECKING

from hololinked.config import global_config
from hololinked.core.interfaces import BaseConfigurationRepository
from hololinked.serializers import PythonBuiltinJSONSerializer as JSONSerializer
from hololinked.storage.config import MongoDBConfig, SQLDBConfig, SQLiteConfig
from hololinked.utils import get_sanitized_filename_from_random_string


if TYPE_CHECKING:
    from hololinked.core.thing import Thing


class BaseDB(BaseConfigurationRepository):
    """
    Base class for database engine based configuration management.

    Implements common functionality like loading DB configuration and context management for batch calls.
    Specific database engines should inherit from this class and implement the required methods from
    `BaseConfigurationRepository`.
    """

    def __init__(self, thing: Thing, config_file: str | None = None) -> None:
        """
        Initialize the BaseDB instance.

        Parameters
        ----------
        thing: Thing
            The `Thing` instance which uses this database engine for configuration storage.
        config_file: str, optional
            Path to the database configuration file. `sqlite` backend with default settings will be used if not provided.
        """
        super().__init__(thing=thing)
        self.config = BaseDB.load_conf(
            config_file=config_file,
            default_file_path=os.path.join(
                global_config.TEMP_DIR_DB,
                get_sanitized_filename_from_random_string(
                    f"{self.thing.__class__.__name__}.{self.thing.id}",
                    extension="db",
                ),
            ),
        )
        self._batch_call_context = {}

    @staticmethod
    def load_conf(
        config_file: str | None,
        default_file_path: str = "",
    ) -> SQLDBConfig | SQLiteConfig | MongoDBConfig:
        """
        Load configuration file using JSON serializer.

        Parameters
        ----------
        config_file: str
            path to configuration file, expected to be in JSON format with fields according to the config classes.
        default_file_path: str
            fallback file path if config_file is not provided, only used for SQLiteConfig, default is empty string
            which leads to a DB with name of thing ID

        Returns
        -------
        SQLDBConfig | SQLiteConfig | MongoDBConfig
            configuration object according to the provider specified in the config file

        Raises
        ------
        NotImplementedError
            if the provider specified in the config file is not supported
        ValueError
            if the config file is not in JSON format
        """
        if not config_file:
            return SQLiteConfig(file=default_file_path)
        if not config_file.endswith(".json"):
            raise ValueError("config files of extension {} expected, given file name {}".format(["json"], config_file))
        file = open(config_file, "r")
        conf = JSONSerializer.load(file)
        if not isinstance(conf, dict):
            raise ValueError("config file expected to contain a JSON object/dictionary, given {}".format(type(conf)))
        if conf.get("provider", None) in ["postgresql", "mysql"]:
            return SQLDBConfig.model_validate(conf, strict=True, from_attributes=True)
        elif conf.get("provider", None) == "sqlite":
            return SQLiteConfig.model_validate(conf, strict=True, from_attributes=True)
        elif conf.get("provider", None) == "mongo":
            return MongoDBConfig.model_validate(conf, strict=True, from_attributes=True)
        raise NotImplementedError("only postgresql, mysql, sqlite and mongo are supported")

    @property
    def in_batch_call_context(self):
        return threading.get_ident() in self._batch_call_context


__all__ = [
    BaseDB.__name__,
]
