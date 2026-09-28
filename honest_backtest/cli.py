"""Command-line interface.

The CLI exists so the refusal is visible from a shell with no Python written.
It aggregates a small JSON result set, runs every guard the data can support,
and exits non-zero on ``REFUSED`` -- so a CI job can gate on it and a human can
read why.

Exit codes::

    0   CERTIFIED
    1   SUSPECT
    2   REFUSED
    3   usage error (bad input file, bad config)

The exit codes are ordered by severity so that ``honest-backtest check ... ||
alert`` does the obvious thing. Note that ``SUSPECT`` is *not* success: it
exits 1, because a result you may not report as a finding is not a passing
build.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

from .guards.multiplicity import ExperimentCounter
from .guards.universe import Selection
from .guards.windows import WindowPlan
from .report import Config, HonestyReport, ResultSet
from .types import HonestyError, RefusedError, Verdict

__all__ = ["build_parser", "load_result_set", "main", "run_check"]

EXIT = {Verdict.CERTIFIED: 0, Verdict.SUSPECT: 1, Verdict.REFUSED: 2}
USAGE_ERROR = 3

def _example_payload() -> dict[str, object]:
    """The built-in example: the real measured fixtures, bundled.

    Built from :mod:`honest_backtest.fixtures` rather than hand-written here, so
    the CLI reproduces the *same* numbers the tests and examples do. A separate
    copy of the data would drift, and a fixture that drifts is a fixture that
    stops testing what it claims to test.
    """
    from . import fixtures

    nested = fixtures.NESTED_FOUR_SPLIT
    starts = nested["starts"]
    shared_end = nested["shared_end"]
    assert isinstance(starts, list) and isinstance(shared_end, date)
    plan = [f"{s.isoformat()}..{shared_end.isoformat()}" for s in starts]  # type: ignore[attr-defined]

    return {
        "name": "copier_pnl + nine_of_twelve + nested walk-forward (measured fixtures)",
        "split_effects": list(fixtures.COPIER_PNL["effects"]),  # type: ignore[arg-type]
        "split_distances_days": list(fixtures.COPIER_PNL["distances_days"]),  # type: ignore[arg-type]
        "window_excesses": list(fixtures.NINE_OF_TWELVE["excesses"]),  # type: ignore[arg-type]
        "win_count": fixtures.NINE_OF_TWELVE["win_count"],
        "trade_pnls": list(fixtures.TOP_DECILE_121["pnls"]),  # type: ignore[arg-type]
        "series_values": fixtures._spliced_series(),  # noqa: SLF001 - shared fixture
        "window_plan": plan,
        "window_plan_label": "walk_forward",
    }



def _parse_dates(raw: Sequence[str]) -> tuple[date, ...]:
    return tuple(date.fromisoformat(d) for d in raw)


def _parse_timestamps(raw: Sequence[str]) -> tuple[datetime, ...]:
    return tuple(datetime.fromisoformat(t) for t in raw)


def load_result_set(path: Path) -> tuple[ResultSet, Config, dict[str, object]]:
    """Load a JSON payload into a :class:`ResultSet`, a :class:`Config` and
    the extra multiplicity inputs.

    The JSON schema is deliberately flat and forgiving -- this is a validation
    tool, not a data platform, and rejecting a nearly-correct file would push
    people back to ad-hoc scripts, which is where the self-deception lives.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HonestyError(f"cannot read result set {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise HonestyError(f"result set {path} must be a JSON object")

    def floats(key: str) -> tuple[float, ...]:
        seq = raw.get(key, [])
        if not isinstance(seq, list):
            raise HonestyError(f"{key!r} must be a list of numbers")
        try:
            return tuple(float(x) for x in seq)
        except (TypeError, ValueError) as exc:
            raise HonestyError(f"{key!r} contains a non-numeric entry") from exc

    name = str(raw.get("name", path.stem))
    window_plan: WindowPlan | None = None
    if isinstance(raw.get("window_plan_spec"), str):
        window_plan = WindowPlan.from_spec(
            str(raw["window_plan_spec"]), label=str(raw.get("window_plan_label", "cli"))
        )
    elif isinstance(raw.get("window_plan"), list):
        entries = raw["window_plan"]
        if not isinstance(entries, list):
            raise HonestyError("'window_plan' must be a list of 'start..end' strings")
        windows = []
        for i, entry in enumerate(entries):
            label = f"w{i + 1}"
            windows.append(
                WindowPlan.from_spec(str(entry), label=label).windows[0]
            )
        window_plan = WindowPlan(
            windows=tuple(windows),
            label=str(raw.get("window_plan_label", "cli")),
        )

    cohort: Selection[object] | None = None
    benchmark: Selection[object] | None = None
    if "cohort" in raw and "benchmark" in raw:
        c = raw["cohort"]
        b = raw["benchmark"]
        assert isinstance(c, dict) and isinstance(b, dict)
        shared = _shared_predicate(int(c.get("min_age_days", 0)))
        cohort = Selection(
            name=str(c.get("name", "cohort")),
            predicate=shared,
            selected=tuple(c.get("members", [])),
        )
        benchmark = Selection(
            name=str(b.get("name", "benchmark")),
            predicate=shared,
            selected=tuple(b.get("members", [])),
        )

    result = ResultSet(
        name=name,
        split_effects=floats("split_effects"),
        split_distances_days=floats("split_distances_days"),
        split_dates=_parse_dates(raw.get("split_dates", []) or []),
        snapshot_date=(
            date.fromisoformat(str(raw["snapshot_date"]))
            if raw.get("snapshot_date")
            else None
        ),
        window_excesses=floats("window_excesses"),
        win_count=int(raw["win_count"]) if raw.get("win_count") is not None else None,
        trade_pnls=floats("trade_pnls"),
        window_plan=window_plan,
        cohort=cohort,
        benchmark=benchmark,
        series_values=floats("series_values"),
        series_timestamps=_parse_timestamps(raw.get("series_timestamps", []) or []),
        series_step_seconds=(
            float(raw["series_step_seconds"])
            if raw.get("series_step_seconds") is not None
            else None
        ),
    )

    cfg_raw = raw.get("config", {})
    if not isinstance(cfg_raw, dict):
        raise HonestyError("'config' must be a JSON object")
    cfg = Config(
        **{
            k: v
            for k, v in cfg_raw.items()
            if k in Config.__dataclass_fields__  # type: ignore[attr-defined]
        },
        assert_no_unguarded_construction=True,
    )
    extra: dict[str, object] = {
        "claimed_p": raw.get("claimed_p"),
        "n_nominal_positives": raw.get("n_nominal_positives"),
        "n_experiments": raw.get("n_experiments"),
    }
    return result, cfg, extra


def _shared_predicate(min_age_days: int) -> object:
    """Build the eligibility predicate used for *both* sides.

    The CLI constructs one object and hands it to both selections. That is the
    point: there is no code path in this file that builds two.
    """

    def eligible(subject: object) -> bool:
        if isinstance(subject, dict):
            age = subject.get("age_days", 0)
            dormant = subject.get("dormant", False)
            try:
                age_val = int(age)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
            return age_val >= min_age_days and not bool(dormant)
        return True

    return eligible


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="honest-backtest",
        description=(
            "Run every honesty guard that a result set can support and emit one "
            "verdict. Exit 0 CERTIFIED, 1 SUSPECT, 2 REFUSED, 3 usage error."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="validate a JSON result set")
    check.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="path to a JSON result set; omit and pass --example to use the fixture",
    )
    check.add_argument(
        "--example",
        action="store_true",
        help="run the built-in contaminated fixture instead of a file",
    )
    check.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    check.add_argument(
        "--quiet", action="store_true", help="suppress the explanation, keep the verdict"
    )
    check.add_argument(
        "--min-independent-windows",
        type=int,
        default=None,
        help="override Config.min_independent_windows",
    )
    check.add_argument(
        "--guard",
        action="append",
        default=None,
        help="restrict to this guard (repeatable); default is all applicable",
    )

    for name, helptext in (
        ("lookahead", "distance-decay contamination diagnostic"),
        ("outliers", "mean/median disagreement and tail concentration"),
        ("windows", "independent-window counting"),
        ("universe", "cohort/benchmark predicate symmetry"),
        ("multiplicity", "family-wise error accounting"),
        ("series", "splice, padding and index contiguity"),
    ):
        g = sub.add_parser(name, help=helptext)
        g.add_argument("--json", action="store_true", help="emit machine-readable JSON")
        g.add_argument(
            "--example",
            action="store_true",
            help="use the built-in fixture for this guard",
        )
        if name == "lookahead":
            g.add_argument("--r-threshold", type=float, default=0.5)
        if name == "outliers":
            g.add_argument("--top-fraction", type=float, default=0.10)
        if name == "windows":
            g.add_argument("--min-independent", type=int, default=2)
        if name == "multiplicity":
            g.add_argument("--n-experiments", type=int, default=341)
            g.add_argument("--p", type=float, default=0.03)
        if name == "series":
            g.add_argument("--splice-ratio", type=float, default=25.0)

    return parser


def run_check(args: argparse.Namespace) -> int:
    """Execute the ``check`` subcommand; return the process exit code."""
    if args.example or args.path is None:
        raw = _example_payload()
        tmp = Path("_example_result.json")
        tmp.write_text(json.dumps(raw), encoding="utf-8")
        try:
            result, cfg, extra = load_result_set(tmp)
        finally:
            tmp.unlink(missing_ok=True)
    else:
        result, cfg, extra = load_result_set(args.path)

    if args.min_independent_windows is not None:
        cfg = Config(
            **{
                **cfg.as_dict(),  # type: ignore[arg-type]
                "min_independent_windows": args.min_independent_windows,
                "guard_subset": tuple(args.guard or ()),
            }
        )
    elif args.guard:
        cfg = Config(
            **{
                **cfg.as_dict(),  # type: ignore[arg-type]
                "guard_subset": tuple(args.guard),
            }
        )

    n_experiments = extra.get("n_experiments")
    counter: ExperimentCounter | None = None
    if n_experiments is not None:
        counter = ExperimentCounter(alpha=cfg.alpha, correction=cfg.correction)  # type: ignore[arg-type]
        for i in range(int(n_experiments)):  # type: ignore[arg-type]
            counter.record(f"config-{i}")

    report = HonestyReport.run(
        result,
        config=cfg,
        counter=counter,
        claimed_p=extra.get("claimed_p"),  # type: ignore[arg-type]
        n_nominal_positives=extra.get("n_nominal_positives"),  # type: ignore[arg-type]
    )

    if args.json:
        sys.stdout.write(report.to_json() + "\n")
    else:
        sys.stdout.write(report.explanation() + "\n")
        if not args.quiet:
            sys.stdout.write(
                f"\n{len(report.failures())} blocking finding(s); "
                f"guards run: {', '.join(report.ran_guards) or 'none'}\n"
            )
    return EXIT[report.verdict]


def _guard_subcommands(args: argparse.Namespace) -> int:
    """Run a single guard against its built-in fixture."""
    from . import fixtures

    name = args.command
    payload = fixtures.GUARD_FIXTURES[name]()
    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(fixtures.render(name) + "\n")
    verdict = Verdict(str(payload["verdict"]))
    return EXIT[verdict]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return run_check(args)
        return _guard_subcommands(args)
    except RefusedError as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return EXIT[Verdict.REFUSED]
    except HonestyError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return USAGE_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
