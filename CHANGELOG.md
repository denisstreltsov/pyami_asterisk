# Changelog

## Unreleased

- Packaging moved to `pyproject.toml`; version `1.6.0.dev0`; Python 3.10-3.13; `loguru>=0.6,<1`.
- GitHub Actions runs the tests on Python 3.10 and 3.13; Travis CI configuration removed.
- Tests: a fake AMI server over a real TCP socket (`tests/fake_ami.py`), a test pinning the 1.5.2 public API.
- The existing tests no longer rewrite fixture files on import and no longer depend on the working directory.
