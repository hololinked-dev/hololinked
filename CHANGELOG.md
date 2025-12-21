# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

✓ means ready to try

# [v0.3.10] - 2025-12-xx

- adds a layered architecture in `hololinked.server` for better organization
- update protocol handlers (like HTTP handler and MQTT topic publishers) from `__init__` of their servers through improved dependency injection
- fixes bugs with image streaming and streaming arbitrary content types
- `ignore_errors` in TD generation works better and gaurantees atleast a partial TD generation
- adds API key authentication for HTTP protocol binding

# [v0.3.9] - 2025-12-01

- adds CORS headers for HTTP SSE which went missing from 0.2.x -> 0.3.x transition
- refactor basic security for client using a BasicSecurity class instead of supplying plain username and password
- minor bug fixes in state machine

## [v0.3.8] - 2025-11-15

- supports structlog for logging, with colored logs and updated log statements
- SAST with bandit & gitleaks integrated into CI/CD pipelines
- uses pytest instead of unittests

## [v0.3.7] - 2025-10-30

- supports MQTT

## [v0.3.6] - 2025-10-18

- supports MongoDB as a database for property persistence (see infrastructure project in README to quick-setup)
- adds HTTP handlers for reading/writing multiple properties at once (which used to be supported <0.2.11 but removed later until now by mistake)
- refactors CI/CD pipelines - separate workflows for developing and publishing

## [v0.3.4] - 2025-10-02

- fixes a bug in content type in the forms of TD for HTTP protocol binding, when multiple serializers are used
- one can specify numpy array or arbitrary python objects in pydantic models for properties, actions and events

## [v0.3.3] - 2025-09-25

- updates API reference largely to latest version

## [v0.3.2] - 2025-09-21

- adds TD security definition for BCryptBasicSecurity and ArgsBasicSecurity
- uses httpx for HTTP client instead of tonardo - async support, works better in a jupyter notebook
- bug fixes

## [v0.3.1] - 17.08.2025

Unreleased to pip, only git tag available.

This release contains a lot of new features and improvements so that a version 1.0.0 may be published sooner:

- better conceptual alignment with WoT in code structure
- more tests coverage in both breadth and depth
- schedule async methods & threaded actions more easily
- support pydantic models for action schema validation directly with python typing annotations - no need explicitly specify schema
- easier to add more protocols (like MQTT, CoAP, etc) - protocol bindings are more systematically supported as far as what goes for an WoT compatible RPC
- scripting API (`ObjectProxy`) also support HTTP - client object abstracts operations irrespective of protocol
- `observe_property` op on client side (although we always supported on server side)
- descriptors for all of properties, actions, events and state machine. previously only property was a descriptor
- descriptor registries for idiomatic introspection of a Thing's capabilites
- adding custom handlers for each property, action and event to override default behaviour for HTTP protocol
- HTTP basic auth
- docs recreated in mkdocs-material

## [v0.2.12] - 2025-05-18

- virtual environment with `uv` package manager:
  ⚡ Faster onboarding: New contributors can setup environments in seconds
  📦 Consistent installations: Precise dependency resolution avoids "works on my machine" issues
  🧪 Efficient testing: uv run executes tests with minimal overhead
  please report bugs if any as this is the first iteration of this feature.

## [v0.2.11] - 2025-04-25

- new feature - support for JSON files as backup for property values (use with `db_commit`, `db_persist` and `db_init`). Compatible only with JSON serializable properties.

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

- `class_member` argument for properties respected more accurately

## [v0.1.2] - 2024-06-06

### Added

- first public release to pip, docs are the best source to document this release. Checkout commit
  [04b75a73c28cab298eefa30746bbb0e06221b81c] and build docs if at all necessary.
