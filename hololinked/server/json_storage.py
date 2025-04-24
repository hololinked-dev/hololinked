import os
import json
import threading
from .serializers import JSONSerializer
from typing import Any, Dict, List, Optional, Union
from .property import Property
from ..param import Parameterized


class ThingJsonStorage:
    def __init__(self, filename: str, instance: Parameterized, serializer: Optional[Any]=None):
        self.filename = filename
        self.thing_instance = instance
        self.instance_name = instance.instance_name
        self._serializer = serializer or JSONSerializer()
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.filename) or os.path.getsize(self.filename) == 0:
            return {}
        try:
            with open(self.filename, 'rb') as f:
                raw_bytes = f.read()
                if not raw_bytes:
                    return {}
                return self._serializer.loads(raw_bytes)
        except Exception:
            return {}

    def _save(self):
        raw_bytes = self._serializer.dumps(self._data)
        with open(self.filename, 'wb') as f:
            f.write(raw_bytes)

    def get_property(self, property: Union[str, Property]) -> Any:
        name = property if isinstance(property, str) else property.name
        if name not in self._data:
            raise KeyError(f"property {name} not found in JSON storage")
        with self._lock:
            return self._data[name]

    def set_property(self, property: Union[str, Property], value: Any) -> None:
        name = property if isinstance(property, str) else property.name
        with self._lock:
            self._data[name] = value
            self._save()

    def get_properties(self, properties: Dict[Union[str, Property], Any]) -> Dict[str, Any]:
        names = [key if isinstance(key, str) else key.name for key in properties.keys()]
        with self._lock:
            return {name: self._data.get(name) for name in names}

    def set_properties(self, properties: Dict[Union[str, Property], Any]) -> None:
        with self._lock:
            for obj, value in properties.items():
                name = obj if isinstance(obj, str) else obj.name
                self._data[name] = value
            self._save()

    def get_all_properties(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)

    def create_missing_properties(self, properties: Dict[str, Property],
                                  get_missing_property_names: bool = False) -> Optional[List[str]]:
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
    ThingJsonStorage.__name__,
]
