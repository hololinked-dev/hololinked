import typing


from .base import *
from .data_schema import *
from .forms import *
from .security_definitions import *
from .metadata import *
from .interaction_affordance import *
from .tm import ThingModel


class ThingDescription(ThingModel):
    """
    generate Thing Description of W3C Web of Things standard. 
    Refer standard - https://www.w3.org/TR/wot-thing-description11
    Refer schema - https://www.w3.org/TR/wot-thing-description11/#thing
    """
    links: typing.Optional[typing.List[Link]] 
    forms: typing.Optional[typing.List[Form]]
    security: typing.Union[str, typing.List[str]]
    securityDefinitions: SecurityScheme
    schemaDefinitions: typing.Optional[typing.List[DataSchema]]
    
    def generate(self) -> "ThingDescription": 
        super().generate()
        # self.forms = NotImplemented
        # self.links = NotImplemented
        # self.schemaDefinitions = dict(exception=JSONSchema.get_type(Exception))
        # self.add_links()
        # self.add_top_level_forms()
        # self.add_security_definitions()
        return self
    
    # def add_forms(self, protocol)
    
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




