"""
Storage backends for `Thing` instances.

When properties are written, their values can be dispatched to store them in different storage backends.
Whenever the `Thing` instance is reinitialized, these stored values can be reloaded.
This helps to backup running configuration and survive those values in case of power-cycles or crashes.
"""
