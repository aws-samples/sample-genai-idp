"""Root conftest — adds the tests/ directory to sys.path so test modules can
`from _helpers import make_appsync_event` without colliding with a `tests`
package that may be installed site-wide.
"""

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent / "tests"
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
