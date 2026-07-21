## Task 2: Session windows with minute precision

**Files:**
- Create: `engine/smc_canonical.py` (start the module with helpers)
- Test: inside `engine/smc_canonical.py` `demo()`

**Interfaces:**
- Produces: `in_session(ts, sessions_utc, server_utc_offset) -> bool` where `sessions_utc` is `[[h1,m1,h2,m2], ...]` half-open `[start,end)` in UTC minutes.

- [ ] **Step 1: Write the failing test.** Create `engine/smc_canonical.py` with a module docstring and a `demo()` containing:

```python
def demo():
    import pandas as pd
    sess = [[7, 0, 10, 0], [12, 0, 15, 30]]
    T = lambda h, m: pd.Timestamp(f"2026-01-05 {h:02d}:{m:02d}", tz="UTC")
    # offset 0
    assert in_session(T(7, 0), sess, 0)          # London start inclusive
    assert not in_session(T(10, 0), sess, 0)     # London end exclusive
    assert in_session(T(15, 29), sess, 0)        # NY still in
    assert not in_session(T(15, 30), sess, 0)    # NY end exclusive
    assert not in_session(T(11, 0), sess, 0)     # gap between sessions
    # broker offset +2: candle stamp 09:00 broker = 07:00 UTC -> London start
    assert in_session(T(9, 0), sess, 2)
    assert not in_session(T(8, 59), sess, 2)     # 06:59 UTC
    print("[OK] in_session: minute precision + offset")
```

- [ ] **Step 2: Run to verify it fails.** Run: `python -m engine.smc_canonical`  Expected: FAIL (`in_session` undefined).

- [ ] **Step 3: Implement `in_session`.** Add near the top of `engine/smc_canonical.py`:

```python
from __future__ import annotations
import pandas as pd
from engine.models import Bundle, Setup, SmcState
from engine import indicators as ind


def in_session(ts: pd.Timestamp, sessions_utc: list[list[int]], server_utc_offset: int = 0) -> bool:
    """True if ts (broker candle time) falls in any [start,end) UTC window.
    sessions_utc entries are [start_h, start_m, end_h, end_m]."""
    utc_min = ((ts.hour - server_utc_offset) % 24) * 60 + ts.minute
    for sh, sm, eh, em in sessions_utc:
        if sh * 60 + sm <= utc_min < eh * 60 + em:
            return True
    return False
```

- [ ] **Step 4: Run to verify it passes.** Run: `python -m engine.smc_canonical`  Expected: PASS `[OK] in_session: ...`.

- [ ] **Step 5: Commit.**

```bash
git add engine/smc_canonical.py
git commit -m "feat(smc): minute-precision session gate"
```

---

