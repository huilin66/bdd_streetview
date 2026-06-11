"""
香港街景全景坐标数据读取器
用法:
    reader = PointReader("streetscape-360-api-wholehk.geojson")
    print(reader.count)
    pt = reader.nearest(114.1792, 22.3304)  # 查找最近点
    pt = reader.random()                      # 随机取一点
    for pt in reader.iter(1000):              # 顺序迭代，每次1000个
        ...
"""

import json
import math
import random
from collections import defaultdict


class PointReader:
    def __init__(self, filepath, grid_res=0.001):
        """
        filepath: GeoJSON 文件路径
        grid_res: 空间索引网格分辨率 (度), 默认 0.001° ≈ 100m
        """
        self._points = []
        self._grid = defaultdict(list)
        self._grid_res = grid_res
        self._load(filepath)

    def _load(self, filepath):
        print(f"[Reader] 加载 {filepath} ...")
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        features = data.get("features", [])
        for feat in features:
            geom = feat.get("geometry", {})
            if geom.get("type") != "Point":
                continue
            c = geom["coordinates"]
            lng, lat = float(c[0]), float(c[1])
            z = float(c[2]) if len(c) > 2 else 16.0

            idx = len(self._points)
            self._points.append((lng, lat, z))

            # 网格索引
            gx = int(lng / self._grid_res)
            gy = int(lat / self._grid_res)
            self._grid[(gx, gy)].append(idx)

        print(f"[Reader] 加载完成: {len(self._points):,} 个点, "
              f"{len(self._grid):,} 个网格")

    # ─── 基础属性 ──────────────────────────────────────

    @property
    def count(self):
        return len(self._points)

    def __len__(self):
        return len(self._points)

    # ─── 最近点查询 ────────────────────────────────────

    def nearest(self, lng, lat, max_dist=0.01):
        """
        查找距离 (lng, lat) 最近的点。
        max_dist: 最大搜索范围 (度), 约 1km
        返回 (lng, lat, z, distance_in_degrees) 或 None
        """
        gx = int(lng / self._grid_res)
        gy = int(lat / self._grid_res)
        best = None
        best_d2 = max_dist ** 2

        # 搜索周围 3×3 网格
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                cell = (gx + dx, gy + dy)
                for idx in self._grid.get(cell, ()):
                    pt = self._points[idx]
                    d2 = (pt[0] - lng) ** 2 + (pt[1] - lat) ** 2
                    if d2 < best_d2:
                        best_d2 = d2
                        best = pt

        if best is not None:
            return best + (math.sqrt(best_d2),)
        return None

    # ─── 随机采样 ──────────────────────────────────────

    def random(self, n=1):
        """随机返回 n 个点"""
        if n == 1:
            return self._points[random.randint(0, len(self._points) - 1)]
        indices = random.sample(range(len(self._points)), min(n, len(self._points)))
        return [self._points[i] for i in indices]

    # ─── 顺序迭代 ──────────────────────────────────────

    def iter(self, batch_size=1000):
        """顺序迭代所有点, 每次返回 batch_size 个"""
        for i in range(0, len(self._points), batch_size):
            yield self._points[i : i + batch_size]

    def get(self, index):
        """获取指定索引的点"""
        return self._points[index]

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self._points[index]
        return self._points[index]

    # ─── 坐标列表导出 ──────────────────────────────────

    def to_list(self):
        """返回全部 (lng, lat, z) 列表"""
        return self._points
