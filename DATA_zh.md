[English](./DATA.md) | [中文](./DATA_zh.md)

# 数据目录

## 目录结构

```
data/hk_streetscape360/
├── .env                              # API 凭证
├── streetscape-360-api-wholehk.geojson  # 坐标数据集 (~730 MB)
└── pan_download/                     # 全景下载输出
    ├── {panoName}/                   # 每个全景独立目录
    │   ├── metadata.json             # 全景元数据
    │   └── r2/                       # 24张高分辨率 tile (1024px)
    │       ├── px_0_0.jpg ... px_1_1.jpg   # +X 面
    │       ├── nx_0_0.jpg ... nx_1_1.jpg   # -X 面
    │       ├── py_0_0.jpg ... py_1_1.jpg   # +Y 面 (上)
    │       ├── ny_0_0.jpg ... ny_1_1.jpg   # -Y 面 (下)
    │       ├── pz_0_0.jpg ... pz_1_1.jpg   # +Z 面
    │       └── nz_0_0.jpg ... nz_1_1.jpg   # -Z 面
    ├── gtpanos_data/                 # GTPanos 提取缓存 (每次自动清理)
    └── point_pano_map.json           # 坐标→全景 映射
```

## GeoJSON 数据集

- **文件**: `streetscape-360-api-wholehk.geojson`
- **来源**: [空间数据共享平台 — 街景360 API](https://portal.csdi.gov.hk/csdi-webpage/apidoc/streetscape-360-api)
- **大小**: ~730 MB
- **数据量**: 3,371,328 个坐标点，覆盖全港范围

### 数据结构

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [114.242688, 22.428724, 14.162]
      },
      "properties": {}
    }
  ]
}
```

每个坐标点为 `[经度, 纬度, 海拔(米)]`。全港海拔范围约 8–85 米。所有 feature 的 `properties` 均为空对象。

### 覆盖范围

数据集通过四个阶段逐步发布（2022年12月至2025年3月）：

| 阶段 | 时间 | 覆盖范围 |
|---|---|---|
| 第一期 | 2022 年 12 月 | 九龍東 |
| 第二期 | 2023 年 9 月 | 九龍中 |
| 第三期 | 2024 年 6 月 | 大嶼山及離島 |
| 第四期 | 2025 年 3 月 | 港島、新界 — **全港覆蓋** |

### 数据更新

地政总署持续更新和扩展数据集。新的 MMS 采集任务会追加坐标点及更新的影像。可在[空间数据共享平台](https://portal.csdi.gov.hk)获取最新版本。

## API 凭证 (`.env`)

```
API_KEY=你的_api_key
SHARE_CODE=你的_share_code
```

两者均需在[空间数据共享平台](https://portal.csdi.gov.hk)注册后免费获取。API 免费供公众使用，设有调用频率和带宽限制。

## 全景格式

API 提供两种存储格式的全景，下载器自动检测：

| | Tile | GTPanos |
|---|---|---|
| **panoName 格式** | 日期编码, 如 `20220225G13628` | 纯数字序号, 如 `1074` |
| **存储方式** | 每 tile 独立 `.pano` 文件 | 单文件 `.gtpanos` 打包 |
| **访问方式** | 每 tile 直链 URL | HTTP Range 字节请求 |
| **采集时期** | 2022 年起 (较新) | 2022 年之前 (较旧) |
| **影像质量** | 更高 (新摄像设备) | 标准 |

Tile 格式的 panoName 以 `YYYYMMDD` 编码采集日期（如 `20220225` = 2022年2月25日）。

### Tile 分辨率级别

| 级别 | 分辨率 | 状态 |
|---|---|---|
| `r0` | 128 px | 仅 r2 不可用时下载 |
| `r1` | 512 px | **无效** (占位数据) |
| `r2` | 1024 px | 始终下载 (高分辨率) |

## 输出元数据 (`metadata.json`)

```json
{
  "panoName": "20220202G05512",
  "folderUrl": "https://services1.map.gov.hk/api/3d-mms-data/MMS/KE/pano/20220202",
  "lng": 114.225,
  "lat": 22.315,
  "z": 18.926,
  "format": "tile",
  "layerId": 42,
  "panoDetail": { ... }
}
```

GTPanos 格式的 `panoDetail` 包含 MMS SDK 内部 `_panoObj` 对象的完整原始元数据。

## 可视化工具

可生成全部 337 万坐标点的地图可视化：

```bash
python pan_tools/visualize.py
# 输出: pan_tools/frontend/map.html
```

工具生成单个自包含 HTML 文件 (~36 MB)，坐标数据以 base64 内嵌。使用 Leaflet + Canvas 渲染，带像素级去重。底图可在 LandsD / OSM / CartoDB 之间切换。
