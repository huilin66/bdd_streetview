"""
香港街景全景下载引擎
"""

import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import piexif
import requests
from tqdm import tqdm

# 立方体贴图结构 (固定, 不属于配置)
CUBE_FACES = ["px", "nx", "py", "ny", "pz", "nz"]
TILE_LEVEL = "r2"
TILES_PER_FACE = 2


def _to_exif_rational(val):
    d = int(val)
    m = int((val - d) * 60)
    s = int(((val - d) * 60 - m) * 60 * 100)
    return ((d, 1), (m, 1), (s, 100))


def _embed_exif(filepath, lng, lat, pano_name, tile_label=""):
    try:
        gps_ifd = {
            piexif.GPSIFD.GPSLatitudeRef: "N" if lat >= 0 else "S",
            piexif.GPSIFD.GPSLatitude: _to_exif_rational(abs(lat)),
            piexif.GPSIFD.GPSLongitudeRef: "E" if lng >= 0 else "W",
            piexif.GPSIFD.GPSLongitude: _to_exif_rational(abs(lng)),
        }
        desc = f"{pano_name}" if not tile_label else f"{pano_name} {tile_label}"
        zeroth_ifd = {piexif.ImageIFD.ImageDescription: desc}
        exif_bytes = piexif.dump({"0th": zeroth_ifd, "GPS": gps_ifd})
        piexif.insert(exif_bytes, str(filepath))
    except Exception:
        pass


class TokenManager:
    def __init__(self, api_key, share_code, geotwin_host):
        self.api_key = api_key
        self.share_code = share_code
        self.geotwin_host = geotwin_host
        self.token = None
        self._fetch_token()

    def _fetch_token(self):
        url = f"{self.geotwin_host}/sys/workspace/share/check/link"
        params = {"shareCode": self.share_code, "key": self.api_key}
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data["code"] != 0:
            raise RuntimeError(f"Token fetch failed: {data.get('msg')}")
        self.token = data["data"]["token"]

    @property
    def key(self):
        return self.api_key

    @property
    def tk(self):
        return self.token

    def refresh(self):
        self._fetch_token()


class PanoDiscovery:
    def __init__(self, tm, layer_ids):
        self.tm = tm
        self.layer_ids = layer_ids

    @staticmethod
    def detect_format(pano_data):
        url = pano_data.get("url", "")
        pano_name = pano_data.get("panoName", "")
        if url.lower().endswith(".gtpanos") or (pano_name and pano_name.isdigit()):
            return "gtpanos"
        return "tile"

    def search(self, lng, lat, z=16.0):
        url = f"{self.tm.geotwin_host}/sys/pano/search/nearby"
        params = {"key": self.tm.api_key}
        headers = {"token": self.tm.token, "Content-Type": "application/json"}
        body = {"layerId": self.layer_ids, "x": lng, "y": lat, "z": z}
        resp = requests.post(url, params=params, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data["code"] != 0 or not data.get("data"):
            return None

        closest = data["data"][0]
        name = closest["panoName"].replace(".jpg", "")
        url_base = closest["url"]
        if "?key=" in url_base:
            url_base = url_base[: url_base.index("?key=")]

        return {
            "panoId": closest["panoId"],
            "panoName": name,
            "folderUrl": url_base,
            "lng": lng,
            "lat": lat,
            "z": z,
            "format": self.detect_format(closest),
            "layerId": closest.get("layerId"),
        }

    def batch_search(self, points, on_found=None):
        pano_map = {}
        point_map = []

        for pt in tqdm(points, desc="发现全景", unit="pt"):
            lng, lat = pt[0], pt[1]
            z = pt[2] if len(pt) > 2 and pt[2] is not None else 16.0
            info = self.search(lng, lat, z)
            if info:
                pn = info["panoName"]
                if pn not in pano_map:
                    pano_map[pn] = info
                point_map.append((lng, lat, pn))
                if on_found:
                    on_found(lng, lat, pn)
            else:
                point_map.append((lng, lat, None))
            time.sleep(0.2)

        return list(pano_map.values()), point_map


class TileDownloader:
    def __init__(self, tm, output_dir, max_workers=8):
        self.tm = tm
        self.output_dir = Path(output_dir)
        self.max_workers = max_workers
        self.session = requests.Session()

    def _gen_urls(self, info):
        urls = []
        fld = info["folderUrl"]
        pn = info["panoName"]
        for face in CUBE_FACES:
            for c in range(TILES_PER_FACE):
                for r in range(TILES_PER_FACE):
                    tname = f"{pn}_{face}_{TILE_LEVEL}_{c}_{r}"
                    url = f"{fld}/{TILE_LEVEL}/{tname}.pano?key={self.tm.key}&token={self.tm.tk}"
                    urls.append((url, face, c, r))
        return urls

    def _download_one(self, url, pano_name, lng, lat, face, col, row):
        out_dir = self.output_dir / pano_name / TILE_LEVEL
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{face}_{col}_{row}.jpg"
        if out_path.exists() and out_path.stat().st_size > 100:
            return "skipped", None

        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=60)
                if resp.status_code == 404:
                    return "not_found", None
                resp.raise_for_status()
                jpeg = resp.content[8:]
                if len(jpeg) < 100 or jpeg[:2] != b"\xff\xd8":
                    return "bad_data", None
                out_path.write_bytes(jpeg)
                _embed_exif(out_path, lng, lat, pano_name, f"{face}_{col}_{row}")
                return "ok", None
            except requests.RequestException:
                if attempt < 2:
                    time.sleep(1)
        return "failed", None

    def download(self, info, pbar=None):
        pn = info["panoName"]
        lng, lat = info["lng"], info["lat"]
        tiles = self._gen_urls(info)
        stats = {"ok": 0, "skipped": 0, "not_found": 0, "failed": 0, "bad_data": 0}

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {}
            for url, face, col, row in tiles:
                f = ex.submit(self._download_one, url, pn, lng, lat, face, col, row)
                futures[f] = (face, col, row)
            for f in as_completed(futures):
                status, _ = f.result()
                stats[status] = stats.get(status, 0) + 1
                if pbar:
                    pbar.update(1)
                    pbar.set_postfix(ok=stats["ok"], skip=stats["skipped"])

        meta_path = self.output_dir / pn / "metadata.json"
        meta_path.write_text(
            json.dumps({k: v for k, v in info.items() if k != "panoId"},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return stats


class GtpanosDownloader:
    def __init__(self, tm, output_dir, max_workers=8):
        self.tm = tm
        self.output_dir = Path(output_dir)
        self.max_workers = max_workers
        self.session = requests.Session()

    def download(self, info, gt_ranges, pbar=None):
        folder_url = info["folderUrl"]
        lng, lat, pn = info["lng"], info["lat"], info["panoName"]
        if len(gt_ranges) == 72:
            gt_ranges = gt_ranges[48:]

        stats = {"ok": 0, "skipped": 0, "not_found": 0, "failed": 0, "bad_data": 0}
        out_dir = self.output_dir / pn
        out_dir.mkdir(parents=True, exist_ok=True)
        sep = "&" if "?" in folder_url else "?"
        base_url = f"{folder_url}{sep}token={self.tm.tk}"

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {}
            for i, rng in enumerate(gt_ranges):
                frm, to = rng["from"], rng["to"]
                if frm >= to:
                    continue
                tname = f"tile_{i:03d}"
                f = ex.submit(self._download_one, base_url, frm, to, pn, tname, lng, lat)
                futures[f] = i
            for f in as_completed(futures):
                status, _ = f.result()
                stats[status] = stats.get(status, 0) + 1
                if pbar:
                    pbar.update(1)
                    pbar.set_postfix(ok=stats["ok"], skip=stats["skipped"])

        meta_path = out_dir / "metadata.json"
        meta = {k: v for k, v in info.items() if k != "panoDetail"}
        if info.get("panoDetail"):
            meta["panoDetail"] = info["panoDetail"]
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return stats

    def _download_one(self, url, byte_from, byte_to, pano_name, tile_name, lng, lat):
        out_dir = self.output_dir / pano_name / "tiles"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{tile_name}.jpg"
        if out_path.exists() and out_path.stat().st_size > 100:
            return "skipped", None

        headers = {"Range": f"bytes={byte_from}-{byte_to}"}
        for attempt in range(3):
            try:
                resp = self.session.get(url, headers=headers, timeout=60)
                if resp.status_code == 404:
                    return "not_found", None
                resp.raise_for_status()
                jpeg = resp.content[8:]
                if len(jpeg) < 100 or jpeg[:2] != b"\xff\xd8":
                    return "bad_data", None
                out_path.write_bytes(jpeg)
                _embed_exif(out_path, lng, lat, pano_name, tile_name)
                return "ok", None
            except requests.RequestException:
                if attempt < 2:
                    time.sleep(1)
        return "failed", None


def extract_gtpanos(panos, output_dir, extractor_script):
    output_dir = Path(output_dir)
    if output_dir.exists():
        shutil.rmtree(str(output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)

    pending_path = output_dir.parent / "gtpanos_pending.json"
    pending_path.write_text(json.dumps(panos, ensure_ascii=False, indent=2), encoding="utf-8")

    result = subprocess.run(
        ["node", str(extractor_script), "--input", str(pending_path),
         "--output-dir", str(output_dir)],
        capture_output=True, text=True, timeout=600,
        cwd=str(Path(extractor_script).parent),
    )
    if result.returncode != 0:
        print(f"[extract_gtpanos] 失败: {result.stderr}")
        return {}

    loaded = {}
    for f in output_dir.glob("*.json"):
        entry = json.loads(f.read_text(encoding="utf-8"))
        pn = entry.get("panoDetail", {}).get("panoName", f.stem)
        loaded[pn] = entry
    return loaded


class PanDownloader:
    """全景下载入口 —— 自动检测格式, tile 直下 + gtpanos 自动提取"""

    def __init__(self, output_dir, api_key, share_code, geotwin_host,
                 layer_ids, extractor_path, max_workers=8):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.extractor_script = Path(extractor_path)
        self.max_workers = max_workers

        self.tm = TokenManager(api_key, share_code, geotwin_host)
        self.discovery = PanoDiscovery(self.tm, layer_ids)
        self.tile_dl = TileDownloader(self.tm, output_dir, max_workers)
        self.gt_dl = GtpanosDownloader(self.tm, output_dir, max_workers)

    def download_points(self, points):
        t_start = time.time()
        print(f"\n=== Phase 1: 发现 ({len(points)} 个坐标) ===")
        panos, point_map = self.discovery.batch_search(points)
        if not panos:
            print("未找到任何全景")
            return 0, {}

        tile_panos = [p for p in panos if p.get("format") != "gtpanos"]
        gt_panos = [p for p in panos if p.get("format") == "gtpanos"]
        print(f"  Tile: {len(tile_panos)}, GTPanos: {len(gt_panos)}  [{time.time() - t_start:.1f}s]")

        total = 0
        all_stats = {"tile": {}, "gtpanos": {}}

        if gt_panos:
            print("\n=== Phase 2: GTPanos 提取 ===")
            pending = [
                {"panoId": p["panoId"], "panoName": p["panoName"],
                 "folderUrl": p["folderUrl"], "lng": p["lng"], "lat": p["lat"],
                 "layerId": p.get("layerId")}
                for p in gt_panos
            ]
            gdata_dir = self.output_dir / "gtpanos_data"
            loaded = extract_gtpanos(pending, str(gdata_dir), str(self.extractor_script))

            coords_lookup = {p["panoName"]: (p["lng"], p["lat"]) for p in gt_panos}
            # 预计算总 tile 数
            gt_tasks = []
            for pn, data in loaded.items():
                ranges = data.get("gtRanges", [])
                if not ranges:
                    continue
                if len(ranges) == 72:
                    ranges = ranges[48:]
                valid = [r for r in ranges if r["from"] < r["to"]]
                if valid:
                    detail = data.get("panoDetail", {})
                    lng, lat = coords_lookup.get(pn, (0, 0))
                    info = {
                        "panoName": pn,
                        "folderUrl": detail.get("_folderUrl", ""),
                        "panoId": detail.get("panoId", ""),
                        "format": "gtpanos",
                        "lng": lng, "lat": lat,
                        "layerId": detail.get("layerId"),
                        "panoDetail": detail,
                    }
                    gt_tasks.append((info, valid))
            gt_total = sum(len(r) for _, r in gt_tasks)

            t_gt = time.time()
            gt_pbar = tqdm(total=gt_total, desc="  GTPanos", unit="tile")
            for info, ranges in gt_tasks:
                stats = self.gt_dl.download(info, ranges, pbar=gt_pbar)
                all_stats["gtpanos"][info["panoName"]] = stats
                total += stats["ok"] + stats["skipped"]
            gt_pbar.close()
            print(f"  GTPanos 完成 [{time.time() - t_gt:.1f}s]")

        if tile_panos:
            print(f"\n=== Phase 3: Tile 下载 ({len(tile_panos)} 个) ===")
            tile_total = len(tile_panos) * 24
            t_tile = time.time()
            tile_pbar = tqdm(total=tile_total, desc="  Tile", unit="tile")
            for p in tile_panos:
                stats = self.tile_dl.download(p, pbar=tile_pbar)
                all_stats["tile"][p["panoName"]] = stats
                total += stats["ok"] + stats["skipped"]
            tile_pbar.close()
            print(f"  Tile 完成 [{time.time() - t_tile:.1f}s]")

        map_path = self.output_dir / "point_pano_map.json"
        map_path.write_text(
            json.dumps([{"lng": lng, "lat": lat, "pano": pn}
                        for lng, lat, pn in point_map],
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"\n=== 完成: {total} tiles, 总耗时 {time.time() - t_start:.1f}s ===")
        return total, all_stats

    def run(self, points):
        return self.download_points(points)
