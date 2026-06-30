"""
Crop building facade views from already downloaded Streetscape360 cube tiles.

Typical usage:
    python pan_tools/facade_cropper.py \
        --candidates data/building_pano_random5_download/facade_pano_candidates.csv \
        --pano-dir data/building_pano_random5_download/pan_download \
        --output data/building_pano_random5_download/facade_crops
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image
from tqdm import tqdm


FACES = ("px", "nx", "py", "ny", "pz", "nz")
TILES_PER_FACE = 2
DEFAULT_GT_FACE_ORDER = ("nx", "px", "ny", "py", "nz", "pz")
DEFAULT_GT_TILE_ORDER = ((0, 0), (1, 0), (0, 1), (1, 1))
DOWNLOADER_FACE_ORDER = ("px", "nx", "py", "ny", "pz", "nz")
DOWNLOADER_TILE_ORDER = ((0, 0), (0, 1), (1, 0), (1, 1))


@dataclass(frozen=True)
class CropRequest:
    row_number: int
    building_id: str
    building_cs: str
    facade_id: str
    sample_id: str
    pano_name: str
    view_azimuth: float
    facade_length: float | None
    street_distance_m: float | None
    angle_error_deg: float | None
    candidate_rank: int | None
    source: dict[str, str]


class CubeMap:
    def __init__(self, faces: dict[str, Image.Image]):
        missing = [face for face in FACES if face not in faces]
        if missing:
            raise ValueError(f"Missing cube faces: {', '.join(missing)}")

        sizes = {faces[face].size for face in FACES}
        if len(sizes) != 1:
            raise ValueError(f"Cube faces have inconsistent sizes: {sorted(sizes)}")

        self.size = faces["px"].size[0]
        if faces["px"].size[0] != faces["px"].size[1]:
            raise ValueError(f"Cube faces must be square, got {faces['px'].size}")

        self.faces = {
            face: np.asarray(faces[face].convert("RGB"), dtype=np.float32)
            for face in FACES
        }

    @classmethod
    def from_pano_dir(cls, pano_dir: Path, gt_order: str = "geomtable") -> "CubeMap":
        r2_dir = pano_dir / "r2"
        gt_tiles_dir = pano_dir / "tiles"
        if r2_dir.exists():
            return cls(_load_named_tile_faces(r2_dir))
        if gt_tiles_dir.exists():
            return cls(_load_numbered_gt_faces(gt_tiles_dir, gt_order))
        raise FileNotFoundError(f"No r2/ or tiles/ directory found in {pano_dir}")

    def perspective(
        self,
        yaw_deg: float,
        pitch_deg: float,
        hfov_deg: float,
        width: int,
        height: int,
    ) -> Image.Image:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")
        if not 1.0 <= hfov_deg < 179.0:
            raise ValueError("hfov must be in [1, 179) degrees")

        aspect = width / height
        hfov = math.radians(hfov_deg)
        vfov = 2.0 * math.atan(math.tan(hfov / 2.0) / aspect)

        xs = (np.arange(width, dtype=np.float32) + 0.5) / width
        ys = (np.arange(height, dtype=np.float32) + 0.5) / height
        xx, yy = np.meshgrid(
            (2.0 * xs - 1.0) * math.tan(hfov / 2.0),
            (1.0 - 2.0 * ys) * math.tan(vfov / 2.0),
        )
        zz = np.ones_like(xx, dtype=np.float32)

        pitch = math.radians(pitch_deg)
        cp, sp = math.cos(pitch), math.sin(pitch)
        y1 = yy * cp + zz * sp
        z1 = -yy * sp + zz * cp
        x1 = xx

        yaw = math.radians(yaw_deg)
        cy, sy = math.cos(yaw), math.sin(yaw)
        xw = x1 * cy + z1 * sy
        yw = y1
        zw = -x1 * sy + z1 * cy

        norm = np.sqrt(xw * xw + yw * yw + zw * zw)
        xw /= norm
        yw /= norm
        zw /= norm

        out = np.zeros((height, width, 3), dtype=np.float32)
        abs_x = np.abs(xw)
        abs_y = np.abs(yw)
        abs_z = np.abs(zw)

        x_major = (abs_x >= abs_y) & (abs_x >= abs_z)
        y_major = (abs_y > abs_x) & (abs_y >= abs_z)
        z_major = ~(x_major | y_major)

        self._sample_face(out, "px", x_major & (xw > 0), -zw / abs_x, -yw / abs_x)
        self._sample_face(out, "nx", x_major & (xw <= 0), zw / abs_x, -yw / abs_x)
        self._sample_face(out, "py", y_major & (yw > 0), xw / abs_y, zw / abs_y)
        self._sample_face(out, "ny", y_major & (yw <= 0), xw / abs_y, -zw / abs_y)
        self._sample_face(out, "pz", z_major & (zw > 0), xw / abs_z, -yw / abs_z)
        self._sample_face(out, "nz", z_major & (zw <= 0), -xw / abs_z, -yw / abs_z)

        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), mode="RGB")

    def _sample_face(
        self,
        out: np.ndarray,
        face: str,
        mask: np.ndarray,
        sc: np.ndarray,
        tc: np.ndarray,
    ) -> None:
        if not np.any(mask):
            return

        img = self.faces[face]
        max_idx = self.size - 1
        u = np.clip((sc[mask] + 1.0) * 0.5 * max_idx, 0, max_idx)
        v = np.clip((tc[mask] + 1.0) * 0.5 * max_idx, 0, max_idx)

        x0 = np.floor(u).astype(np.int32)
        y0 = np.floor(v).astype(np.int32)
        x1 = np.clip(x0 + 1, 0, max_idx)
        y1 = np.clip(y0 + 1, 0, max_idx)
        wx = (u - x0)[:, None]
        wy = (v - y0)[:, None]

        top = img[y0, x0] * (1.0 - wx) + img[y0, x1] * wx
        bottom = img[y1, x0] * (1.0 - wx) + img[y1, x1] * wx
        out[mask] = top * (1.0 - wy) + bottom * wy


def _load_named_tile_faces(r2_dir: Path) -> dict[str, Image.Image]:
    faces = {}
    for face in FACES:
        tiles = {}
        for col in range(TILES_PER_FACE):
            for row in range(TILES_PER_FACE):
                path = r2_dir / f"{face}_{col}_{row}.jpg"
                if not path.exists():
                    raise FileNotFoundError(path)
                tiles[(col, row)] = Image.open(path)
        faces[face] = _stitch_2x2(tiles)
    return faces


def _load_numbered_gt_faces(tiles_dir: Path, gt_order: str) -> dict[str, Image.Image]:
    if gt_order == "geomtable":
        face_order = DEFAULT_GT_FACE_ORDER
        tile_order = DEFAULT_GT_TILE_ORDER
    elif gt_order == "downloader":
        face_order = DOWNLOADER_FACE_ORDER
        tile_order = DOWNLOADER_TILE_ORDER
    else:
        raise ValueError("--gt-order must be 'geomtable' or 'downloader'")

    paths = [tiles_dir / f"tile_{idx:03d}.jpg" for idx in range(len(face_order) * 4)]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing GTPanos tiles: " + ", ".join(missing[:3]))

    faces: dict[str, Image.Image] = {}
    tile_idx = 0
    for face in face_order:
        tiles = {}
        for col, row in tile_order:
            tiles[(col, row)] = Image.open(paths[tile_idx])
            tile_idx += 1
        faces[face] = _stitch_2x2(tiles)
    return faces


def _stitch_2x2(tiles: dict[tuple[int, int], Image.Image]) -> Image.Image:
    tile_size = tiles[(0, 0)].size[0]
    if any(tile.size != (tile_size, tile_size) for tile in tiles.values()):
        sizes = sorted({tile.size for tile in tiles.values()})
        raise ValueError(f"Tiles must be square and same-sized, got {sizes}")

    face_img = Image.new("RGB", (tile_size * 2, tile_size * 2))
    for (col, row), tile in tiles.items():
        face_img.paste(tile.convert("RGB"), (col * tile_size, row * tile_size))
    return face_img


def read_requests(csv_path: Path, max_rank: int | None, require_found: bool) -> list[CropRequest]:
    requests: list[CropRequest] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row_number, row in enumerate(reader, start=1):
            pano_name = row.get("panoName", "").strip()
            if not pano_name:
                continue
            if require_found and row.get("download_status", "").strip() not in {"found", "downloaded", "skipped"}:
                continue

            rank = _optional_int(row.get("candidate_rank"))
            if max_rank is not None and rank is not None and rank > max_rank:
                continue

            requests.append(
                CropRequest(
                    row_number=row_number,
                    building_id=row.get("building_id", "").strip() or "unknown_building",
                    building_cs=row.get("building_cs", "").strip(),
                    facade_id=row.get("facade_id", "").strip() or f"row{row_number}",
                    sample_id=row.get("sample_id", "").strip(),
                    pano_name=pano_name,
                    view_azimuth=float(row["view_azimuth"]),
                    facade_length=_optional_float(row.get("facade_length")),
                    street_distance_m=_optional_float(row.get("street_distance_m")),
                    angle_error_deg=_optional_float(row.get("angle_error_deg")),
                    candidate_rank=rank,
                    source=row,
                )
            )
    return requests


def crop_facades(
    requests: Iterable[CropRequest],
    pano_dir: Path,
    output_dir: Path,
    width: int,
    height: int,
    hfov: float,
    pitch: float,
    yaw_offset: float,
    auto_hfov: bool,
    min_hfov: float,
    max_hfov: float,
    gt_order: str,
    jpeg_quality: int,
    overwrite: bool,
) -> list[dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, object]] = []
    cube_cache: dict[str, CubeMap] = {}

    for request in tqdm(list(requests), desc="裁剪立面", unit="crop"):
        crop_hfov = _facade_hfov(request, hfov, auto_hfov, min_hfov, max_hfov)
        rel_path = Path(_safe_name(request.building_id)) / (
            f"{_safe_name(request.facade_id)}__{_safe_name(request.pano_name)}__row{request.row_number}.jpg"
        )
        out_path = output_dir / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)

        status = "ok"
        error = ""
        if out_path.exists() and not overwrite:
            status = "skipped"
        else:
            try:
                cube = cube_cache.get(request.pano_name)
                if cube is None:
                    cube = CubeMap.from_pano_dir(pano_dir / request.pano_name, gt_order=gt_order)
                    cube_cache[request.pano_name] = cube
                yaw = (request.view_azimuth + yaw_offset) % 360.0
                img = cube.perspective(yaw, pitch, crop_hfov, width, height)
                img.save(out_path, quality=jpeg_quality, optimize=True)
            except Exception as exc:  # noqa: BLE001 - manifest records per-row failures.
                status = "failed"
                error = str(exc)

        manifest_rows.append(
            {
                "crop_path": str(rel_path),
                "status": status,
                "error": error,
                "building_id": request.building_id,
                "building_cs": request.building_cs,
                "facade_id": request.facade_id,
                "sample_id": request.sample_id,
                "panoName": request.pano_name,
                "view_azimuth": request.view_azimuth,
                "hfov": crop_hfov,
                "pitch": pitch,
                "yaw_offset": yaw_offset,
                "facade_length": request.facade_length,
                "street_distance_m": request.street_distance_m,
                "angle_error_deg": request.angle_error_deg,
                "candidate_rank": request.candidate_rank,
                "source_row": request.row_number,
            }
        )

    return manifest_rows


def write_manifest(output_dir: Path, rows: list[dict[str, object]]) -> None:
    fields = [
        "crop_path",
        "status",
        "error",
        "building_id",
        "building_cs",
        "facade_id",
        "sample_id",
        "panoName",
        "view_azimuth",
        "hfov",
        "pitch",
        "yaw_offset",
        "facade_length",
        "street_distance_m",
        "angle_error_deg",
        "candidate_rank",
        "source_row",
    ]
    with (output_dir / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field)) for field in fields})


def _facade_hfov(
    request: CropRequest,
    default_hfov: float,
    auto_hfov: bool,
    min_hfov: float,
    max_hfov: float,
) -> float:
    if not auto_hfov or not request.facade_length or not request.street_distance_m:
        return default_hfov
    if request.street_distance_m <= 0:
        return default_hfov
    fov = math.degrees(2.0 * math.atan((request.facade_length * 1.8) / (2.0 * request.street_distance_m)))
    return max(min_hfov, min(max_hfov, fov))


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip() or "unknown")


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _csv_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.6f}"
    return str(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract facade crops from already downloaded Streetscape360 cube tiles."
    )
    parser.add_argument("--candidates", type=Path, required=True, help="facade_pano_candidates.csv")
    parser.add_argument("--pano-dir", type=Path, required=True, help="Directory containing downloaded pano folders")
    parser.add_argument("--output", type=Path, required=True, help="Output directory for facade crops")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--hfov", type=float, default=70.0, help="Horizontal field of view in degrees")
    parser.add_argument("--auto-hfov", action="store_true", help="Estimate hfov from facade length and distance")
    parser.add_argument("--min-hfov", type=float, default=25.0)
    parser.add_argument("--max-hfov", type=float, default=90.0)
    parser.add_argument("--pitch", type=float, default=0.0, help="Camera pitch in degrees, positive looks upward")
    parser.add_argument("--yaw-offset", type=float, default=0.0, help="Calibration offset added to view_azimuth")
    parser.add_argument(
        "--gt-order",
        choices=("downloader", "geomtable"),
        default="downloader",
        help="Tile order for local GTPanos tile_000..tile_023 files",
    )
    parser.add_argument("--max-rank", type=int, default=1, help="Keep candidates with candidate_rank <= N")
    parser.add_argument("--include-unfound", action="store_true", help="Do not require download_status=found")
    parser.add_argument("--quality", type=int, default=92, help="JPEG quality")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requests = read_requests(args.candidates, args.max_rank, require_found=not args.include_unfound)
    if not requests:
        print("No candidate rows matched the filters", file=sys.stderr)
        return 1

    rows = crop_facades(
        requests=requests,
        pano_dir=args.pano_dir,
        output_dir=args.output,
        width=args.width,
        height=args.height,
        hfov=args.hfov,
        pitch=args.pitch,
        yaw_offset=args.yaw_offset,
        auto_hfov=args.auto_hfov,
        min_hfov=args.min_hfov,
        max_hfov=args.max_hfov,
        gt_order=args.gt_order,
        jpeg_quality=args.quality,
        overwrite=args.overwrite,
    )
    write_manifest(args.output, rows)
    ok = sum(1 for row in rows if row["status"] in {"ok", "skipped"})
    failed = sum(1 for row in rows if row["status"] == "failed")
    print(f"[facade_cropper] crops={ok}, failed={failed}, output={args.output.resolve()}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
