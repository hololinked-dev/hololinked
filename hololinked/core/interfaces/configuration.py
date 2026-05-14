"""Interface class for configuration storage management."""

from typing import Any


class BaseConfigurationRepository:
    """Repository for a `Thing` instance, can be used for storing configuration."""

    def fetch_own_info(self):  # -> ThingInformation:
        """Fetch `Thing` instance's own information (some useful metadata which helps the `Thing` run)."""

    def get_property(self, property: str, deserialized: bool = True) -> Any:
        """
        Fetch a single property.

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

    def set_property(self, property: str, value: Any) -> None:
        """
        Change the value of an already existing property.

        Parameters
        ----------
        property: str | Property
            string name or descriptor object
        value: Any
            value of the property
        """

    def get_properties(self, properties: dict[str, Any], deserialized: bool = True) -> dict[str, Any]:
        """
        Get multiple properties at once.

        Parameters
        ----------
        properties: List[str]
            string names of the properties as a list
        deserialized: bool, default True
            deserialize the properties if True
        """

    def set_properties(self, properties: dict[str, Any]) -> None:
        """
        Change the values of already existing properties at once.

        Parameters
        ----------
        properties: Dict[str, Any]
            string names of the properties and any value as dictionary pairs
        """

    def get_all_properties(self, deserialized: bool = True) -> dict[str, Any]:
        """
        Get all properties of the `Thing` instance.

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
        properties: dict[str, Any],
        get_missing_property_names: bool = False,
    ) -> None | list[str]:
        """
        Create any and all missing properties of `Thing` instance in database.

        Parameters
        ----------
        properties: Dict[str, Any]
            descriptors of the properties
        get_missing_property_names: bool, default False
            whether to return the list of missing property names

        Returns
        -------
        List[str]
            list of missing properties if get_missing_property_names is True
        """

    def create_db_init_properties(self, thing_id: str, thing_class: str, **properties: Any) -> None:
        """
        Create properties that are supposed to be initialized from database for a thing instance.

        Invoke this method once before running the thing instance to store its initial value in database.

        Parameters
        ----------
        thing_id: str
            ID of the thing instance to which these properties belong
        thing_class: str
            Class name of the thing instance to which these properties belong
        properties: dict[str, Any]
            property names and their initial values as dictionary pairs
        """
