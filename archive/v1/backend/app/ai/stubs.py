"""Explicitly out-of-scope AI features (Section 5, item 7).

These are NOT built in this product phase. The module exists so the
architectural seam is visible and so the future-readiness design notes live
next to the code they will eventually constrain.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# AI dashcam / computer vision - NOT BUILT.
#
# Design note for a future phase (documentation only - no build work now).
# If a dashcam is added later, these privacy-by-design properties must be
# planned for from the first data-model decision, not retrofitted:
#
#   * Pedestrian and bystander identity blurring applied at capture time.
#   * A driver-configurable privacy mode that disables raw video capture while
#     keeping event detection and in-cab audio alerts active.
#   * Explicit, enforced data-retention limits per footage class, with
#     automatic deletion rather than manual pruning.
#   * Any footage reference stored against a Trip/Incident must be a pointer
#     with its own retention clock, never an inline blob on a business table.
# ---------------------------------------------------------------------------


def analyse_dashcam_footage(*args: object, **kwargs: object) -> None:
    """Not implemented - out of scope for MVP (Section 9)."""
    raise NotImplementedError(
        "AI dashcam / computer vision is explicitly out of scope for MVP."
    )


def forecast_fleet_size(*args: object, **kwargs: object) -> None:
    """Not implemented - out of scope for MVP (Section 9)."""
    raise NotImplementedError(
        "Fleet-sizing forecasting is explicitly out of scope for MVP."
    )


def detect_fraud(*args: object, **kwargs: object) -> None:
    """Not implemented - out of scope for MVP (Section 9)."""
    raise NotImplementedError(
        "Fraud detection is explicitly out of scope for MVP."
    )
