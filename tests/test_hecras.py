"""Synthetic HDF fixtures test rejection of incomplete/unstable native runs."""

from datetime import timedelta
from pathlib import Path

import h5py
import numpy as np
import pytest

from server.models import Scenario
from server.hecras import _native_output, AREA, NAME, WARMUP_HOURS


@pytest.fixture
def native_case(tmp_path):
    scenario = Scenario.model_validate_json(
        Path("examples/nowshera-2022.json").read_text()
    )
    scenario.time.end = scenario.time.start + timedelta(hours=2)
    start = scenario.time.start - timedelta(hours=WARMUP_HOURS)
    dates = [start + timedelta(hours=i) for i in range(WARMUP_HOURS + 3)]
    path = tmp_path / f"{NAME}.p01.hdf"
    with h5py.File(path, "w") as hdf:
        hdf.attrs["Units System"] = np.bytes_("SI Units")
        hdf["Results/Summary/Compute Messages (text)"] = np.array(
            [
                b"2D Unsteady SWE-ELM Equation Set\nFinished Unsteady Flow Simulation\nOverall Volume Accounting Error as percentage: 0.001\n"
            ]
        )
        hdf["Geometry/2D Flow Areas/Attributes"] = np.array(
            [(AREA.encode(), 2)], dtype=[("Name", "S16"), ("Cell Count", "i4")]
        )
        geom = hdf.require_group(f"Geometry/2D Flow Areas/{AREA}")
        geom["Cells Minimum Elevation"] = np.zeros(2)
        geom["Faces Cell Indexes"] = [[0, 1], [0, 2], [1, 3]]
        geom["FacePoints Coordinate"] = [[0, 0], [1, 0], [2, 0], [0, 1], [1, 1], [2, 1]]
        geom["Cells FacePoint Indexes"] = [[0, 1, 4, 3], [1, 2, 5, 4]]
        hdf["Geometry/Boundary Condition Lines/Attributes"] = np.array(
            [(b"HMS Inflow",), (b"Downstream",)], dtype=[("Name", "S32")]
        )
        hdf["Geometry/Boundary Condition Lines/External Faces"] = np.array(
            [(0, 1), (1, 2)], dtype=[("BC Line ID", "i4"), ("Face Index", "i4")]
        )
        ts = hdf.require_group(
            "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
        )
        ts["Time Date Stamp"] = np.array(
            [date.strftime("%d%b%Y %H:%M:%S").upper().encode() for date in dates]
        )
        area = ts.require_group(f"2D Flow Areas/{AREA}")
        area["Water Surface"] = np.ones((len(dates), 2))
        area["Face Velocity"] = np.ones((len(dates), 3))
        for boundary in ["HMS Inflow", "Downstream"]:
            area[f"Boundary Conditions/{boundary}"] = np.tile(
                [1.0, 1000.0], (len(dates), 1)
            )
        area["Computations/Volume"] = np.full((len(dates), 1), 10.0)
        area["Reference Lines/Name"] = np.array([b"Nowshera gauge"])
        area["Reference Lines/Flow"] = np.full((len(dates), 1), 1000.0)
    return tmp_path, scenario, path


def test_native_output_checks_complete_window_and_connected_warmup(native_case):
    project, scenario, _ = native_case
    result = _native_output(project, scenario)
    assert result["review"]["passed"]
    assert result["review"]["wet_inlet_to_outlet_connection"]
    assert result["review"]["volume_accounting_error_percent"] == 0.001
    assert result["dates"][-1] == scenario.time.end


@pytest.mark.parametrize(
    "failure", ["unstable", "partial", "mass", "nan", "unconverged", "disconnected"]
)
def test_native_output_rejects_unacceptable_hydraulics(native_case, failure):
    project, scenario, path = native_case
    with h5py.File(path, "r+") as hdf:
        ts = hdf[
            "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
        ]
        area = ts[f"2D Flow Areas/{AREA}"]
        if failure in {"unstable", "mass"}:
            messages = hdf["Results/Summary/Compute Messages (text)"][0]
            del hdf["Results/Summary/Compute Messages (text)"]
            hdf["Results/Summary/Compute Messages (text)"] = np.array(
                [
                    (
                        messages + b"2D Solution went unstable"
                        if failure == "unstable"
                        else messages.replace(b"0.001", b"2.5")
                    )
                ]
            )
        elif failure == "partial":
            ts["Time Date Stamp"][-1] = ts["Time Date Stamp"][-2]
        elif failure == "nan":
            area["Water Surface"][0, 0] = np.nan
        elif failure == "unconverged":
            area["Boundary Conditions/Downstream"][:, 1] = 500.0
        else:
            area["Water Surface"][:, 1] = 0.0
    with pytest.raises(ValueError):
        _native_output(project, scenario)


@pytest.mark.parametrize(
    "failure", [None, "uniform", "missing_association", "nonfinite", "out_of_range"]
)
def test_zoned_case_requires_actual_valid_native_cell_and_face_roughness(
    native_case, failure
):
    from server.store import write_json

    project, scenario, path = native_case
    write_json(
        project / "hecras-case.json",
        {"roughness_zones": {"classes": [{"n": 0.035}, {"n": 0.10}]}},
    )
    with h5py.File(path, "r+") as hdf:
        hdf["Geometry"].attrs["Complete Geometry"] = np.bytes_("True")
        hdf["Geometry"].attrs["Land Cover Filename"] = np.bytes_(
            ".\\Land Classification\\Fixture.hdf"
        )
        geom = hdf[f"Geometry/2D Flow Areas/{AREA}"]
        geom["Cells Center Manning's n"] = [0.035, 0.10]
        geom["Faces Area Elevation Values"] = [[0, 0, 0, 0.035], [1, 0, 0, 0.10]]
        if failure == "uniform":
            geom["Cells Center Manning's n"][:] = 0.04
            geom["Faces Area Elevation Values"][:, 3] = 0.04
        elif failure == "missing_association":
            del hdf["Geometry"].attrs["Land Cover Filename"]
        elif failure == "nonfinite":
            geom["Cells Center Manning's n"][0] = np.nan
        elif failure == "out_of_range":
            geom["Faces Area Elevation Values"][0, 3] = 0.20
    if failure:
        with pytest.raises((ValueError, RuntimeError)):
            _native_output(project, scenario)
    else:
        review = _native_output(project, scenario)["review"]["roughness_zones"][0]
        assert (
            review["passed"]
            and review["cell_distinct_count"] == review["face_distinct_count"] == 2
        )
