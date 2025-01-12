
# @dataclass
# class ThingDescription(Schema):
#     """
#     generate Thing Description schema of W3 Web of Things standard. 
#     Refer standard - https://www.w3.org/TR/wot-thing-description11
#     Refer schema - https://www.w3.org/TR/wot-thing-description11/#thing
#     """
#     context : typing.Union[typing.List[str], str, typing.Dict[str, str]] 
#     type : typing.Optional[typing.Union[str, typing.List[str]]]
#     id : str 
#     title : str 
#     description : str 
#     version : typing.Optional[VersionInfo]
#     created : typing.Optional[str] 
#     modified : typing.Optional[str]
#     support : typing.Optional[str] 
#     base : typing.Optional[str] 
#     properties : typing.List[DataSchema]
#     actions : typing.List[ActionAffordance]
#     events : typing.List[EventAffordance]
#     links : typing.Optional[typing.List[Link]] 
#     forms : typing.Optional[typing.List[Form]]
#     security : typing.Union[str, typing.List[str]]
#     securityDefinitions : SecurityScheme
#     schemaDefinitions : typing.Optional[typing.List[DataSchema]]
    
#     skip_properties = ['expose', 'httpserver_resources', 'zmq_resources', 'gui_resources',
#                     'events', 'thing_description', 'GUI', 'object_info' ]

#     skip_actions = ['_set_properties', '_get_properties', '_add_property', '_get_properties_in_db', 
#                     'get_postman_collection', 'get_thing_description', 'get_our_temp_thing_description']

#     # not the best code and logic, but works for now

#     def __init__(self, instance : "Thing", authority : typing.Optional[str] = None, 
#                     allow_loose_schema : typing.Optional[bool] = False, ignore_errors : bool = False) -> None:
#         super().__init__()
#         self.instance = instance
#         self.authority = authority
#         self.allow_loose_schema = allow_loose_schema
#         self.ignore_errors = ignore_errors

#     def produce(self) -> JSON: 
#         self.context = "https://www.w3.org/2022/wot/td/v1.1"
#         self.id = f"{self.authority}/{self.instance.id}"
#         self.title = self.instance.__class__.__name__ 
#         self.description = Schema.format_doc(self.instance.__doc__) if self.instance.__doc__ else "no class doc provided" 
#         self.properties = dict()
#         self.actions = dict()
#         self.events = dict()
#         self.forms = NotImplemented
#         self.links = NotImplemented
        
#         # self.schemaDefinitions = dict(exception=JSONSchema.get_type(Exception))

#         self.add_interaction_affordances()
#         self.add_links()
#         self.add_top_level_forms()
#         self.add_security_definitions()
       
#         return self
    

#     def add_interaction_affordances(self):
#         # properties 
#         for prop in self.instance.properties.descriptors.values():
#             if not isinstance(prop, Property) or not prop.remote or prop.name in self.skip_properties: 
#                 continue
#             if prop.name == 'state' and (not hasattr(self.instance, 'state_machine') or 
#                                 not isinstance(self.instance.state_machine, StateMachine)):
#                 continue
#             try:
#                 if (resource.isproperty and resource.obj_name not in self.properties and 
#                     resource.obj_name not in self.skip_properties and hasattr(resource.obj, "_remote_info") and 
#                     resource.obj._remote_info is not None): 
#                     if (resource.obj_name == 'state' and (not hasattr(self.instance, 'state_machine') or 
#                                 not isinstance(self.instance.state_machine, StateMachine))):
#                         continue
#                     if resource.obj_name not in self.instance.properties:
#                         continue 
#                     self.properties[resource.obj_name] = PropertyAffordance.generate_schema(resource.obj, 
#                                                                             self.instance, self.authority) 
                
#                 elif (resource.isaction and resource.obj_name not in self.actions and 
#                     resource.obj_name not in self.skip_actions and hasattr(resource.obj, '_remote_info')):

#                     if resource.bound_obj != self.instance or (resource.obj_name == 'exit' and 
#                             self.instance._owner is not None) or (not hasattr(resource.bound_obj, 'db_engine') and
#                             resource.obj_name == 'load_properties_from_DB'):
#                         continue
#                     self.actions[resource.obj_name] = ActionAffordance.generate_schema(resource.obj, 
#                                                                                 self.instance, self.authority)
#                 self.properties[prop.name] = PropertyAffordance.generate_schema(prop, self.instance, self.authority) 
#             except Exception as ex:
#                 if not self.ignore_errors:
#                     raise ex from None
#                 self.instance.logger.error(f"Error while generating schema for {prop.name} - {ex}")
#         # actions       
#         for name, resource in self.instance.actions.items():
#             if name in self.skip_actions:
#                 continue    
#             try:       
#                 self.actions[resource.obj_name] = ActionAffordance.generate_schema(resource.obj, self.instance, 
#                                                                                self.authority)
#             except Exception as ex:
#                 if not self.ignore_errors:
#                     raise ex from None
#                 self.instance.logger.error(f"Error while generating schema for {name} - {ex}")
#         # events
#         for name, resource in self.instance.events.items():
#             try:
#                 self.events[name] = EventAffordance.generate_schema(resource, self.instance, self.authority)
#             except Exception as ex:
#                 if not self.ignore_errors:
#                     raise ex from None
#                 self.instance.logger.error(f"Error while generating schema for {resource.obj_name} - {ex}")

#         self.add_links()
    
    
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




