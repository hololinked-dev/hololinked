import typing


from .base import *
from .data_schema import *
from .forms import *
from .security_definitions import *
from .metadata import *
from .interaction_affordance import *
from ..core.state_machine import StateMachine



class ThingDescription(Schema):
    """
    generate Thing Description of W3C Web of Things standard. 
    Refer standard - https://www.w3.org/TR/wot-thing-description11
    Refer schema - https://www.w3.org/TR/wot-thing-description11/#thing
    """
    context: typing.List[str] | str | typing.Dict[str, str] = "https://www.w3.org/2022/wot/td/v1.1"
    type: typing.Optional[typing.Union[str, typing.List[str]]]
    id : str 
    title : str 
    description : str 
    version : typing.Optional[VersionInfo]
    created : typing.Optional[str] 
    modified : typing.Optional[str]
    support : typing.Optional[str] 
    base : typing.Optional[str] 
    properties : typing.List[DataSchema]
    actions : typing.List[ActionAffordance]
    events : typing.List[EventAffordance]
    links : typing.Optional[typing.List[Link]] 
    forms : typing.Optional[typing.List[Form]]
    security : typing.Union[str, typing.List[str]]
    securityDefinitions : SecurityScheme
    schemaDefinitions : typing.Optional[typing.List[DataSchema]]
    
    def __init__(self, 
                instance: "Thing", 
                allow_loose_schema: typing.Optional[bool] = False, 
                ignore_errors: bool = False
            ) -> None:
        super().__init__()
        self.instance = instance
        self.allow_loose_schema = allow_loose_schema
        self.ignore_errors = ignore_errors

    def produce(self) -> "ThingDescription": 

        self.id = self.instance.id
        self.title = self.instance.__class__.__name__ 
        self.description = Schema.format_doc(self.instance.__doc__) if self.instance.__doc__ else "no class doc provided" 
        self.properties = dict()
        self.actions = dict()
        self.events = dict()
        # self.forms = NotImplemented
        # self.links = NotImplemented
        # self.schemaDefinitions = dict(exception=JSONSchema.get_type(Exception))

        self.add_interaction_affordances()
        # self.add_links()
        # self.add_top_level_forms()
        # self.add_security_definitions()
       
        return self
    
#     def add_links(self):
#         for name, resource in self.instance.sub_things.items():
#             if resource is self.instance: # or isinstance(resource, EventLoop):
#                 continue
#             if self.links is None:
#                 self.links = []
#             link = Link()
#             link.build(resource, self.instance, self.authority)
#             self.links.append(link.asdict())
    

#     def add_top_level_forms(self):

#         self.forms = []

#         properties_end_point = f"{self.authority}{self.instance._full_URL_path_prefix}/properties"

#         readallproperties = Form()
#         readallproperties.href = properties_end_point
#         readallproperties.op = "readallproperties"
#         readallproperties.htv_methodName = "GET"
#         readallproperties.contentType = "application/json"
#         # readallproperties.additionalResponses = [AdditionalExpectedResponse().asdict()]
#         self.forms.append(readallproperties.asdict())
        
#         writeallproperties = Form() 
#         writeallproperties.href = properties_end_point
#         writeallproperties.op = "writeallproperties"   
#         writeallproperties.htv_methodName = "PUT"
#         writeallproperties.contentType = "application/json" 
#         # writeallproperties.additionalResponses = [AdditionalExpectedResponse().asdict()]
#         self.forms.append(writeallproperties.asdict())

#         readmultipleproperties = Form()
#         readmultipleproperties.href = properties_end_point
#         readmultipleproperties.op = "readmultipleproperties"
#         readmultipleproperties.htv_methodName = "GET"
#         readmultipleproperties.contentType = "application/json"
#         # readmultipleproperties.additionalResponses = [AdditionalExpectedResponse().asdict()]
#         self.forms.append(readmultipleproperties.asdict())

#         writemultipleproperties = Form() 
#         writemultipleproperties.href = properties_end_point
#         writemultipleproperties.op = "writemultipleproperties"   
#         writemultipleproperties.htv_methodName = "PATCH"
#         writemultipleproperties.contentType = "application/json"
#         # writemultipleproperties.additionalResponses = [AdditionalExpectedResponse().asdict()]
#         self.forms.append(writemultipleproperties.asdict())
  
        
#     def add_security_definitions(self):
#         self.security = 'unimplemented'
#         self.securityDefinitions = SecurityScheme().build('unimplemented', self.instance)


#     def json(self) -> JSON:
#         return self.asdict()




