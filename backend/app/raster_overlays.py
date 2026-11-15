"""Discover GeoTIFF overlays and render on-demand Web Mercator tiles."""

from __future__ import annotations

import hashlib
import csv
import json
import logging
import math
import os
import re
import threading
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.features import bounds as geometry_bounds, geometry_mask
from rasterio.transform import array_bounds, from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform, transform_bounds, transform_geom
from rasterio.errors import WindowError
from rasterio.windows import Window, from_bounds as window_from_bounds, transform as window_transform

ROOT = Path(__file__).resolve().parents[2]
WEB_MERCATOR_LIMIT = 20037508.342789244
RAMPS = {
    "viridis": ((68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)),
    "magma": ((0, 0, 4), (81, 18, 124), (183, 55, 121), (252, 137, 97), (252, 253, 191)),
    "blue-red": ((49, 54, 149), (116, 173, 209), (247, 247, 247), (244, 109, 67), (165, 0, 38)),
}
_DATE_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}[-_]?(?:0[1-9]|1[0-2])(?:[-_]?(?:0[1-9]|[12]\d|3[01]))?(?!\d)")
_DOY_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})((?:0\d\d|[12]\d\d|3[0-6]\d))(?!\d)")
_YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
logger = logging.getLogger(__name__)
HF_REPO_ID = "OzzyWay/Farmers-Helper"
HF_REPO_TYPE = "dataset"
RASTER_SUFFIXES = {".tif", ".tiff"}
CATALOG_PATH = ROOT / "raster_layer_catalog.csv"
SMAP_L4_PRODUCT_ID = "SPL4SMGP"
SMAP_L4_CRS = "EPSG:6933"


def _file_id(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def _parse_date(text: str) -> str | None:
    directory_date = re.search(
        r"(?<!\d)((?:19|20)\d{2})[\\/](0?[1-9]|1[0-2])(?:[\\/](0?[1-9]|[12]\d|3[01]))?(?!\d)",
        text,
    )
    if directory_date:
        year, month, day = directory_date.groups()
        try:
            if day is None:
                return f"{int(year):04d}-{int(month):02d}"
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            pass
    match = _DATE_PATTERN.search(text)
    if match:
        value = re.sub(r"[-_]", "", match.group())
        try:
            if len(value) == 6:
                return f"{value[:4]}-{value[4:6]}"
            return date(int(value[:4]), int(value[4:6]), int(value[6:8])).isoformat()
        except ValueError:
            pass
    match = _DOY_PATTERN.search(text)
    if match:
        try:
            return date(int(match.group(1)), 1, 1).fromordinal(
                date(int(match.group(1)), 1, 1).toordinal() + int(match.group(2)) - 1
            ).isoformat()
        except ValueError:
            return None
    match = _YEAR_PATTERN.search(Path(text).stem)
    if match:
        return f"{match.group(1)}-01-01"
    return None


def _units(tags: dict[str, str]) -> str | None:
    for key, value in tags.items():
        if key.lower() in {"units", "unit", "unittype", "unit_type"} and value.strip():
            return value.strip()
    return None


@lru_cache(maxsize=1)
def _catalog_rows() -> tuple[dict[str, str], ...]:
    if not CATALOG_PATH.is_file():
        return ()
    with CATALOG_PATH.open(encoding="utf-8-sig", newline="") as stream:
        return tuple(csv.DictReader(stream))


@lru_cache(maxsize=8)
def _catalog_header_index(family: str) -> dict[str, dict[str, str]]:
    return {
        re.sub(r"[^a-z0-9]", "", row["layer_header"].casefold()): row
        for row in _catalog_rows()
        if row["source_family"].casefold() == family.casefold() and row.get("layer_header")
    }


def _describe_data(title: str | None, description: str | None, units: str | None) -> str | None:
    fragments = []
    content = (description or title or "").strip()
    if content:
        fragments.append(content.rstrip("."))
    unit_text = (units or "").strip()
    if unit_text and unit_text.casefold() not in {"n/a", "na", "none"}:
        fragments.append(f"Units: {unit_text}")
    if not fragments:
        return None
    description_text = ". ".join(fragments)
    if description_text and not description_text.endswith("."):
        description_text += "."
    return description_text


def _catalog_match(text: str, family: str | None = None) -> dict | None:
    if not family:
        return None
    headers = _catalog_header_index(family)
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    matches = []
    for start in range(len(tokens)):
        normalized = ""
        for token in tokens[start:start + 16]:
            normalized += token
            row = headers.get(normalized)
            if row:
                matches.append((len(normalized), row))
    if not matches:
        return None
    row = max(matches, key=lambda match: match[0])[1]
    return {
        "source_family": row["source_family"],
        "layer_header": row["layer_header"],
        "title": row["descriptive_title"],
        "description": row["description"],
        "units": row["units"],
        "minimum_valid_value": row["minimum_valid_value"],
        "maximum_valid_value": row["maximum_valid_value"],
        "range_basis": row["range_basis"],
        "title_source": row["title_source"],
        "description_source": row["description_source"],
    }


def _source_family(text: str) -> str | None:
    families = {row["source_family"] for row in _catalog_rows()}
    folded = text.casefold()
    return next((family for family in families if family.casefold() in folded), None)


def _catalog_metadata(identity: str, dataset_name: str, name: str) -> dict:
    text = f"{identity} {dataset_name} {name}"
    family = _source_family(text)
    entry = _catalog_match(text, family)
    description = _describe_data(
        (entry or {}).get("title"),
        (entry or {}).get("description"),
        (entry or {}).get("units"),
    ) if entry else None
    return {
        "source_family": family or (entry or {}).get("source_family"),
        "catalog_entry": entry,
        "catalog_matched": entry is not None,
        "title": entry["title"] if entry else name,
        "description": description,
    }


def _stats(path: str, band: int, modified: str) -> dict:
    with rasterio.open(path) as dataset:
        tags = dataset.tags(band)
        tags.update(dataset.tags())
        band_name = dataset.descriptions[band - 1] or tags.get("long_name") or tags.get("DESCRIPTION")
        # A bounded sample keeps catalog requests practical for very large local rasters and COGs.
        height = min(512, dataset.height)
        width = min(512, dataset.width)
        sample = dataset.read(
            band,
            out_shape=(height, width),
            masked=True,
            resampling=Resampling.nearest,
        )
        values = np.asarray(sample.compressed(), dtype=np.float64)
        values = values[np.isfinite(values)]
        if values.size:
            minimum = float(values.min())
            maximum = float(values.max())
            low, high = (float(v) for v in np.percentile(values, [2, 98]))
            if low == high:
                low, high = minimum, maximum
        else:
            minimum = maximum = low = high = None

        categories = None
        try:
            color_map = dataset.colormap(band)
            categories = [
                {
                    "value": int(value),
                    "label": str(value),
                    "color": f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}",
                    "alpha": int(rgba[3]),
                }
                for value, rgba in sorted(color_map.items())
            ]
        except (ValueError, KeyError):
            pass
        if categories is None and np.issubdtype(dataset.dtypes[band - 1], np.integer) and values.size:
            unique = np.unique(values)
            if 1 < unique.size <= 20:
                colors = RAMPS["viridis"]
                categories = []
                for index, value in enumerate(unique):
                    position = round(index * (len(colors) - 1) / max(1, unique.size - 1))
                    color = colors[position]
                    categories.append({
                        "value": int(value),
                        "label": tags.get(f"class_{int(value)}", str(int(value))),
                        "color": f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}",
                    })
        return {
            "index": band,
            "name": band_name or (f"Band {band}" if dataset.count > 1 else None),
            "units": _units(tags),
            "min": minimum,
            "max": maximum,
            "display_min": low,
            "display_max": high,
            "categories": categories,
            "categorical": bool(categories),
        }


@lru_cache(maxsize=512)
def _cached_stats(path: str, band: int, modified: str) -> dict:
    return _stats(path, band, modified)


def _spatial_reference(dataset, name: str):
    if dataset.crs is not None:
        return dataset.crs, dataset.transform

    # SPL4SMGP GeoTIFF exports can retain grid metadata while losing GeoTIFF CRS tags.
    tags = dataset.tags()
    product_id = (
        tags.get("Metadata_DatasetIdentification_shortName")
        or tags.get("Metadata_SeriesIdentification_shortName")
    )
    if product_id != SMAP_L4_PRODUCT_ID:
        raise ValueError(f"{name} has no CRS")

    try:
        width = int(tags["Metadata_GridSpatialRepresentation_Longitude_dimensionSize"])
        height = int(tags["Metadata_GridSpatialRepresentation_Latitude_dimensionSize"])
        west = float(tags["Metadata_Extent_westBoundLongitude"])
        east = float(tags["Metadata_Extent_eastBoundLongitude"])
        south = float(tags["Metadata_Extent_southBoundLatitude"])
        north = float(tags["Metadata_Extent_northBoundLatitude"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{name} has no CRS") from error

    if (
        (width, height) != (dataset.width, dataset.height)
        or not all(math.isfinite(value) for value in (west, east, south, north))
        or not (math.isclose(west, -180) and math.isclose(east, 180))
        or not (math.isclose(south, -north) and -90 < south < 0 < north < 90)
    ):
        raise ValueError(f"{name} has no CRS")

    x_bounds, _ = transform("EPSG:4326", SMAP_L4_CRS, [west, east], [0, 0])
    _, y_bounds = transform("EPSG:4326", SMAP_L4_CRS, [0, 0], [south, north])
    return rasterio.crs.CRS.from_string(SMAP_L4_CRS), from_bounds(
        min(x_bounds), min(y_bounds), max(x_bounds), max(y_bounds), width, height
    )


def _native_maxzoom(dataset, source_crs, source_transform) -> int:
    center = source_transform @ (dataset.width / 2, dataset.height / 2)
    column_neighbor = source_transform @ (dataset.width / 2 + 1, dataset.height / 2)
    row_neighbor = source_transform @ (dataset.width / 2, dataset.height / 2 + 1)
    xs, ys = transform(
        source_crs,
        "EPSG:3857",
        [center[0], column_neighbor[0], row_neighbor[0]],
        [center[1], column_neighbor[1], row_neighbor[1]],
    )
    pixel_sizes = (
        math.hypot(xs[1] - xs[0], ys[1] - ys[0]),
        math.hypot(xs[2] - xs[0], ys[2] - ys[0]),
    )
    pixel_size = max(pixel_sizes)
    if not math.isfinite(pixel_size) or pixel_size <= 0:
        raise ValueError("Could not determine raster resolution in Web Mercator")
    world_pixel_size = 2 * WEB_MERCATOR_LIMIT / 256
    return max(0, min(22, math.floor(math.log2(world_pixel_size / pixel_size))))


def _asset_metadata(
    path: str,
    identity: str,
    dataset_name: str,
    name: str,
    modified: str,
    overrides: dict | None = None,
    date_source: str | None = None,
    series_key_source: str | None = None,
) -> dict:
    overrides = overrides or {}
    with rasterio.open(path) as source:
        source_crs, source_transform = _spatial_reference(source, name)
        bounds = transform_bounds(
            source_crs,
            "EPSG:4326",
            *array_bounds(source.height, source.width, source_transform),
            densify_pts=21,
        )
        maxzoom = _native_maxzoom(source, source_crs, source_transform)
        bands = source.count
        raster_tags = source.tags()
    variables = [_cached_stats(path, band, modified) for band in range(1, bands + 1)]
    for item in variables:
        if item["name"] is None:
            item["name"] = name
        if overrides.get("variable"):
            item["name"] = str(overrides["variable"])
        if overrides.get("units"):
            item["units"] = str(overrides["units"])
        for field in ("min", "max", "display_min", "display_max"):
            if overrides.get(field) is not None:
                item[field] = float(overrides[field])
    metadata_date = next(
        (value for key, value in raster_tags.items() if key.casefold() in {"datetime", "date", "time"} and value),
        None,
    )
    when = str(
        overrides.get("datetime")
        or _parse_date(name)
        or _parse_date(date_source or identity)
        or _parse_date(metadata_date or "")
        or ""
    ) or None
    catalog = _catalog_metadata(identity, dataset_name, name)
    for item in variables:
        entry = _catalog_match(
            f"{identity} {dataset_name} {name} {item['name'] or ''}",
            catalog["source_family"],
        )
        item["catalog_entry"] = entry
        if entry:
            item["name"] = entry["title"]
            if entry["units"] and entry["units"].casefold() != "n/a":
                item["units"] = entry["units"]
    return {
        "id": _file_id(identity + modified),
        "dataset": dataset_name,
        "name": name,
        "datetime": when,
        "bounds": [bounds[0], bounds[1], bounds[2], bounds[3]],
        "maxzoom": maxzoom,
        "variables": variables,
        "path": path,
        "identity": identity,
        "modified": modified,
        "series_key": _series_key(series_key_source or identity, dataset_name),
        **catalog,
    }


def _series_key(identity: str, dataset_name: str) -> str:
    if identity.startswith("hf:"):
        source_path = identity.split("@", 1)[1].split("/", 1)[1]
    elif identity.startswith("local:"):
        source_path = identity.removeprefix("local:")
    else:
        source_path = identity
    parts = list(Path(source_path).parts)
    if parts and parts[-1].lower().endswith((".tif", ".tiff")):
        parts[-1] = Path(parts[-1]).stem
    cleaned = []
    for index, part in enumerate(parts):
        if re.fullmatch(r"(?:19|20)\d{2}", part) and index + 1 < len(parts) and re.fullmatch(r"(?:0?[1-9]|1[0-2])", parts[index + 1]):
            continue
        if index > 0 and re.fullmatch(r"(?:19|20)\d{2}", parts[index - 1]):
            continue
        part = _DATE_PATTERN.sub("", part)
        part = _DOY_PATTERN.sub("", part)
        if index == len(parts) - 1:
            part = _YEAR_PATTERN.sub("", part)
        if part:
            cleaned.append(part)
    stem = re.sub(r"[^a-zA-Z0-9]+", "-", "-".join(cleaned)).strip("-").lower()
    return f"{dataset_name.casefold()}:{stem or dataset_name.casefold()}"


def _local_sources() -> list[tuple[str, str, str, str, str, dict]]:
    configured = os.getenv("RASTER_DATA_DIRS")
    roots = [Path(p).expanduser() for p in configured.split(os.pathsep) if p] if configured else [ROOT / "examples"]
    sources = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".tif", ".tiff"}:
                try:
                    rel = path.relative_to(root)
                    dataset_name = rel.parts[0] if len(rel.parts) > 1 else root.name
                except ValueError:
                    dataset_name = root.name
                identity = f"local:{path.resolve()}"
                stat = path.stat()
                modified = f"{stat.st_mtime_ns}:{stat.st_size}"
                sources.append((str(path.resolve()), identity, dataset_name, path.stem, modified, {}))

    catalog_file = os.getenv("RASTER_CATALOG_FILE")
    if catalog_file:
        catalog = json.loads(Path(catalog_file).expanduser().read_text(encoding="utf-8"))
        for item in catalog.get("rasters", []):
            url = item.get("url")
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                raise ValueError("Remote raster catalog entries require an HTTP(S) url")
            identity = "remote:" + url
            sources.append((
                url,
                identity,
                str(item.get("dataset") or "Raster"),
                str(item.get("name") or Path(url.split("?", 1)[0]).stem),
                str(item.get("modified") or "remote"),
                item,
            ))
    return sources


class RasterOverlayService:
    """Discover raster metadata cheaply and download Hugging Face files only on selection."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._assets: dict[str, dict] = {}
        self._asset_locks: dict[str, threading.Lock] = {}
        self._download_locks: dict[str, threading.Lock] = {}
        self._scanned_at = 0.0
        self.warnings: list[str] = []

    def _hub_sources(self) -> list[dict]:
        token = os.getenv("HF_TOKEN")
        if not token:
            self.warnings.append("Hugging Face map layers are unavailable because the required access token is not set.")
            return []

        repo_id = HF_REPO_ID
        try:
            from huggingface_hub import HfApi

            info = HfApi(token=token).dataset_info(
                repo_id=repo_id,
                files_metadata=True,
            )
        except Exception as error:  # Hub client errors vary across supported versions.
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", None)
            if status in (401, 403):
                message = "Hugging Face access was denied; check that the access token can read the dataset."
            elif status == 404:
                message = f"Hugging Face dataset {repo_id} was not found or is not accessible."
            else:
                message = "Hugging Face dataset discovery failed; check connectivity and repository access."
            logger.warning("Hugging Face raster discovery failed (%s)", type(error).__name__)
            self.warnings.append(message)
            return []

        sources = []
        revision = info.sha
        for sibling in info.siblings:
            repo_path = sibling.rfilename
            if Path(repo_path).suffix.casefold() not in RASTER_SUFFIXES:
                continue
            identity = f"hf:{repo_id}/{repo_path}"
            parent = Path(repo_path).parent
            family = _source_family(repo_path)
            dataset_name = family or (parent.parts[0] if parent.parts and str(parent) != "." else repo_id)
            sources.append({
                "path": None,
                "identity": identity,
                "dataset": dataset_name,
                "name": Path(repo_path).stem,
                "modified": f"{revision}:{getattr(sibling, 'blob_id', '') or getattr(sibling, 'size', '')}",
                "overrides": {},
                "kind": "huggingface",
                "repo_id": repo_id,
                "repo_path": repo_path,
                "revision": revision,
            })
        return sources

    def _download(self, asset: dict) -> str:
        if asset.get("path"):
            return asset["path"]
        asset_id = asset["id"]
        with self._lock:
            lock = self._download_locks.setdefault(asset_id, threading.Lock())
        with lock:
            if asset.get("path"):
                return asset["path"]
            token = os.getenv("HF_TOKEN")
            if not token:
                raise PermissionError("The Hugging Face access token is not set.")
            try:
                from huggingface_hub import hf_hub_download

                path = hf_hub_download(
                    repo_id=asset["repo_id"],
                    filename=asset["repo_path"],
                    repo_type=HF_REPO_TYPE,
                    revision=asset["revision"],
                    token=token,
                    cache_dir=str(ROOT / "backend" / "cache" / "huggingface"),
                )
            except Exception as error:  # Hub client errors vary across supported versions.
                response = getattr(error, "response", None)
                status = getattr(response, "status_code", None)
                if status in (401, 403):
                    raise PermissionError("Hugging Face access was denied; check that the access token can read the dataset.") from error
                if status == 404:
                    raise FileNotFoundError("The selected map layer is no longer available in the dataset.") from error
                logger.warning("Hugging Face raster download failed (%s)", type(error).__name__)
                raise ConnectionError("The selected map layer could not be downloaded from Hugging Face.") from error
            asset["path"] = path
            return path

    def catalog(self, refresh: bool = False) -> list[dict]:
        import time

        with self._lock:
            if refresh or time.monotonic() - self._scanned_at > 300:
                assets = {}
                self.warnings = []
                sources = [
                    {
                        "path": path,
                        "identity": identity,
                        "dataset": dataset_name,
                        "name": name,
                        "modified": modified,
                        "overrides": overrides,
                        "kind": "local" if identity.startswith("local:") else "remote",
                    }
                    for path, identity, dataset_name, name, modified, overrides in _local_sources()
                ]
                sources.extend(self._hub_sources())
                for source in sources:
                    identity = source["identity"]
                    if source["kind"] == "huggingface":
                        asset = {
                            "id": _file_id(identity),
                            "dataset": source["dataset"],
                            "name": source["name"],
                            "datetime": _parse_date(source["name"]) or _parse_date(source["repo_path"]),
                            "bounds": None,
                            "variables": [],
                            "series_key": _series_key(source["repo_path"], source["dataset"]),
                            **_catalog_metadata(identity, source["dataset"], source["name"]),
                            "source_type": "Hugging Face map data; the catalog does not say where the measurements came from.",
                        }
                    else:
                        try:
                            asset = _asset_metadata(
                                source["path"], identity, source["dataset"], source["name"],
                                source["modified"], source["overrides"],
                            )
                            asset["source_type"] = "Map data from this device" if source["kind"] == "local" else "Map data from an online source"
                        except (OSError, rasterio.errors.RasterioError, ValueError) as error:
                            logger.warning("Skipping unreadable raster %s: %s", identity, error)
                            continue
                    assets[asset["id"]] = {**source, **asset}
                self._assets = assets
                self._scanned_at = time.monotonic()

            groups: dict[str, list[dict]] = {}
            for asset in self._assets.values():
                groups.setdefault(asset["series_key"], []).append(asset)
            result = []
            for records in groups.values():
                records = sorted(records, key=lambda item: item["datetime"] or item["name"])
                asset = records[0]
                result.append({
                    key: value
                    for key, value in asset.items()
                    if key not in {
                        "path", "identity", "modified", "series_key", "overrides",
                        "repo_id", "repo_path", "revision", "kind",
                    }
                } | {
                    "records": [
                        {"id": record["id"], "name": record["name"], "datetime": record["datetime"]}
                        for record in records
                    ]
                })
            return sorted(result, key=lambda item: (item["dataset"].casefold(), item["name"].casefold()))

    def asset(self, asset_id: str) -> dict:
        self.catalog()
        with self._lock:
            try:
                asset = self._assets[asset_id]
            except KeyError as exc:
                raise KeyError("Map layer not found; refresh the map layer list") from exc
            asset_lock = self._asset_locks.setdefault(asset_id, threading.Lock())
        with asset_lock:
            path = self._download(asset)
            if not asset["variables"]:
                metadata = _asset_metadata(
                    path, asset["identity"], asset["dataset"], asset["name"],
                    asset["modified"], asset.get("overrides"),
                    date_source=asset.get("repo_path"),
                    series_key_source=asset.get("repo_path") if asset["kind"] == "huggingface" else None,
                )
                asset.update(metadata)
                asset["id"] = asset_id
                asset["source_type"] = (
                    "Hugging Face map data; the catalog does not say where the measurements came from."
                    if asset["kind"] == "huggingface"
                    else asset["source_type"]
                )
            return asset

    def tile(self, asset_id: str, z: int, x: int, y: int, band: int, ramp: str) -> bytes:
        if z < 0 or z > 22 or x < 0 or y < 0 or x >= 2**z or y >= 2**z:
            raise ValueError("Invalid tile coordinate")
        if ramp not in RAMPS:
            raise ValueError(f"Unknown color ramp: {ramp}")
        asset = self.asset(asset_id)
        if band < 1 or band > len(asset["variables"]):
            raise ValueError("Invalid map measurement")
        variable = json.dumps(asset["variables"][band - 1], sort_keys=True)
        return _render_tile(asset_id, asset["path"], variable, z, x, y, band, ramp)

    def summary(self, asset_id: str, geometry: dict) -> dict:
        asset = self.asset(asset_id)
        _validate_geometry(geometry)
        stats = [
            _cached_summary(
                asset["path"],
                band["index"],
                asset["modified"],
                json.dumps(geometry, sort_keys=True, separators=(",", ":")),
            )
            for band in asset["variables"]
        ]
        return {
            "asset_id": asset_id,
            "dataset": asset["dataset"],
            "name": asset["name"],
            "datetime": asset["datetime"],
            "source_type": asset["source_type"],
            "bounds": asset["bounds"],
            "variables": [
                {
                    **variable,
                    "summary": values,
                    "description": _describe_data(
                        (variable.get("catalog_entry") or {}).get("title"),
                        (variable.get("catalog_entry") or {}).get("description"),
                        (variable.get("catalog_entry") or {}).get("units"),
                    ),
                    "catalog_matched": variable.get("catalog_entry") is not None,
                }
                for variable, values in zip(asset["variables"], stats)
            ],
        }


def _validate_geometry(geometry: dict) -> None:
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Region must be a GeoJSON Polygon or MultiPolygon.")
    if not isinstance(geometry.get("coordinates"), list):
        raise ValueError("Region geometry has no coordinates.")

    def count_positions(value) -> int:
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(
            isinstance(item, (int, float)) for item in value[:2]
        ):
            lon, lat = value[:2]
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError("Region coordinates must use EPSG:4326 longitude and latitude.")
            return 1
        if isinstance(value, (list, tuple)):
            return sum(count_positions(item) for item in value)
        raise ValueError("Region contains invalid coordinates.")

    if count_positions(geometry["coordinates"]) > 5000:
        raise ValueError("Region is too detailed; simplify it to at most 5,000 vertices.")


@lru_cache(maxsize=128)
def _cached_summary(path: str, band: int, modified: str, geometry_json: str) -> dict:
    geometry = json.loads(geometry_json)
    with rasterio.open(path) as source:
        source_crs, source_transform = _spatial_reference(source, Path(path).stem)
        projected = transform_geom("EPSG:4326", source_crs, geometry)
        bounds = geometry_bounds(projected)
        region_pixels, region_count_sampled = _count_region_pixels(projected, bounds, source_transform)
        try:
            region_window = window_from_bounds(*bounds, transform=source_transform)
            region_window = region_window.round_offsets().round_lengths().intersection(
                Window(0, 0, source.width, source.height)
            )
        except WindowError:
            return _empty_summary(region_pixels, region_count_sampled)
        if region_window.width <= 0 or region_window.height <= 0:
            return _empty_summary(region_pixels, region_count_sampled)

        count = 0
        minimum = maximum = mean = m2 = None
        sample_parts: list[np.ndarray] = []
        sample_size = 0
        rng = np.random.default_rng(42)
        row_start = int(region_window.row_off)
        col_start = int(region_window.col_off)
        row_stop = row_start + int(region_window.height)
        col_stop = col_start + int(region_window.width)

        for row in range(row_start, row_stop, 512):
            height = min(512, row_stop - row)
            for col in range(col_start, col_stop, 512):
                width = min(512, col_stop - col)
                window = Window(col, row, width, height)
                inside = geometry_mask(
                    [projected],
                    out_shape=(height, width),
                    transform=window_transform(window, source_transform),
                    invert=True,
                )
                values = source.read(band, window=window, masked=True)
                data = np.asarray(values.data, dtype=np.float64)
                valid = inside & ~np.ma.getmaskarray(values) & np.isfinite(data)
                selected = data[valid]
                if not selected.size:
                    continue
                block_count = int(selected.size)
                block_mean = float(selected.mean())
                block_m2 = float(np.sum((selected - block_mean) ** 2))
                if count == 0:
                    mean, m2 = block_mean, block_m2
                    minimum, maximum = float(selected.min()), float(selected.max())
                else:
                    delta = block_mean - mean
                    combined = count + block_count
                    m2 += block_m2 + delta * delta * count * block_count / combined
                    mean += delta * block_count / combined
                    minimum = min(minimum, float(selected.min()))
                    maximum = max(maximum, float(selected.max()))
                count += block_count
                if selected.size > 256:
                    selected = selected[rng.choice(selected.size, 256, replace=False)]
                sample_parts.append(selected)
                sample_size += selected.size
                if sample_size > 200_000:
                    sample = np.concatenate(sample_parts)
                    sample = sample[rng.choice(sample.size, 100_000, replace=False)]
                    sample_parts = [sample]
                    sample_size = sample.size

        if not region_pixels:
            return _empty_summary(region_pixels, region_count_sampled)
        if sample_size > 100_000:
            sample = np.concatenate(sample_parts)
            sample = sample[rng.choice(sample.size, 100_000, replace=False)]
        else:
            sample = np.concatenate(sample_parts) if sample_parts else np.array([], dtype=np.float64)
        return {
            "min": minimum,
            "max": maximum,
            "mean": mean,
            "median": float(np.median(sample)) if sample.size else None,
            "standard_deviation": math.sqrt(max(m2 or 0.0, 0.0) / count) if count else None,
            "valid_pixel_count": count,
            "region_pixel_count": region_pixels,
            "valid_region_percent": round(100 * count / region_pixels, 2),
            "region_pixel_count_is_approximate": region_count_sampled,
            "median_is_sampled": count > sample.size,
            "warning": None if count else "No map data squares cover the selected area.",
        }


def _count_region_pixels(geometry: dict, bounds: tuple, transform) -> tuple[int, bool]:
    region_window = window_from_bounds(*bounds, transform=transform).round_offsets().round_lengths()
    width = max(0, int(region_window.width))
    height = max(0, int(region_window.height))
    if not width or not height:
        return 0, False
    total_cells = width * height
    if total_cells > 20_000_000:
        factor = math.sqrt(total_cells / 20_000_000)
        sample_width = max(1, int(width / factor))
        sample_height = max(1, int(height / factor))
        sample_transform = from_bounds(*bounds, sample_width, sample_height)
        inside = geometry_mask(
            [geometry],
            out_shape=(sample_height, sample_width),
            transform=sample_transform,
            invert=True,
        )
        return round(np.count_nonzero(inside) * total_cells / (sample_width * sample_height)), True

    count = 0
    row_start = int(region_window.row_off)
    col_start = int(region_window.col_off)
    row_stop = row_start + height
    col_stop = col_start + width
    for row in range(row_start, row_stop, 512):
        tile_height = min(512, row_stop - row)
        for col in range(col_start, col_stop, 512):
            tile_width = min(512, col_stop - col)
            window = Window(col, row, tile_width, tile_height)
            inside = geometry_mask(
                [geometry],
                out_shape=(tile_height, tile_width),
                transform=window_transform(window, transform),
                invert=True,
            )
            count += int(np.count_nonzero(inside))
    return count, False


def _empty_summary(region_pixel_count: int = 0, approximate: bool = False) -> dict:
    return {
        "min": None,
        "max": None,
        "mean": None,
        "median": None,
        "standard_deviation": None,
        "valid_pixel_count": 0,
        "region_pixel_count": region_pixel_count,
        "valid_region_percent": 0,
        "region_pixel_count_is_approximate": approximate,
        "median_is_sampled": False,
        "warning": "The selected area is outside this map layer's coverage.",
    }


def _colorize(data: np.ndarray, valid: np.ndarray, variable: dict, ramp: str) -> np.ndarray:
    rgba = np.zeros((*data.shape, 4), dtype=np.uint8)
    categories = variable["categories"]
    if categories:
        for category in categories:
            color = category["color"].lstrip("#")
            rgb = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
            selected = valid & (data == category["value"])
            rgba[selected, :3] = rgb
            rgba[selected, 3] = category.get("alpha", 255)
    else:
        low = variable["display_min"]
        high = variable["display_max"]
        if low is None or high is None:
            return rgba
        normalized = np.clip((data.astype(np.float64) - low) / max(high - low, 1e-12), 0, 1)
        stops = RAMPS[ramp]
        positions = np.linspace(0, 1, len(stops))
        for channel in range(3):
            rgba[:, :, channel] = np.interp(
                normalized, positions, [stop[channel] for stop in stops]
            ).astype(np.uint8)
        rgba[:, :, 3] = valid.astype(np.uint8) * 255
    if categories:
        rgba[:, :, 3] *= valid.astype(np.uint8)
    return rgba


@lru_cache(maxsize=512)
def _render_tile(
    asset_id: str, path: str, variable_json: str, z: int, x: int, y: int, band: int, ramp: str
) -> bytes:
    width = 2 * WEB_MERCATOR_LIMIT / 2**z
    left = -WEB_MERCATOR_LIMIT + x * width
    top = WEB_MERCATOR_LIMIT - y * width
    transform = from_bounds(left, top - width, left + width, top, 256, 256)
    variable = json.loads(variable_json)
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff",
        GDAL_CACHEMAX=64,
    ):
        with rasterio.open(path) as source:
            source_crs, source_transform = _spatial_reference(source, Path(path).stem)
            with WarpedVRT(
                source,
                src_crs=source_crs,
                src_transform=source_transform,
                crs="EPSG:3857",
                transform=transform,
                width=256,
                height=256,
                resampling=Resampling.nearest if variable["categorical"] else Resampling.bilinear,
                nodata=source.nodata,
            ) as warped:
                values = warped.read(band, masked=True)
    data = np.asarray(values.data)
    valid = ~np.ma.getmaskarray(values) & np.isfinite(data)
    rgba = _colorize(data, valid, variable, ramp)
    output = Image.fromarray(rgba, mode="RGBA")
    from io import BytesIO

    buffer = BytesIO()
    output.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()
