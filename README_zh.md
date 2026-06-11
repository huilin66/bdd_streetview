[English](./README.md) | [中文](./README_zh.md)

# 香港街景全景下载工具

香港街景全景批量下载工具，从香港地政总署 MMS API 下载高分辨率街景立方体贴图，支持 Tile 和 GTPanos 两种存储格式。

## 目录结构

```
├── main.py                  # 入口
├── config/                  # 全局配置 (路径/凭证/API常量)
├── pan_tools/               # 核心工具包
│   ├── downloader.py        # 下载引擎 (发现→提取→下载)
│   ├── reader.py            # GeoJSON 数据读取器 (337万坐标点)
│   └── frontend/            # Puppeteer 提取脚本 (GTPanos格式)
└── data/hk_streetscape360/  # 数据目录
    ├── .env                 # API 凭证 (自行创建)
    ├── streetscape-360-api-wholehk.geojson
    └── pan_download/        # 下载输出
```

## 环境要求

- **Python** 3.8+
- **Node.js** 18+ (仅 GTPanos 格式需要)
- **Chromium/Chrome** (Puppeteer 自动复用本地安装)

## 安装

```bash
# 1. Python 依赖
pip install -r requirements.txt

# 2. Node 依赖 (Puppeteer)
cd pan_tools/frontend && npm install && cd ../..

# 3. 配置 API 凭证
# 在 data/hk_streetscape360/.env 中写入:
#   API_KEY=your_api_key
#   SHARE_CODE=your_share_code
```

## 使用方法

```bash
# 随机下载 10 个全景
python main.py --random 10

# 顺序下载前 100 个
python main.py --sample 100

# 指定坐标下载
python main.py --lng 114.168 --lat 22.284 --z 18.5

# 自定义输出目录
python main.py --random 5 --output ./my_output

# 查看所有参数
python main.py --help
```

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--lng` | 经度 | — |
| `--lat` | 纬度 | — |
| `--z` | 海拔高度 (米) | 16.0 |
| `--random N` | 随机下载 N 个 | 10 |
| `--sample N` | 顺序下载前 N 个 | — |
| `--output` | 输出目录 | `data/hk_streetscape360/pan_download` |

## 输出结构

```
pan_download/
├── {panoName}/
│   ├── metadata.json        # 全景元数据 (格式/坐标/layerId/原始detail)
│   └── r2/                  # 24张高分辨率1024px tiles
│       ├── px_0_0.jpg ... px_1_1.jpg
│       ├── nx_0_0.jpg ... nx_1_1.jpg
│       ├── py_0_0.jpg ... py_1_1.jpg
│       ├── ny_0_0.jpg ... ny_1_1.jpg
│       ├── pz_0_0.jpg ... pz_1_1.jpg
│       └── nz_0_0.jpg ... nz_1_1.jpg
├── gtpanos_data/            # GTPanos 提取中间数据 (每次自动清理)
└── point_pano_map.json      # 坐标→全景映射
```

每张 tile JPEG 内嵌 EXIF GPS 坐标及全景名称。

## 技术说明

- **两种格式**：代码自动检测 — URL 以 `.gtpanos` 结尾或 panoName 为纯数字 → GTPanos 格式，否则 → Tile 格式
- **GTPanos**：通过 Puppeteer 加载 MMS SDK 页面，从内部 `_panoObj` 提取 HTTP Range 字节偏移，再用 Range 请求逐 tile 下载
- **Tile**：直接拼接 URL 并发下载 `.pano` 文件 (8字节头 + JPEG流)
- **只下载高分辨率** r2 级别 (1024px)，跳过 r0 (128px) 和 r1 (无效)
- **断点续传**：已存在且大小 >100B 的文件自动跳过
