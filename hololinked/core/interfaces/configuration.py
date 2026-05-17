"""Interface class for configuration storage management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence


if TYPE_CHECKING:
    # postpones evaluation, this is not a runtime import and must not become a runtime dependency of the interfaces.
    # Better would to get rid of the type hint instead, if required.
    from hololinked.core.property import Property
    from hololinked.core.thing import Thing


class BaseConfigurationRepository:
    """
    Repository/Persistence for a `Thing` instance that can be used for storing configuration.

    Model your device setting's as properties and set `db_persist=True`/`db_commit=True` in the property's argument
    to activate persistance. If your server dies and restarts, the settings will be reloaded and applied to your device.

    Different storage backends (like JSON file, SQLAlchemy, MongoDB) are supported and custom backends can be
    implemented by inheriting from this class.
    """

    def __init__(self, thing: Thing) -> None:
        self.thing = thing

    def fetch_own_info(self) -> Any:
        """Fetch `Thing` instance's own information (some useful metadata which could help the `Thing` run)."""

    def get_property(self, property: str | Property, deserialized: bool = True) -> Any:
        """
        Fetch a single property from the configuration storage.

        Parameters
        ----------
        property: str | Property
            string name or descriptor object
        deserialized: bool, default True
            deserialize the property if True

        Returns
        -------
        Any
            property value
        """

    def set_property(self, property: str | Property, value: Any) -> None:
        """
        Change the value of an already existing property in the configuration storage.

        Parameters
        ----------
        property: str | Property
            string name or descriptor object
        value: Any
            value of the property
        """

    def get_properties(self, properties: dict[str | Property, Any], deserialized: bool = True) -> dict[str, Any]:
        """
        Get multiple properties at once from the configuration storage.

        Parameters
        ----------
        properties: List[str | Property]
            string names or the descriptor of the properties as a list
        deserialized: bool, default True
            deserialize the properties if True

        Returns
        -------
        dict[str, Any]
            property names and values as items
        """

    def set_properties(self, properties: dict[str | Property, Any]) -> None:
        """
        Change the values of already existing properties in the configuration storage (at once).

        Parameters
        ----------
        properties: Dict[str | Property, Any]
            string names or the descriptor of the properties and their values.
        """

    def get_all_properties(self, deserialized: bool = True) -> dict[str, Any] | Sequence:
        """
        Get all properties of the `Thing` instance from the configuration storage.

        Parameters
        ----------
        deserialized: bool, default True
            deserialize the properties if True

        Returns
        -------
        dict[str, Any]
            property names and values as items
        """

    def create_missing_properties(
        self,
        properties: dict[str, Property],
        get_missing_property_names: bool = False,
    ) -> None | list[str]:
        """
        Create any and all missing properties of `Thing` instance in the configuration storage.

        Auto-invoked at `Thing.__init__()` and takes effect if new properties are introduced.

        Parameters
        ----------
        properties: Dict[str, Property]
            descriptors of the properties
        get_missing_property_names: bool, default False
            whether to return the list of missing property names

        Returns
        -------
        List[str]
            list of missing properties if get_missing_property_names is True
        """

    def create_init_properties(self, thing_id: str, thing_class: str, **properties: Any) -> None:
        """
        Create properties that are supposed to be initialized from configuration storage.

        Invoke this method once before running the thing instance to store their initial values.

        The `Thing` instance is not accepted as an argument as the method would be used outside its lifecycle.
        ID, class name and initial property names and valeus must match.

        Parameters
        ----------
        thing_id: str
            ID of the thing instance to which these properties belong
        thing_class: str
            Class name of the thing instance to which these properties belong (must be thing.__class__.__name__)
        properties: dict[str, Any]
            property names and their initial values as dictionary pairs
        """
