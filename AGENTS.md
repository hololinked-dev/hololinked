## Working Methods

- run the test suite/files pertaining to the code change first and ask permission before running the full suite.
- Never run any test with a large timeout, individual files should finish within 3 minutes and the entire suit should finish in 10 minutes. Always keep track of the log, dont run tests without seeing the log of the test framework at least (say pytest).
- dont add tests without planning
- dont add unnecessary docstrings and obvious comments
- split plans into individual steps that can build on each other if possible, when involving code change crossing 500 lines.