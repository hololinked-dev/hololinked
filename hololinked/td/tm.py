from dataclasses import dataclass

from .base import Schema


@dataclass
class ThingModel(Schema):


    def __init__(self, 
                instance, 
                ignore_errors: bool = False
            ) -> None:
        super().__init__()

    def produce(self) -> "ThingModel":
        return self