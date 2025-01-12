



# @dataclass
# class SecurityScheme(Schema):
#     """
#     create security scheme. 
#     schema - https://www.w3.org/TR/wot-thing-description11/#sec-security-vocabulary-definition
#     """
#     scheme: str 
#     description : str 
#     descriptions : typing.Optional[typing.Dict[str, str]]
#     proxy : typing.Optional[str]

#     def __init__(self):
#         super().__init__()

#     def build(self, name : str, instance):
#         self.scheme = 'nosec'
#         self.description = 'currently no security scheme supported - use cookie auth directly on hololinked.server.HTTPServer object'
#         return { name : self.asdict() }