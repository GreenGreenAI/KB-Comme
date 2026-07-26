"""External data collection (ECOS, 기업마당).

This package is a leaf: no other TradeFlow module imports it. Collectors run
separately and write snapshot files under `data/snapshots/`, and the calculation
and knowledge layers read only those files. Keeping the dependency on data
rather than on running code is what lets a past snapshot reproduce a past
result, and what keeps the test suite runnable without any external API.

`tests/architecture/test_module_boundaries.py` enforces the leaf property.
"""
