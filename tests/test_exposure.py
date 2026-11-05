"""Synthetic fixtures for exposure and tributary plumbing; never shipped as model output."""
import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from fastapi.testclient import TestClient

from server import cli, exposure, store, tributaries
from server.store import file_hash, write_json

# A 1 km square model grid in UTM 42N (100 m cells), like the published Nowshera rasters.
WEST, NORTH, CELL, SIZE = 770_000.0, 3_766_000.0, 100.0, 10
TO_WGS = Transformer.from_crs(32642, 4326, always_xy=True).transform


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for module in [store, cli, exposure, tributaries]:
        monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(exposure, "EXPOSURE", tmp_path / "exposure")
    monkeypatch.setattr(exposure, "LAYERS", tmp_path / "exposure" / "layers.json")
    monkeypatch.setattr(tributaries, "AUDITS", tmp_path / "tributaries")
    monkeypatch.setattr(tributaries, "WATERWAYS", tmp_path / "tributaries" / "none.geojson")
    monkeypatch.setattr(tributaries, "PDMA", tmp_path / "none.csv")
    return tmp_path


def depth_tif(path, values):
    with rasterio.open(path, "w", driver="GTiff", width=SIZE, height=SIZE, count=1, dtype="float32",
                       crs="EPSG:32642", transform=from_origin(WEST, NORTH, CELL, CELL), nodata=-9999) as dst:
        dst.write(np.asarray(values, dtype="float32"), 1)
    return path


def publish_fixture(root, depths, result_id="fixture-result"):
    folder = root / "results" / result_id
    folder.mkdir(parents=True)
    frames = []
    for index, values in enumerate(depths):
        path = depth_tif(folder / f"{index:05d}-depth.tif", values)
        frames.append({"time": f"2022-08-20T0{index}:00:00+00:00",
                       "fields": {"depth": {"url": f"/outputs/{result_id}/{path.stem}.png",
                                            "raster_url": f"/outputs/{result_id}/{path.name}",
                                            "sha256": file_hash(path), "bounds": [0, 0, 0, 0]}}})
    write_json(folder / "manifest.json", {"id": result_id, "scenario_sha256": "fixture-scenario",
                                          "engine": "LISFLOOD-FP", "frames": frames})
    return result_id


def population_layer(root):
    """One person per ~50 m geographic pixel over the model grid and a margin."""
    west, north = TO_WGS(WEST - 300, NORTH + 300)
    east, south = TO_WGS(WEST + SIZE * CELL + 300, NORTH - SIZE * CELL - 300)
    step = 0.0005
    width, height = int((east - west) / step) + 1, int((north - south) / step) + 1
    path = root / "exposure" / "population.tif"
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(west, north, step, step), nodata=np.nan) as dst:
        dst.write(np.ones((height, width), dtype="float32"), 1)
    inside = TO_WGS(WEST + 450, NORTH - 450)
    outside = TO_WGS(WEST - 5000, NORTH + 5000)
    features = [{"type": "Feature", "id": f"osm:node/{i}", "geometry": {"type": "Point", "coordinates": list(point)},
                 "properties": {"kind": "health", "amenity": "hospital", "name": name}}
                for i, (point, name) in enumerate([(inside, "Inside"), (outside, "Outside")])]
    facilities = root / "exposure" / "facilities.geojson"
    write_json(facilities, {"type": "FeatureCollection", "features": features})
    write_json(root / "exposure" / "layers.json", {
        "population": {"path": "exposure/population.tif", "sha256": file_hash(path), "product": "Synthetic test fixture",
                       "license": "test only", "overlay": {"path": "exposure/none.png", "sha256": "", "bounds": [0, 0, 0, 0]}},
        "facilities": {"path": "exposure/facilities.geojson", "sha256": file_hash(facilities), "osm_timestamp": None},
    })


def test_exposure_counts_people_outside_the_starting_river(isolated):
    river = np.zeros((SIZE, SIZE))
    river[:, 0] = 0.8  # wet at the first frame: the channel, excluded from counts
    result_id = publish_fixture(isolated, [river, np.full((SIZE, SIZE), 0.5), np.full((SIZE, SIZE), 2.0)])
    population_layer(isolated)
    report = exposure.compute_exposure(result_id)
    first, shallow, deep = (frame["people"] for frame in report["frames"])
    assert first == [0, 0]
    assert report["population_excluded_start_wet"] > 0
    counted = report["population_in_extent"] - report["population_excluded_start_wet"]
    assert shallow == [counted, 0]
    assert deep == [counted, counted]
    assert report["peak"]["people"] == deep
    (item,) = report["facilities"]["items"]  # the outside facility is not in the model extent
    assert item["name"] == "Inside" and item["max_depth_m"] == 2.0
    assert item["first_flooded_time"] == report["frames"][1]["time"]
    assert report["facilities"]["ever_flooded"] == 1


def test_population_columns_add_up_to_the_frame_counts(isolated, monkeypatch):
    import server.app as app_module
    import server.map_context as map_context
    monkeypatch.setattr(app_module, "ROOT", isolated)
    monkeypatch.setattr(map_context, "terrain_metadata", lambda: {"available": False})
    river = np.zeros((SIZE, SIZE))
    river[:, 0] = 0.8
    partial = np.zeros((SIZE, SIZE))
    partial[:, 5:] = 1.5
    result_id = publish_fixture(isolated, [river, partial, np.full((SIZE, SIZE), 0.5)])
    population_layer(isolated)
    report = exposure.compute_exposure(result_id)
    response = TestClient(app_module.app).get(f"/api/results/{result_id}/exposure/columns")
    assert response.headers["content-encoding"] == "gzip"
    data = response.json()
    assert data["available"] and data["ground_source"] is None
    assert report["columns"]["count"] == len(data["columns"]) > 1

    def count(series, frame):
        if not series or not 0 <= frame - series["from"] < len(series["people"]):
            return 0
        return series["people"][frame - series["from"]]

    for frame, totals in enumerate(report["frames"]):
        for threshold in range(2):
            assert sum(count((column.get("flooded") or [None, None])[threshold], frame)
                       for column in data["columns"]) == totals["people"][threshold]
    counted = report["population_in_extent"] - report["population_excluded_start_wet"]
    assert sum(column["people"] for column in data["columns"]) == counted
    # Nothing is flooded at frame 0, so every stored series starts later.
    assert all(series["from"] >= 1 for column in data["columns"]
               for series in column.get("flooded", []) if series)
    assert all("ground_m" not in column for column in data["columns"])


def test_exposure_refuses_changed_depth_rasters(isolated):
    result_id = publish_fixture(isolated, [np.zeros((SIZE, SIZE)), np.ones((SIZE, SIZE))])
    population_layer(isolated)
    depth_tif(isolated / "results" / result_id / "00001-depth.tif", np.full((SIZE, SIZE), 3.0))
    with pytest.raises(ValueError, match="no longer matches"):
        exposure.compute_exposure(result_id)


def test_exposure_endpoint_reports_missing_layers(isolated, monkeypatch):
    import server.app as app_module
    monkeypatch.setattr(app_module, "ROOT", isolated)
    result_id = publish_fixture(isolated, [np.zeros((SIZE, SIZE))])
    response = TestClient(app_module.app).get(f"/api/results/{result_id}/exposure")
    assert response.status_code == 200
    assert response.json() == {"available": False, "reason": "Acquire the population layer first: python -m server.exposure acquire"}
    assert TestClient(app_module.app).get("/api/results/unknown-id/exposure").status_code == 404


def reach(hyriv_id, next_down, upland, points):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [list(TO_WGS(x, y)) for x, y in points]},
            "properties": {"HYRIV_ID": hyriv_id, "NEXT_DOWN": next_down, "UPLAND_SKM": upland,
                           "DIS_AV_CMS": upland / 100, "ORD_STRA": 3}}


def test_tributary_audit_flags_streams_that_enter_away_from_inflow_lines(isolated):
    result_id = publish_fixture(isolated, [np.zeros((SIZE, SIZE))])
    project = isolated / "project"
    project.mkdir()
    (project / "terrain.asc").write_text(
        f"ncols {SIZE}\nnrows {SIZE}\nxllcorner {WEST}\nyllcorner {NORTH - SIZE * CELL}\ncellsize {CELL}\nNODATA_value -9999\n")
    # The only inflow: 200 m of the western edge around the main river.
    (project / "boundaries.bci").write_text(f"W {NORTH - 600} {NORTH - 400} QVAR routed\nE {NORTH - 1000} {NORTH} FREE 0.0004\n")
    write_json(isolated / "bindings" / "fixture-scenario.json", {"engine": "LISFLOOD-FP", "project": str(project)})
    main_y, south = NORTH - 500, NORTH - SIZE * CELL
    rivers = {"type": "FeatureCollection", "features": [
        reach(1, 2, 9000, [(WEST - 2000, main_y), (WEST + 500, main_y)]),           # main river, fed
        reach(2, 0, 9800, [(WEST + 500, main_y), (WEST + 3000, main_y)]),           # leaves eastwards
        reach(3, 2, 800, [(WEST + 500, NORTH + 2000), (WEST + 500, main_y)]),       # major tributary from the north
        reach(4, 2, 20, [(WEST + 700, south - 1000), (WEST + 700, main_y)]),        # minor local stream from the south
    ]}
    write_json(isolated / "hydrography.geojson", rivers)
    cli.register("hydrography", isolated / "hydrography.geojson", "Synthetic test fixture", "test only", "rivers")
    report = tributaries.audit(result_id)
    by_id = {item["hyriv_id"]: item for item in report["entering"]}
    assert set(by_id) == {1, 3, 4}
    assert by_id[1]["represented"] and by_id[1]["boundary"] == "routed" and by_id[1]["edge"] == "west"
    assert not by_id[3]["represented"] and by_id[3]["edge"] == "north" and by_id[3]["significance"] == "major"
    assert not by_id[4]["represented"] and by_id[4]["significance"] == "minor"
    assert report["summary"]["unrepresented_major"] == ["HydroRIVERS 3"]
    assert report["summary"]["unrepresented_upland_km2"] == 820


def test_hecras_inflow_lines_come_from_flow_hydrograph_boundaries(tmp_path):
    (tmp_path / "Case.g01").write_text(
        "BC Line Name=HMS Inflow\nBC Line Storage Area=A\nBC Line Arc= 2 \n"
        "          767900         3770600          767900         3770200\n"
        "BC Line Name=Downstream\nBC Line Storage Area=A\nBC Line Arc= 2 \n"
        "          782300         3760100          782300         3774500\n")
    (tmp_path / "Case.u01").write_text(
        "Boundary Location=  ,  ,  ,  ,  ,A  ,  ,Downstream  \nFriction Slope=0.0004\n"
        "Boundary Location=  ,  ,  ,  ,  ,A  ,  ,HMS Inflow  \nInterval=1HOUR\nFlow Hydrograph= 3 \n")
    (line,) = tributaries.inflow_boundaries("HEC-RAS 2D", tmp_path)
    assert line["name"] == "HMS Inflow"
    assert list(line["line"].coords) == [(767900, 3770600), (767900, 3770200)]
