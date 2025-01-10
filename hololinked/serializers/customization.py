from .serializers import *


class Serializers:
    json = JSONSerializer()
    pickle = PickleSerializer()
    msgpack = MsgpackSerializer()

    serializers = {
        None : JSONSerializer,
        'json' : JSONSerializer, 
        'pickle' : PickleSerializer,
        'msgpack' : MsgpackSerializer
    }
    serializers['serpent'] = SerpentSerializer

    def register_content_type(self, thing_id: str, objekt: str) -> None:
        "register content type for a serializer"
        raise NotImplementedError("implement in subclass")
    
    def register_content_type_per_instance() -> None:
        raise NotImplementedError("implement in subclass")
    
    def get_serializer_for_objekt(self, objekt: str) -> BaseSerializer:
        "get serializer for a content type"
        raise NotImplementedError("implement in subclass")



def set_serializer_from_user_given_options(
        zmq_serializer : typing.Union[str, BaseSerializer], 
        http_serializer : typing.Union[str, JSONSerializer]
    ) -> typing.Tuple[BaseSerializer, JSONSerializer]:
    """
    We give options to specify serializer as a string or an object,  
    """ 
    if http_serializer in [None, 'json'] or isinstance(http_serializer, JSONSerializer):
        http_serializer = http_serializer if isinstance(http_serializer, JSONSerializer) else JSONSerializer()
    else:
        raise ValueError("invalid JSON serializer option : {}".format(http_serializer))
        # could also technically be TypeError 
    if isinstance(zmq_serializer, BaseSerializer):
        zmq_serializer = zmq_serializer 
        if isinstance(zmq_serializer, PickleSerializer) or zmq_serializer.type == pickle:
            warnings.warn("using pickle serializer which is unsafe, consider another like msgpack.", UserWarning)
    elif zmq_serializer == 'json' or zmq_serializer is None:
        zmq_serializer = http_serializer
    elif isinstance(zmq_serializer, str): 
        zmq_serializer = serializers.get(zmq_serializer, JSONSerializer)()
    else:
        raise ValueError("invalid rpc serializer option : {}".format(zmq_serializer))    
    return zmq_serializer, http_serializer