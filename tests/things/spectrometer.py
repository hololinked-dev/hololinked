import datetime
from enum import StrEnum
import threading
import typing
import numpy
from dataclasses import dataclass


from hololinked.core import Thing, Property, action, Event
from hololinked.core.properties import (String, Integer, Number, List, Boolean,
                                    Selector, ClassSelector, TypedList)
from hololinked.core.state_machine import StateMachine
from hololinked.serializers import JSONSerializer
from hololinked.td import JSONSchema
from hololinked.protocols.http import HTTPServer


@dataclass 
class Intensity:
    value : numpy.ndarray
    timestamp : str  

    schema = {
        "type" : "object",
        "properties" : {
            "value" : {
                "type" : "array",
                "items" : {
                    "type" : "number"
                },
            },
            "timestamp" : {
                "type" : "string"
            }
        }
    }

    @property
    def not_completely_black(self):
        if any(self.value[i] > 0 for i in range(len(self.value))):  
            return True 
        return False
    


JSONSerializer.register_type_replacement(numpy.ndarray, lambda obj : obj.tolist())
JSONSchema.register_type_replacement(Intensity, 'object', Intensity.schema)


connect_args = {
    "type": "object",
    "properties": {
        "serial_number": {"type": "string"},
        "trigger_mode": {"type": "integer"},
        "integration_time": {"type": "number"}
    },
    "additionalProperties": False
}



class States(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    ON = "ON"
    FAULT = "FAULT"
    MEASURING = "MEASURING"
    ALARM = "ALARM"


class OceanOpticsSpectrometer(Thing):
    """
    OceanOptics spectrometers Test Thing.
    """

    states = States

    status = String(readonly=True, fget=lambda self: self._status,
                    doc="descriptive status of current operation") # type: str

    serial_number = String(default=None, allow_None=True,  
                    doc="serial number of the spectrometer to connect/or connected")# type: str

    last_intensity = ClassSelector(default=None, allow_None=True, class_=Intensity, 
                    doc="last measurement intensity (in arbitrary units)") # type: Intensity
    
    intensity_measurement_event = Event(friendly_name='intensity-measurement-event', 
            doc="event generated on measurement of intensity, max 30 per second even if measurement is faster.",
            schema=Intensity.schema)
    
    reference_intensity = ClassSelector(default=None, allow_None=True, class_=Intensity,
            doc="reference intensity to overlap in background") # type: Intensity
    
    
    def __init__(self, id : str, serial_number : typing.Optional[str] = None, **kwargs) -> None:
        super().__init__(id=id, serial_number=serial_number, **kwargs)
        self.set_status("disconnected")
        if serial_number is not None:
            self.connect()
        self._acquisition_thread = None 
        self._running = False
       
    def set_status(self, *args) -> None:
        if len(args) == 1:
            self._status = args[0]
        else:
            self._status = ' '.join(args)
            
    @action(input_schema=connect_args)
    def connect(self, serial_number : str = None, trigger_mode : int = None, integration_time : float = None) -> None:
        if serial_number is not None:
            self.serial_number = serial_number
        self.state_machine.current_state = self.states.ON
        self._pixel_count = 50
        self._wavelengths = [i for i in range(self._pixel_count)]
        self._model = 'STS'
        self._max_intensity = 16384
        if trigger_mode is not None:
            self.trigger_mode = trigger_mode
        else:
            self.trigger_mode = self.trigger_mode
            # Will set default value of property
        if integration_time is not None:
            self.integration_time = integration_time
        else:
            self.integration_time = self.integration_time
            # Will set default value of property
        self.logger.debug(f"opened device with serial number {self.serial_number} with model {self.model}")
        self.set_status("ready to start acquisition")

    model = String(default=None, allow_None=True, readonly=True,
                doc="model of the connected spectrometer",
                fget=lambda self: self._model if self.state_machine.current_state != self.states.DISCONNECTED else None
                ) # type: str
    
    wavelengths = List(default=None, allow_None=True, item_type=(float, int), readonly=True,
                    doc="wavelength bins of measurement",
                    fget=lambda self: self._wavelengths if self.state_machine.current_state != self.states.DISCONNECTED else None,
                ) # type: typing.List[typing.Union[float, int]]

    pixel_count = Integer(default=None, allow_None=True, readonly=True,
                doc="number of points in wavelength",
                fget=lambda self: self._pixel_count if self.state_machine.current_state != self.states.DISCONNECTED else None
                ) # type: int
    
    max_intensity = Number(readonly=True,
                    doc="""the maximum intensity that can be returned by the spectrometer in (a.u.). 
                        It's possible that the spectrometer saturates already at lower values.""",
                    fget=lambda self: self._max_intensity if self.state_machine.current_state != self.states.DISCONNECTED else None
                    ) # type: float
      
    @action()
    def disconnect(self):
        self.state_machine.current_state = self.states.DISCONNECTED

    trigger_mode = Selector(objects=[0, 1, 2, 3, 4], default=0, observable=True,
                        doc="""0 = normal/free running, 1 = Software trigger, 2 = Ext. Trigger Level,
                         3 = Ext. Trigger Synchro/ Shutter mode, 4 = Ext. Trigger Edge""") # type: int
    
    @trigger_mode.setter 
    def apply_trigger_mode(self, value : int):
        self._trigger_mode = value 
        
    @trigger_mode.getter 
    def get_trigger_mode(self):
        try:
            return self._trigger_mode
        except:
            return self.properties["trigger_mode"].default 
        

    integration_time = Number(default=1000, bounds=(0.001, None), crop_to_bounds=True, 
                            observable=True,
                            doc="integration time of measurement in milliseconds") # type: float
    
    @integration_time.setter 
    def apply_integration_time(self, value : float):
        self._integration_time = int(value) 
      
    @integration_time.getter 
    def get_integration_time(self) -> float:
        try:
            return self._integration_time
        except:
            return self.properties["integration_time"].default   
    
    background_correction = Selector(objects=['AUTO', 'CUSTOM', None], default=None, allow_None=True, 
                        doc="set True for Seabreeze internal black level correction") # type: typing.Optional[str]
    
    custom_background_intensity = TypedList(item_type=(float, int)) # type: typing.List[typing.Union[float, int]]
    
    nonlinearity_correction = Boolean(default=False, 
                        doc="automatic correction of non linearity in detector CCD") # type: bool

    @action()
    def start_acquisition(self) -> None:
        self.stop_acquisition() # Just a shield 
        self._acquisition_thread = threading.Thread(target=self.measure) 
        self._acquisition_thread.start()

    @action()
    def stop_acquisition(self) -> None:
        if self._acquisition_thread is not None:
            self.logger.debug(f"stopping acquisition thread with thread-ID {self._acquisition_thread.ident}")
            self._running = False # break infinite loop
            # Reduce the measurement that will proceed in new trigger mode to 1ms
            self._acquisition_thread.join()
            self._acquisition_thread = None 
            # re-apply old values
            self.trigger_mode = self.trigger_mode
            self.integration_time = self.integration_time 
        

    def measure(self, max_count = None):
        try:
            self._running = True
            self.state_machine.current_state = self.states.MEASURING
            self.set_status("measuring")
            self.logger.info(f'starting continuous acquisition loop with trigger mode {self.trigger_mode} & integration time {self.integration_time} in thread with ID {threading.get_ident()}')
            loop = 0
            while self._running:
                if max_count is not None and loop > max_count:
                    break 
                loop += 1               
                # Following is a blocking command - self.spec.intensities
                self.logger.debug(f'starting measurement count {loop}')                
                _current_intensity = [numpy.random.randint(0, self.max_intensity) for i in range(self._pixel_count)]
                if self.background_correction == 'CUSTOM':
                    if self.custom_background_intensity is None:
                        self.logger.warn('no background correction possible')
                        self.state_machine.set_state(self.states.ALARM)
                    else:
                        _current_intensity = _current_intensity - self.custom_background_intensity

                curtime = datetime.datetime.now()
                timestamp = curtime.strftime('%d.%m.%Y %H:%M:%S.') + '{:03d}'.format(int(curtime.microsecond /1000))
                self.logger.debug(f'measurement taken at {timestamp} - measurement count {loop}')

                if self._running:
                    # To stop the acquisition in hardware trigger mode, we set running to False in stop_acquisition() 
                    # and then change the trigger mode for self.spec.intensities to unblock. This exits this 
                    # infintie loop. Therefore, to know, whether self.spec.intensities finished, whether due to trigger 
                    # mode or due to actual completion of measurement, we check again if self._running is True. 
                    self.last_intensity = Intensity(
                        value=_current_intensity, 
                        timestamp=timestamp
                    )
                    if self.last_intensity.not_completely_black:   
                        self.intensity_measurement_event.push(self.last_intensity)
                        self.state_machine.current_state = self.states.MEASURING
                    else:
                        self.logger.warn('trigger delayed or no trigger or erroneous data - completely black')
                        self.state_machine.current_state = self.states.ALARM
            if self.state_machine.current_state not in [self.states.FAULT, self.states.ALARM]:        
                self.state_machine.current_state = self.states.ON
                self.set_status("ready to start acquisition")
            self.logger.info("ending continuous acquisition") 
            self._running = False 
        except Exception as ex:
            self.logger.error(f"error during acquisition - {str(ex)}, {type(ex)}")
            self.set_status(f'error during acquisition - {str(ex)}, {type(ex)}')
            self.state_machine.current_state = self.states.FAULT

    @action()
    def start_acquisition_single(self):
        self.stop_acquisition() # Just a shield 
        self._acquisition_thread = threading.Thread(target=self.measure, args=(1,)) 
        self._acquisition_thread.start()
        self.logger.info("data event will be pushed once acquisition is complete.")

    @action()
    def reset_fault(self):
        self.state_machine.set_state(self.states.ON)

    @action()
    def test_echo(self, value):
        return value

    state_machine = StateMachine(
        states=states,
        initial_state=states.DISCONNECTED,
        push_state_change_event=True,
        DISCONNECTED=[connect, serial_number],
        ON=[start_acquisition, start_acquisition_single, disconnect,
            integration_time, trigger_mode, background_correction, nonlinearity_correction],
        MEASURING=[stop_acquisition],
        FAULT=[stop_acquisition, reset_fault]
    )

    logger_remote_access = True

def run_zmq_server():
    thing = OceanOpticsSpectrometer(id='test_spectrometer')
    thing.run_with_zmq_server()


def run_http_server():
    thing = OceanOpticsSpectrometer(id='test_spectrometer')
    server = HTTPServer()
    server.add_things(thing)
    server.listen()


if __name__ == '__main__':
    run_zmq_server()
    # run_http_server()
