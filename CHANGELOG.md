# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

✓ means ready to try

## [v0.3.0] - 2025 between Apr-Jun

This release will contain a lot of new features and improvements so that a version 1.0.0 may be published sooner. 
- better conceptual alignment with WoT in code structure
- docs recreated in mkdocs-material, more examples and full coverage of features (hosted [here for now](https://docs.hololinked.dev))
- more tests coverage (over 70%)
- easier to add more protocols (like MQTT, CoAP, etc)
- adding custom handlers for each property, action and event to override default behaviour for HTTP protocol 
- schedule async methods & threaded actions more easily
- supports pydantic models for action schema validation, directly with python typing annotations - no need explicitly specify schema. 
- bug fix to create pydantic models for properties during validation & pass the model to the setter (instead of JSON)
- bug fix to remove shared state machine for multiple instances of the same class in the same process
- bug fix state machine instance creation for multiple instances of the same class in the same process
Not finalised:
- cookie auth & its specification in TD (cookie auth branch)

## [v0.2.10] - 2025-04-05

- bug fixes to support `class_member` properties to work with `fget`, `fset` and `fdel` methods. While using custom `fget`, `fset` and `fdel` methods for `class_member`s,
the class will be passed as the first argument. 

## [v0.2.9] - 2025-03-25

- bug fix to execute action when payload is explicitly null in a HTTP request. Whether action takes a payload or not, there was an error which caused the execution to be rejected. 

## [v0.2.8] - 2024-12-07

- pydantic & JSON schema support for property models 
- composed sub`Thing`s exposed with correct URL path 

## [v0.2.7] - 2024-10-22

- HTTP SSE would previously remain unclosed when client abruptly disconnected (like closing a browser tab), but now it would close correctly
- retrieve unserialized data from events with `ObjectProxy` (like JPEG images) by setting `deserialize=False` in `subscribe_event()` 

## [v0.2.6] - 2024-09-09

- bug fix events when multiple serializers are used
- events support custom HTTP handlers (not polished yet, use as last resort, not auto-added to TD)
- image event handlers for streaming live video as JPEG and PNG (not polished yet, not auto-added to TD)

## [v0.2.5] - 2024-09-09

- released to anaconda, it can take a while to turn up. A badge will be added in README when successful.  

## [v0.2.4] - 2024-09-09

- added multiple versions of python for testing
- unlike claimed in previous versions, this package runs only on python 3.11 or higher

## [v0.2.3] - 2024-08-11

- HTTP SSE minor bug-fix/optimization - no difference to the user 

## [v0.2.2] - 2024-08-09

- thing control panel works better with the server side and support observable properties
- `ObjectProxy` client API has been improved to resemble WoT operations better, for example `get_property` is now 
called `read_property`, `set_properties` is now called `write_multiple_properties`. 
- `ObjectProxy` client reliability for poorly written server side actions improved

## [v0.2.1] - 2024-07-21

### Added
- properties are now "observable" and push change events when read or written & value has changed
- input & output JSON schema can be specified for actions, where input schema is used for validation of arguments
- TD has read/write properties' forms at thing level, event data schema
- change log
- some unit tests

### Changed
- events are to specified as descriptors and are not allowed as instance attributes. Specify at class level to 
  automatically obtain a instance specific event.  

### Fixed
- ``class_member`` argument for properties respected more accurately

## [v0.1.2] - 2024-06-06

### Added
- first public release to pip, docs are the best source to document this release. Checkout commit 
  [04b75a73c28cab298eefa30746bbb0e06221b81c] and build docs if at all necessary.
 


