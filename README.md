design decisions:
- test should run in parallel
  - they are isolated (unique network namespace and veth naming)
  - tests don't depend on other tests
  - run in parallel with pytest-xdist
- tests should be able to run in CI and local
  - keep dependencies to minimal
    - depends on: tshark, pytest-xdist
- logs should be clean
  - since it involves networking, log packets
