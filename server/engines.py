"""Adapters for the supplied, prepared public-data engine cases.

A project prepared by this repository carries a marker file naming its
preparation format. Projects attached by a user have no marker and are run
as-is, without the adapter's publishing step.
"""
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class PublicCase:
    engine: str
    marker: str
    check_prefix: str
    runtime_key: str
    format_detail: str
    engine_detail: str
    published_detail: str

    def module(self) -> ModuleType:
        # Imported lazily: both modules import worker, which imports this one.
        if self.engine == "HEC-RAS 2D":
            from . import hecras as module
        else:
            from . import screening as module
        return module


CASES = {
    "HEC-RAS 2D": PublicCase(
        "HEC-RAS 2D", "hecras-case.json", "hecras", "hec_ras",
        "Use the current prepared HEC-RAS public case.",
        "This exploratory HEC case requires the exact engine build recorded during preparation.",
        "HEC-RAS full SWE completed; native numerical checks passed and timestamped rasters are available. Exploratory and uncalibrated."),
    "LISFLOOD-FP": PublicCase(
        "LISFLOOD-FP", "screening.json", "screening", "lisflood_fp",
        "Use the current prepared public case with channel conditioning, river warm-up and a complete discharge cross-section; earlier preparation versions are superseded.",
        "Exploratory screening requires the exact engine build recorded in its preparation review.",
        "External engine completed; numerical checks passed and timestamped output is available. Exploratory and uncalibrated."),
}


def public_case(engine: str, project) -> PublicCase | None:
    """The adapter that prepared ``project`` for ``engine``, or None for a user model."""
    case = CASES.get(engine)
    if case and project and (Path(project) / case.marker).is_file():
        return case
    return None


CACHED_DETAIL = "Loaded the verified output of this exact prepared case. Exploratory and uncalibrated."


def cached_public_result(scenario, project):
    """Hash-verified published output of this exact prepared public case, if any.

    Raises ValueError when an existing result no longer matches its hashes.
    """
    case = public_case(scenario.hydraulics.engine, project)
    return case.module().cached_result(scenario) if case else None
