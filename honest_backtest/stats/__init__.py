"""Statistical machinery, stdlib only.

:mod:`~.bootstrap` supplies the default confidence-interval method (block
bootstrap, not a naive trade-level one) and a permutation null for shape tests.
"""

from __future__ import annotations

from .bootstrap import (
    BlockBootstrapResult,
    PermutationResult,
    block_bootstrap_ci,
    bootstrap_mean_by_block,
    monday_anchored_block,
    permutation_null,
    week_index,
)

__all__ = [
    "block_bootstrap_ci",
    "BlockBootstrapResult",
    "permutation_null",
    "PermutationResult",
    "monday_anchored_block",
    "week_index",
    "bootstrap_mean_by_block",
]
