oscilloscope_TD = {
    "id": "oscilloscope",
    "title": "Oscilloscope",
    "properties": {
        "time_resolution": {"type": "number", "minimum": 0},
        "channel_count": {"type": "integer", "readOnly": True},
        "comment": {"type": "string", "default": "scope"},
    },
    "actions": {
        "start_acquisition": {
            "input": {"type": "object", "properties": {"channel": {"type": "integer"}}, "required": ["channel"]},
        },
        "stop": {},
        "set_trigger_level": {"input": {"type": "number"}, "output": {"type": "number"}},
        "configure_channel": {
            "input": {
                "type": "object",
                "properties": {
                    "channel": {"type": "integer"},
                    "volts_per_division": {"type": "number", "minimum": 0},
                },
                "required": ["channel", "volts_per_division"],
            },
            "output": {"type": "number"},
        },
    },
    "events": {
        "data_ready": {"data": {"type": "array", "items": {"type": "number"}}},
    },
}


class OscilloscopeDriver:
    """no hololinked dependency, implements oscilloscope_TD by its members."""

    def __init__(self) -> None:
        self._resolution = 1.0
        self._comment = "driver"
        self.stopped = False
        self.trigger_level = 0.0
        self.volts_per_division = {}

    @property
    def time_resolution(self) -> float:
        return self._resolution

    @time_resolution.setter
    def time_resolution(self, value: float) -> None:
        self._resolution = value

    @property
    def channel_count(self) -> int:
        return 4

    @property
    def comment(self) -> str:
        return self._comment

    @comment.setter
    def comment(self, value: str) -> None:
        self._comment = value

    def start_acquisition(self, channel: int) -> int:
        self.data_ready.push([1.0, 2.0])
        return channel

    async def stop(self) -> None:
        self.stopped = True

    def set_trigger_level(self, level: float) -> float:
        self.trigger_level = level
        return level

    def configure_channel(self, channel: int, volts_per_division: float) -> float:
        """returns the full scale range over 10 vertical divisions"""
        self.volts_per_division[channel] = volts_per_division
        return volts_per_division * 10
