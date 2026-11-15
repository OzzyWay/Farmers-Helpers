from io import BytesIO
from types import SimpleNamespace

import numpy as np
import rasterio
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from rasterio.transform import from_bounds

from app.main import app, get_raster_overlay_service
from app.raster_overlays import RasterOverlayService, _catalog_match


def test_catalog_and_tile_reproject_geotiff_and_preserve_nodata(tmp_path, monkeypatch):
    raster_path = tmp_path / "rainfall.tiff"
    values = np.arange(32 * 32, dtype=np.float32).reshape((32, 32))
    values[:8, :] = -9999
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=32,
        height=32,
        count=1,
        dtype="float32",
        crs="EPSG:32631",
        transform=from_bounds(166000, -1000, 168000, 1000, 32, 32),
        nodata=-9999,
    ) as dataset:
        dataset.write(values, 1)
        dataset.set_band_description(1, "Precipitation")
        dataset.update_tags(1, units="mm")

    monkeypatch.setenv("RASTER_DATA_DIRS", str(tmp_path))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    service = RasterOverlayService()
    app.dependency_overrides[get_raster_overlay_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.get("/api/rasters")
            assert response.status_code == 200
            rasters = response.json()["rasters"]
            assert len(rasters) == 1
            raster = rasters[0]
            assert raster["variables"][0]["name"] == "Precipitation"
            assert raster["variables"][0]["units"] == "mm"
            assert raster["variables"][0]["min"] == 256
            assert raster["variables"][0]["max"] == 1023
            assert raster["bounds"][0] < raster["bounds"][2]
            assert raster["maxzoom"] == 11

            tile_response = client.get(
                f"/api/rasters/{raster['id']}/tiles/8/128/128.png",
                params={"band": 1, "ramp": "viridis"},
            )
            assert tile_response.status_code == 200
            image = np.asarray(Image.open(BytesIO(tile_response.content)))
            assert image.shape == (256, 256, 4)
            assert np.any(image[:, :, 3] == 0)
            assert np.any(image[:, :, 3] == 255)
    finally:
        app.dependency_overrides.clear()


def test_catalog_uses_only_dates_present_in_raster_filenames(tmp_path, monkeypatch):
    smap_dir = tmp_path / "SMAP"
    smap_dir.mkdir()
    for month in ("2024-01", "2024-03"):
        with rasterio.open(
            smap_dir / f"soil_{month}.tif",
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_bounds(-1, -1, 1, 1, 2, 2),
        ) as dataset:
            dataset.write(np.ones((2, 2), dtype=np.float32), 1)

    monkeypatch.setenv("RASTER_DATA_DIRS", str(tmp_path))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    records = RasterOverlayService().catalog()[0]["records"]
    assert [record["datetime"] for record in records] == ["2024-01", "2024-03"]


def test_catalog_groups_year_suffixed_gaez_rasters_in_year_order(tmp_path, monkeypatch):
    gaez_dir = tmp_path / "GAEZ"
    gaez_dir.mkdir()
    for year in ("1961", "1960"):
        with rasterio.open(
            gaez_dir / f"Sb_{year}.tif",
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_bounds(-1, -1, 1, 1, 2, 2),
        ) as dataset:
            dataset.write(np.ones((2, 2), dtype=np.float32), 1)

    monkeypatch.setenv("RASTER_DATA_DIRS", str(tmp_path))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    catalog = RasterOverlayService().catalog()

    assert len(catalog) == 1
    assert [record["datetime"] for record in catalog[0]["records"]] == [
        "1960-01-01",
        "1961-01-01",
    ]


def test_hugging_face_discovery_is_metadata_only_and_uses_catalog(tmp_path, monkeypatch):
    downloaded = []
    siblings = [
        SimpleNamespace(rfilename=f"ECOSTRESS/ECOSTRESS_SDS_LST_{month}-01.tif", blob_id=month, size=100)
        for month in ("2024-01", "2024-02")
    ]

    class FakeHfApi:
        def __init__(self, token):
            assert token == "test-token"

        def dataset_info(self, repo_id, files_metadata):
            assert repo_id == "OzzyWay/Farmers-Helper"
            assert files_metadata is True
            return SimpleNamespace(sha="revision", siblings=siblings)

    def fake_download(**kwargs):
        downloaded.append(kwargs["filename"])
        return str(tmp_path / "raster.tif")

    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setenv("HF_DATASET_REPO", "other-owner/other-dataset")
    monkeypatch.setenv("RASTER_DATA_DIRS", str(tmp_path))
    monkeypatch.setattr("huggingface_hub.HfApi", FakeHfApi)
    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)

    service = RasterOverlayService()
    catalog = service.catalog()
    assert len(catalog) == 1
    assert [record["datetime"] for record in catalog[0]["records"]] == ["2024-01-01", "2024-02-01"]
    assert catalog[0]["source_family"] == "ECOSTRESS"
    assert catalog[0]["title"] == "Land Surface Temperature"
    assert downloaded == []


def test_hugging_face_asset_ids_survive_repository_revision_changes(monkeypatch):
    revisions = iter(("revision-one", "revision-two"))
    sibling = SimpleNamespace(
        rfilename="ECOSTRESS/ECOSTRESS_SDS_LST_2024-01-01.tif",
        blob_id="blob",
        size=100,
    )

    class FakeHfApi:
        def __init__(self, token):
            pass

        def dataset_info(self, repo_id, files_metadata):
            assert repo_id == "OzzyWay/Farmers-Helper"
            revision = next(revisions)
            return SimpleNamespace(sha=revision, siblings=[sibling])

    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setattr("huggingface_hub.HfApi", FakeHfApi)
    service = RasterOverlayService()

    first_id = service.catalog()[0]["records"][0]["id"]
    refreshed_id = service.catalog(refresh=True)[0]["records"][0]["id"]

    assert refreshed_id == first_id


def test_hugging_face_download_occurs_only_when_asset_is_selected(tmp_path, monkeypatch):
    raster_path = tmp_path / "selected.tif"
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_bounds(-1, -1, 1, 1, 2, 2),
    ) as dataset:
        dataset.write(np.ones((2, 2), dtype=np.float32), 1)

    class FakeHfApi:
        def __init__(self, token):
            pass

        def dataset_info(self, repo_id, files_metadata):
            sibling = SimpleNamespace(
                rfilename="ECOSTRESS/ECOSTRESS_SDS_LST_2024-01-01.tif",
                blob_id="blob",
                size=raster_path.stat().st_size,
            )
            return SimpleNamespace(sha="revision", siblings=[sibling])

    downloads = []

    def fake_download(**kwargs):
        downloads.append(kwargs)
        return str(raster_path)

    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setenv("RASTER_DATA_DIRS", str(tmp_path))
    monkeypatch.setattr("huggingface_hub.HfApi", FakeHfApi)
    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    service = RasterOverlayService()

    record = service.catalog()[0]["records"][0]
    assert downloads == []
    asset = service.asset(record["id"])
    assert asset["id"] == record["id"]
    assert len(downloads) == 1
    assert downloads[0]["filename"] == "ECOSTRESS/ECOSTRESS_SDS_LST_2024-01-01.tif"
    assert downloads[0]["token"] == "test-token"
    assert asset["variables"][0]["name"] == "Land Surface Temperature"
    assert asset["variables"][0]["units"] == "K"
    assert "Land Surface Temperature" in asset["description"]
    assert "Units: K" in asset["description"]


def test_smap_raster_without_geotiff_crs_uses_embedded_ease_grid_metadata(tmp_path, monkeypatch):
    raster_path = tmp_path / "smap.tif"
    width, height = 3856, 1624
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        compress="DEFLATE",
    ) as dataset:
        dataset.write(np.full((height, width), 2.5, dtype=np.float32), 1)
        dataset.update_tags(
            Metadata_DatasetIdentification_shortName="SPL4SMGP",
            Metadata_GridSpatialRepresentation_Longitude_dimensionSize=str(width),
            Metadata_GridSpatialRepresentation_Latitude_dimensionSize=str(height),
            Metadata_Extent_westBoundLongitude="-180",
            Metadata_Extent_eastBoundLongitude="180",
            Metadata_Extent_southBoundLatitude="-85.044563",
            Metadata_Extent_northBoundLatitude="85.044563",
        )

    repo_path = "SMAP/2016-11/2016-10-31__Geophysical_Data_net_downward_longwave_flux.tif"

    class FakeHfApi:
        def __init__(self, token):
            pass

        def dataset_info(self, repo_id, files_metadata):
            sibling = SimpleNamespace(rfilename=repo_path, blob_id="smap-blob", size=raster_path.stat().st_size)
            return SimpleNamespace(sha="revision", siblings=[sibling])

    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setenv("RASTER_DATA_DIRS", str(tmp_path / "empty"))
    monkeypatch.setattr("huggingface_hub.HfApi", FakeHfApi)
    monkeypatch.setattr("huggingface_hub.hf_hub_download", lambda **kwargs: str(raster_path))

    service = RasterOverlayService()
    app.dependency_overrides[get_raster_overlay_service] = lambda: service
    try:
        with TestClient(app) as client:
            catalog = client.get("/api/rasters").json()["rasters"]
            asset_id = catalog[0]["records"][0]["id"]

            details = client.get(f"/api/rasters/{asset_id}")
            assert details.status_code == 200
            assert details.json()["bounds"] == pytest.approx([-180, -85.044563, 180, 85.044563], abs=1e-5)

            tile = client.get(f"/api/rasters/{asset_id}/tiles/3/1/3.png")
            assert tile.status_code == 200
            image = np.asarray(Image.open(BytesIO(tile.content)))
            assert np.any(image[:, :, 3] == 255)

            summary = client.post(
                f"/api/rasters/{asset_id}/summary",
                json={
                    "type": "Polygon",
                    "coordinates": [[[-99, 29], [-96, 29], [-96, 32], [-99, 32], [-99, 29]]],
                },
            )
            assert summary.status_code == 200
            variable_summary = summary.json()["variables"][0]["summary"]
            assert variable_summary["valid_pixel_count"] > 0
            assert variable_summary["mean"] == pytest.approx(2.5)
    finally:
        app.dependency_overrides.clear()


def test_regional_summary_excludes_nodata_and_pixels_outside_polygon(tmp_path, monkeypatch):
    raster_path = tmp_path / "summary.tif"
    values = np.arange(1, 17, dtype=np.float32).reshape((4, 4))
    values[1, 1] = -9999
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_bounds(-2, -2, 2, 2, 4, 4),
        nodata=-9999,
    ) as dataset:
        dataset.write(values, 1)

    monkeypatch.setenv("RASTER_DATA_DIRS", str(tmp_path))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    service = RasterOverlayService()
    asset_id = service.catalog()[0]["id"]
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-3, -1], [1, -1], [1, 1], [-3, 1], [-3, -1]]],
    }

    summary = service.summary(asset_id, geometry)["variables"][0]["summary"]
    assert summary["region_pixel_count"] == 8
    assert summary["valid_pixel_count"] == 5
    assert summary["valid_region_percent"] == 62.5
    assert summary["min"] == 5
    assert summary["max"] == 11
    assert summary["mean"] == pytest.approx(8.4)


def test_catalog_reports_missing_hugging_face_token(tmp_path, monkeypatch):
    monkeypatch.setenv("RASTER_DATA_DIRS", str(tmp_path))
    monkeypatch.delenv("HF_TOKEN", raising=False)

    service = RasterOverlayService()
    assert service.catalog() == []
    assert service.warnings == [
        "Hugging Face map layers are unavailable because the required access token is not set."
    ]


def test_catalog_search_identifier_matches_authoritative_layer_header():
    entry = _catalog_match("ECOSTRESS SDS_Emis3_err", "ECOSTRESS")
    assert entry is not None
    assert entry["layer_header"] == "SDS_Emis3_err"
    assert entry["title"] == "Band 3 Emissivity error"


def test_hugging_face_authentication_failure_is_reported_without_exposing_token(tmp_path, monkeypatch):
    class Unauthorized(Exception):
        response = SimpleNamespace(status_code=401)

    class FakeHfApi:
        def __init__(self, token):
            pass

        def dataset_info(self, repo_id, files_metadata):
            raise Unauthorized()

    monkeypatch.setenv("HF_TOKEN", "test-token")
    monkeypatch.setenv("RASTER_DATA_DIRS", str(tmp_path))
    monkeypatch.setattr("huggingface_hub.HfApi", FakeHfApi)

    service = RasterOverlayService()
    assert service.catalog() == []
    assert "access was denied" in service.warnings[0].lower()
    assert "test-token" not in service.warnings[0]
