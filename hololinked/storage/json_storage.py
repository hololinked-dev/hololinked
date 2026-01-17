import os
import threading

from typing import Any

from ..core.property import Property
from ..param import Parameterized
from ..serializers import JSONSerializer


class ThingJSONStorage:
    """
    JSON-based storage engine composed within `Thing`. Carries out property operations such as storing and
    retrieving values from a plain JSON file.

    Parameters
    ----------
    filename : str
        Path to the JSON file to use for storage.
    instance : Parameterized
        The `Thing` instance which uses this storage. Required to read default property values when
        creating missing properties.
    serializer : JSONSerializer, optional
        Serializer used for encoding and decoding JSON data. Defaults to an instance of `JSONSerializer`.
    """

    def __init__(self, filename: str, instance: Parameterized, serializer: Any = None):
        self.filename = filename
        self.thing_instance = instance
        self.id = instance.id
        self._serializer = serializer or JSONSerializer()
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        """
        Load and decode data from the JSON file.

        Returns
        -------
        dict[str, Any]
            A dictionary of all stored properties. Empty if the file does not exist or cannot be decoded.
        """
        if not os.path.exists(self.filename) or os.path.getsize(self.filename) == 0:
            return {}
        try:
            with open(self.filename, "rb") as f:
                raw_bytes = f.read()
                if not raw_bytes:
                    return {}
                return self._serializer.loads(raw_bytes)
        except Exception:
            return {}

    def _save(self):
        """Encode and write data to the JSON file"""
        raw_bytes = self._serializer.dumps(self._data)
        with open(self.filename, "wb") as f:
            f.write(raw_bytes)

    def get_property(self, property: str | Property) -> Any:
        """
        Fetch a single property.

        Parameters
        ----------
        property: str | Property
            string name or descriptor object

        Returns
        -------
        value: Any
            property value
        """
        name = property if isinstance(property, str) else property.name
        if name not in self._data:
            raise KeyError(f"property {name} not found in JSON storage")
        with self._lock:
            return self._data[name]

    def set_property(self, property: str | Property, value: Any) -> None:
        """
        Change the value of an already existing property.

        Parameters
        ----------
        property: str | Property
            string name or descriptor object
        value: Any
            value of the property
        """
        name = property if isinstance(property, str) else property.name
        with self._lock:
            self._data[name] = value
            self._save()

    def get_properties(self, properties: dict[str | Property, Any]) -> dict[str, Any]:
        """
        Get multiple properties at once.

        Parameters
        ----------
        properties: List[str | Property]
            string names or the descriptor of the properties as a list

        Returns
        -------
        value: Dict[str, Any]
            property names and values as items
        """
        names = [key if isinstance(key, str) else key.name for key in properties.keys()]
        with self._lock:
            return {name: self._data.get(name) for name in names}

    def set_properties(self, properties: dict[str | Property, Any]) -> None:
        """
        Change the values of already existing properties at once.

        Parameters
        ----------
        properties: Dict[str | Property, Any]
            string names or the descriptor of the property and any value as dictionary pairs
        """
        with self._lock:
            for obj, value in properties.items():
                name = obj if isinstance(obj, str) else obj.name
                self._data[name] = value
            self._save()

    def get_all_properties(self) -> dict[str, Any]:
        """Read all properties of the `Thing` instance"""
        with self._lock:
            return dict(self._data)

    def create_missing_properties(
        self,
        properties: dict[str, Property],
        get_missing_property_names: bool = False,
    ) -> list[str] | None:
        """
        Create any and all missing properties of `Thing` instance

        Parameters
        ----------
        properties: Dict[str, Property]
            descriptors of the properties
        get_missing_property_names: bool, default False
            whether to return the list of missing property names

        Returns
        -------
        missing_props: List[str]
            list of missing properties if get_missing_property_names is True
        """
        missing_props = []
        with self._lock:
            existing_props = self.get_all_properties()
            for name, new_prop in properties.items():
                if name not in existing_props:
                    self._data[name] = getattr(self.thing_instance, new_prop.name)
                    missing_props.append(name)
            self._save()
        if get_missing_property_names:
            return missing_props


__all__ = [
    ThingJSONStorage.__name__,
]
