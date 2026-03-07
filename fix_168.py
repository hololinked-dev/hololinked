# path/to/existing/file.py
import warnings

class ThingMeta(type):
    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)

        for attr in attrs:
            if attr in ['oneway', 'noblock']:
                warnings.warn(f"Property or action named '{attr}' is hidden. Use 'body' argument instead.", stacklevel=2)