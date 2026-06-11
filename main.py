"""
香港街景全景下载入口
    python main.py                          # 随机测试单点
    python main.py --random 10              # 随机下载 10 个
    python main.py --sample 100             # 顺序下载前 100 个
    python main.py --lng 114.2 --lat 22.33 --z 28  # 指定坐标
"""

import argparse
from pathlib import Path

from config import *
from pan_tools import PointReader, PanDownloader


def main():
    parser = argparse.ArgumentParser(description="香港街景全景批量下载")
    parser.add_argument("--lng", type=float, help="经度")
    parser.add_argument("--lat", type=float, help="纬度")
    parser.add_argument("--z", type=float, default=16.0, help="海拔/米")
    parser.add_argument("--random", type=int, default=10, help="随机下载 N 个全景")
    parser.add_argument("--sample", type=int, default=0, help="顺序下载前 N 个全景")
    parser.add_argument("--output", type=str, default=str(PANORAMA_OUTPUT), help="输出目录")
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    downloader = PanDownloader(
        output_dir=str(output),
        api_key=API_KEY,
        share_code=SHARE_CODE,
        geotwin_host=GEOTWIN_HOST,
        layer_ids=PANORAMA_LAYER_IDS,
        extractor_path=str(EXTRACTOR_SCRIPT),
        max_workers=DOWNLOAD_WORKERS,
    )

    if args.lng is not None and args.lat is not None:
        downloader.run([(args.lng, args.lat, args.z)])
        return

    print(f"[Main] 加载数据: {GEOJSON_PATH}")
    reader = PointReader(str(GEOJSON_PATH))
    print(f"[Main] 共 {reader.count:,} 个点")

    if args.random > 0:
        pts = reader.random(args.random)
        print(f"[Main] 随机选取 {len(pts)} 个点")
    elif args.sample > 0:
        pts = reader.get(slice(0, args.sample))
        print(f"[Main] 顺序选取前 {len(pts)} 个点")
    else:
        pts = [reader.random()]
        print(f"[Main] 测试单点: {pts[0]}")

    downloader.run(pts)


if __name__ == "__main__":
    main()
