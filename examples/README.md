# Examples

One runnable script per guard. Each demonstrates a documented failure mode and
then **the refusal** that follows from it; each prints its fixture's provenance
label (`MEASURED` / `DERIVED` / `ILLUSTRATIVE`) so the basis of the number is
stated rather than assumed. Some failures are measured, some are constructed to
show a mechanism, and the script says which. Run any of them with no
arguments:

```bash
python examples/lookahead.py
python examples/outliers.py
python examples/windows.py
python examples/universe.py
python examples/multiplicity.py
python examples/series.py
python examples/bootstrap.py
python examples/refused_report.py   # the full pipeline, end to end
python examples/clean_control.py    # the negative direction: CERTIFIED
```

Every script is offline, deterministic and dependency-free beyond
`honest-backtest` itself.
