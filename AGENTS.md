## Working Methods

### Testing

- run the test suite/files pertaining to the code change first and ask permission before running the full suite.
- Never run any test with a large timeout, individual files should finish within 3 minutes and the entire suite should finish in 10 minutes. Always keep track of the log, don't run tests without seeing the log of the test framework at least (say pytest).
- don't long poll test output, update your log record at least every 10 seconds.
- don't add tests without planning.

### Codestyle

- don't add unnecessary docstrings and obvious comments.

### Planning

- split plans into individual steps that can build on each other if possible, when involving code change crossing 500 lines.

### Committing

- Run the pre-commit hooks mentioned in `.pre-commit-config.yaml` whenever changes are complete.
- Don't commit. Don't unstage any changes which you have not done yourself.