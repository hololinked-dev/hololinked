from ....core.properties import (
    String,
    Bytes,
    Integer,
    Number,
    Boolean,
    List,
    Tuple
)
from .handlers import PropertyHandler, JPEGImageHandler, PNGImageHandler


handler_map = {
    String: PropertyHandler,
    Bytes: PropertyHandler,
    Integer: PropertyHandler,
    Number: PropertyHandler,
    Boolean: PropertyHandler,
    List: PropertyHandler,
    Tuple: PropertyHandler,
}