# uninstantiated_things = TypedDict(default=None, allow_None=True, key_type=str,
#                                             item_type=str)
    
    
#     @classmethod
#     def _import_thing(cls, file_name : str, object_name : str):
#         """
#         import a thing specified by `object_name` from its 
#         script or module. 

#         Parameters
#         ----------
#         file_name : str
#             file or module path 
#         object_name : str
#             name of `Thing` class to be imported
#         """
#         module_name = file_name.split(os.sep)[-1]
#         spec = importlib.util.spec_from_file_location(module_name, file_name)
#         if spec is not None:
#             module = importlib.util.module_from_spec(spec)
#             spec.loader.exec_module(module)
#         else:     
#             module = importlib.import_module(module_name, file_name.split(os.sep)[0])
#         consumer = getattr(module, object_name) 
#         if issubclass(consumer, Thing):
#             return consumer 
#         else:
#             raise ValueError(f"object name {object_name} in {file_name} not a subclass of Thing.", 
#                             f" Only subclasses are accepted (not even instances). Given object : {consumer}")
        

#     @remote_method()
#     def import_thing(self, file_name : str, object_name : str):
#         """
#         import thing from the specified path and return the default 
#         properties to be supplied to instantiate the object. 
#         """
#         consumer = self._import_thing(file_name, object_name) # type: ThingMeta
#         id = uuid4()
#         self.uninstantiated_things[id] = consumer
#         return id
           

#     @remote_method() # remember to pass schema with mandatory instance name
#     def instantiate(self, id : str, kwargs : typing.Dict = {}):      
#         """
#         Instantiate the thing that was imported with given arguments 
#         and add to the event loop
#         """
#         consumer = self.uninstantiated_things[id]
#         instance = consumer(**kwargs, eventloop_name=self.id) # type: Thing
#         self.things.append(instance)
#         rpc_server = instance.rpc_server
#         self.request_listener_loop.call_soon(asyncio.create_task(lambda : rpc_server.poll()))
#         self.request_listener_loop.call_soon(asyncio.create_task(lambda : rpc_server.tunnel_message_to_things()))
#         if not self.threaded:
#             self.thing_executor_loop.call_soon(asyncio.create_task(lambda : self.run_single_target(instance)))
#         else: 
#             _thing_executor = threading.Thread(target=self.run_things_executor, args=([instance],))
#             _thing_executor.start()