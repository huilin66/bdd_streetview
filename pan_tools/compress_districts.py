"""
按 district 压缩全景数据 —— 每个区一个 zip，已存在则跳过

用法:
    python pan_tools/compress_districts.py <base_dir> [--districts KLC,KT,SSP]
    python pan_tools/compress_districts.py //158.132.186.40/isds/huilin/bdd/collected_data/HKStreetScape360
"""
import argparse
import subprocess
import sys
import zipfile
from pathlib import Path


def compress_district(district_dir: Path, zip_path: Path) -> tuple[int, int]:
    """用 Python zipfile 流式压缩，返回 (file_count, size_bytes)"""
    count = 0
    total_size = 0
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_STORED) as zf:
        for f in district_dir.rglob("*"):
            if not f.is_file():
                continue
            try:
                arcname = str(f.relative_to(district_dir.parent))
                zf.write(str(f), arcname)
                count += 1
                total_size += f.stat().st_size
                if count % 50000 == 0:
                    print(f"  {count:,} files...")
            except OSError as e:
                print(f"  [skip] {f}: {e}")
    return count, total_size


def main():
    parser = argparse.ArgumentParser(description="按 district 压缩全景数据")
    parser.add_argument("base_dir", type=str, help="包含各 district 文件夹的根目录")
    parser.add_argument("--districts", type=str, default="",
                        help="逗号分隔的 district 列表，默认扫描 base_dir 下所有子目录")
    args = parser.parse_args()

    base = Path(args.base_dir)
    if not base.is_dir():
        print(f"错误: 目录不存在 — {base}")
        sys.exit(1)

    if args.districts:
        names = [n.strip() for n in args.districts.split(",") if n.strip()]
    else:
        names = sorted(
            d.name for d in base.iterdir()
            if d.is_dir() and not d.name.startswith(".") and not d.name.endswith(".zip")
        )

    if not names:
        print("未找到待压缩的 district 目录")
        sys.exit(0)

    for name in names:
        district_dir = base / name
        zip_path = base / f"{name}.zip"

        if not district_dir.is_dir():
            print(f"[{name}] 跳过: 目录不存在")
            continue

        if zip_path.exists():
            print(f"[{name}] 跳过: {zip_path.name} 已存在 ({zip_path.stat().st_size / 1024 / 1024:.0f} MB)")
            continue

        print(f"[{name}] 压缩中...  ({district_dir})")
        try:
            count, size = compress_district(district_dir, zip_path)
            zip_mb = zip_path.stat().st_size / 1024 / 1024
            print(f"[{name}] 完成: {count:,} 文件, {size / 1024 / 1024:.0f} MB → {zip_mb:.0f} MB")
        except Exception as e:
            print(f"[{name}] 失败: {e}")
            if zip_path.exists():
                zip_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
