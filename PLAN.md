# 项目计划：基于香港街景图像的建筑缺陷检测数据集构建

## 1. 项目概述

| 项目要素 | 内容 |
| :--- | :--- |
| **项目目标** | 批量下载香港全境建筑街景图像，构建用于建筑缺陷检测（裂缝、剥落、渗漏等）的图像数据集 |
| **数据来源** | 香港地政总署 — 街景360 API (Streetscape 360 API) |
| **数据范围** | 香港全境（约337万+街景点位，由官方GeoJSON文件提供） |
| **输出成果** | ① 结构化的街景图像数据集 ② 下载脚本 ③ 数据使用说明文档 |
| **研究者** | PolyU PhD Student |
| **合规性** | 香港地政总署学术用途免费授权 |

---

## 2. 技术路线

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  1. 数据索引    │ ──▶ │  2. 批量下载    │ ──▶ │  3. 数据清洗    │
│  解析GeoJSON    │     │  调用API获取    │     │  筛选含建筑的   │
│  获取全景ID     │     │  全景图像       │     │  图像，标注     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                           │
                                                           ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  6. 模型训练    │ ◀── │  5. 数据增强    │ ◀── │  4. 数据集划分  │
│  缺陷检测模型   │     │  扩充样本多样性 │     │  训练/验证/测试 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

---

## 3. 阶段一：数据索引获取与解析

### 3.1 数据源文件

| 文件 | 路径 | 大小 | 内容 |
| :--- | :--- | :--- | :--- |
| GeoJSON 索引 | `data/hk_streetscape360/streetscape-360-api-wholehk.geojson` | ~40M 行 | 3,371,328 个街景点的坐标（lon, lat, elevation） |

### 3.2 数据字段

```json
{
  "type": "Feature",
  "geometry": {
    "type": "Point",
    "coordinates": [114.242688176, 22.428724268, 14.162]  // [经度, 纬度, 高程(m)]
  },
  "properties": {}
}
```

### 3.3 关键指标

| 指标 | 数值 |
| :--- | :--- |
| 总点数 | 3,371,328 |
| 经度范围 | ~113.8° – 114.4° |
| 纬度范围 | ~22.1° – 22.6° |
| 高程范围 | ~0m – 950m |

---

## 4. 阶段二：批量下载脚本开发

### 4.1 功能需求

| 功能模块 | 说明 | 优先级 |
| :--- | :--- | :--- |
| GeoJSON 解析 | 流式读取大规模 GeoJSON，提取坐标 | P0 |
| 坐标→全景ID | 调用查询接口将坐标转为全景路径 | P0 |
| 全景下载 | 根据全景路径下载 360° 图像 | P0 |
| 并发控制 | asyncio + Semaphore 控制并发数 | P1 |
| 断点续传 | 记录已下载点位，中断后可继续 | P1 |
| 错误重试 | 网络异常时自动重试（指数退避） | P1 |
| 进度显示 | tqdm 实时显示下载进度与速率 | P2 |
| 速率限制 | 遵守 API rate limit | P2 |
| 完整性校验 | 下载后校验文件大小/hash | P3 |

### 4.2 技术选型

| 项目 | 选型 | 理由 |
| :--- | :--- | :--- |
| 编程语言 | Python 3.10+ | 生态丰富，async 支持成熟 |
| HTTP 客户端 | `aiohttp` | 异步高并发，连接池复用 |
| GeoJSON 解析 | `ijson` | 流式解析，内存友好（4000万行文件） |
| 并发控制 | `asyncio.Semaphore` | 标准库，零依赖 |
| 进度显示 | `tqdm` + `tqdm.asyncio` | 异步兼容 |
| 日志 | `logging` + `structlog` | 结构化日志，便于排查 |
| 配置管理 | `pydantic-settings` | 类型安全的配置 |

### 4.3 核心代码结构

```
bdd_streetview/
├── main.py                          # 入口
├── PLAN.md                          # 本文件
├── config.py                        # 配置（API key, 并发数, 路径等）
├── downloader/
│   ├── __init__.py
│   ├── geojson_reader.py            # 流式解析 GeoJSON
│   ├── panorama_lookup.py           # 坐标 → 全景路径查询
│   ├── image_downloader.py          # 全景图像下载
│   ├── checkpoint.py                # 断点续传管理
│   └── pipeline.py                  # 主流水线编排
├── data/
│   └── hk_streetscape360/
│       ├── streetscape-360-api-wholehk.geojson   # 源数据
│       ├── raw/                                   # 原始全景图像
│       │   └── {panorama_id}.jpg
│       ├── metadata/
│       │   ├── download_log.jsonl     # 逐条下载日志
│       │   ├── checkpoint.json        # 断点文件
│       │   └── panorama_index.csv     # 全景ID与坐标对应表
│       └── failed/                    # 下载失败记录
│           └── failed_points.csv
└── requirements.txt
```

### 4.4 配置设计 (`config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API
    api_key: str
    api_base_url: str = "https://data.map.gov.hk/api/3d-mms-data"
    api_timeout: int = 30

    # Paths
    geojson_path: str = "data/hk_streetscape360/streetscape-360-api-wholehk.geojson"
    output_dir: str = "data/hk_streetscape360/raw"
    metadata_dir: str = "data/hk_streetscape360/metadata"

    # Download control
    max_concurrent: int = 10
    max_retries: int = 3
    retry_backoff_base: float = 2.0
    rate_limit_per_sec: int = 50

    # GeoJSON parsing
    geojson_batch_size: int = 1000  # 流式分批大小

    class Config:
        env_file = ".env"
```

### 4.5 下载流水线伪代码

```python
# pipeline.py

async def run_pipeline():
    # 1. 加载断点
    checkpoint = Checkpoint.load()

    # 2. 流式读取 GeoJSON，跳过已下载的
    pending = geojson_stream(
        GEOJSON_PATH,
        skip_ids=checkpoint.completed_ids,
        batch_size=settings.geojson_batch_size,
    )

    # 3. 并发下载
    semaphore = asyncio.Semaphore(settings.max_concurrent)
    session = aiohttp.ClientSession()

    async def download_one(point):
        async with semaphore:
            pano_path = await lookup_panorama(session, point)
            if pano_path:
                success = await download_image(session, pano_path, point)
                if success:
                    checkpoint.mark_completed(point.id)
                return success

    tasks = [download_one(p) for p in pending]
    for coro in tqdm.as_completed(tasks, total=len(tasks)):
        await coro

    await session.close()
```

### 4.6 预计性能

| 指标 | 估算值 |
| :--- | :--- |
| 总数据量 | 约 337 万张全景图 |
| 单张下载耗时 | 约 0.2-1.0s（取决于网络） |
| 并发数 10 时吞吐 | 约 10-50 张/秒 |
| 预计总耗时 | 约 **20-95 小时**（带宽1-5 MB/s） |
| 预计存储 | 约 **1-5 TB**（取决于图像分辨率/压缩率） |

---

## 5. 阶段三：数据清洗与筛选

### 5.1 清洗目标

| 步骤 | 操作 | 工具/方法 |
| :--- | :--- | :--- |
| 去重 | 基于坐标/图像hash去除重复点位 | `imagehash` (pHash) |
| 质量筛选 | 剔除模糊、过曝、全黑图像 | 拉普拉斯方差、亮度直方图 |
| 建筑检测 | 筛选场景中实际包含建筑的图像 | YOLO / 语义分割预处理 |
| 格式统一 | 统一分辨率、色彩空间 | OpenCV / PIL |
| 元数据 | 补全坐标、拍摄时间、视角信息 | GeoJSON + EXIF |

### 5.2 建筑存在性检测策略

- **方案 A**：使用预训练 YOLO/DeepLab 模型进行语义分割，检测"building"类别占比
- **方案 B**：基于全景图像的下半部分（天空以下）进行纹理分析（粗糙 → 建筑/植被，均匀 → 天空/水面）
- **方案 C**：利用全景元数据中的 GPS 坐标，结合 OpenStreetMap building footprint 进行交叉验证

推荐：**方案 A + C 组合**，先用地物足迹粗筛，再用视觉模型精细筛选。

### 5.3 缺陷标注策略

| 缺陷类型 | 定义 | 标注方式 |
| :--- | :--- | :--- |
| 裂缝 (Crack) | 墙体表面线状开裂 | Bounding box / Polygon |
| 剥落 (Spalling) | 混凝土表层脱落 | Bounding box / Polygon |
| 渗漏 (Leakage) | 水渍、锈迹 | Bounding box / Polygon |
| 霉变 (Mold) | 墙体表面霉斑 | Bounding box / Polygon |
| 外露钢筋 (Exposed Rebar) | 混凝土剥落后钢筋外露 | Bounding box |

标注工具推荐：LabelStudio / CVAT / LabelImg

---

## 6. 阶段四：数据集划分

### 6.1 划分策略

| 集合 | 比例 | 用途 |
| :--- | :--- | :--- |
| 训练集 (Train) | 70% | 模型训练 |
| 验证集 (Val) | 15% | 超参数调优、早停 |
| 测试集 (Test) | 15% | 最终性能评估 |

### 6.2 划分原则

- **地理分层**：按香港行政区（18区）分层采样，确保训练/测试集地理分布一致
- **缺陷类型均衡**：各类缺陷比例在三个集合中尽量一致
- **避免数据泄漏**：同一建筑的不同视角图像放入同一集合
- **不随机打乱全景序列**：同一街道连拍图像放入同一集合

---

## 7. 阶段五：数据增强

### 7.1 增强策略

| 增强类型 | 方法 | 适用场景 |
| :--- | :--- | :--- |
| 几何变换 | 随机裁剪、翻转、旋转（±15°） | 通用 |
| 色彩增强 | 亮度/对比度/饱和度调整 | 不同天气/光照 |
| 噪声注入 | 高斯噪声、JPEG压缩伪影 | 鲁棒性提升 |
| 天气模拟 | 雾、雨滴、阴影叠加 | 香港多雨天气适应 |
| MixUp / CutMix | 图像混合 | 少样本缺陷类型 |

### 7.2 注意事项

- 裂缝/剥落等小目标缺陷 → 避免过度裁剪导致目标丢失
- 360°全景图 → 增强前先做 equirectangular projection 或直接处理 cube faces
- 保留原始图像作为 baseline，增强版本单独存储

---

## 8. 阶段六：模型训练

### 8.1 Baseline 模型候选

| 模型 | 骨干网络 | 特点 |
| :--- | :--- | :--- |
| YOLOv8 / YOLOv10 | CSPDarknet | 实时检测，部署友好 |
| DETR (DEtection TRansformer) | ResNet + Transformer | 无需 NMS，端到端 |
| Mask R-CNN | ResNet + FPN | 同时支持检测+分割 |
| SegFormer | MiT (Transformer) | 语义分割，适合裂缝等细长目标 |

### 8.2 训练策略

- 从 COCO 预训练权重迁移
- 初始学习率 1e-4，Cosine Annealing 衰减
- 使用 Focal Loss 处理类别不均衡
- 早停策略：验证 mAP 连续 10 epoch 不提升则停止
- Mixed Precision (FP16) 加速训练

### 8.3 评估指标

| 指标 | 说明 |
| :--- | :--- |
| mAP@0.5 | 检测任务主要指标 |
| mAP@0.5:0.95 | COCO 标准指标 |
| Precision / Recall | 各类别分别统计 |
| IoU | 预测框与真实框重叠度 |

---

## 9. 输出文件结构

```
dataset/
├── raw/                              # 原始全景图像
│   ├── {panorama_id_1}.jpg
│   ├── {panorama_id_2}.jpg
│   └── ...
├── cleaned/                          # 清洗后图像
│   ├── images/
│   └── masks/                        # 语义分割标注
├── splits/                           # 数据集划分文件
│   ├── train.txt
│   ├── val.txt
│   └── test.txt
├── metadata/
│   ├── panorama_index.csv            # 全景ID-坐标映射
│   ├── download_log.jsonl            # 下载日志
│   ├── building_labels.json          # 建筑存在性标注
│   └── defect_annotations.json       # 缺陷标注（COCO 格式）
├── scripts/
│   ├── download_streetview.py
│   ├── clean_and_filter.py
│   ├── split_dataset.py
│   └── augment.py
└── README.md
```

---

## 10. 里程碑与时间线

| 阶段 | 内容 | 预计时间 |
| :--- | :--- | :--- |
| ① 数据索引 | GeoJSON 解析 + 坐标→全景ID映射 | 1-2 天 |
| ② 批量下载 | 异步下载脚本开发 + 运行 | 2-3 天（开发）+ 1-4 天（运行） |
| ③ 数据清洗 | 去重、质量筛选、建筑检测 | 3-5 天 |
| ④ 缺陷标注 | 人工标注 + 自动预标注 | 7-14 天（取决于规模） |
| ⑤ 数据集划分 | 分层划分 + 统计报告 | 1 天 |
| ⑥ 数据增强 | 实现增强 pipeline | 2-3 天 |
| ⑦ 模型训练 | Baseline 训练 + 调优 | 5-10 天 |
| ⑧ 模型评估 | 定量评估 + 错误分析 | 2-3 天 |

---

## 11. 风险与应对

| 风险 | 影响 | 应对措施 |
| :--- | :--- | :--- |
| API 限流严格 | 下载时间大幅延长 | 申请提额；多密钥轮换；分区域分批下载 |
| 全景图像不含建筑 | 数据集可用率低 | 结合 OSM building footprint 预筛选点位 |
| 缺陷样本不足 | 模型难以收敛 | 数据增强；合成缺陷图像；半监督/自监督 |
| 存储空间不足 | 下载中断 | 预估需求提前扩容；分批下载+清理 |
| 标注成本过高 | 进度严重拖延 | 先用预训练模型自动标注，人工只审核纠错 |

---

## 12. 当前状态

| 任务 | 状态 | 备注 |
| :--- | :--- | :--- |
| GeoJSON 文件 | ✅ 已就绪 | 3,371,328 个点位 |
| API Key | ⏳ 待申请 | 发邮件至 `3dmap@landsd.gov.hk` |
| API 文档调研 | ⏳ 进行中 | 需确认坐标→全景的 REST endpoint |
| 下载脚本 | 🔲 待开发 | 预研完成，架构已设计 |
| 数据清洗 | 🔲 未开始 | — |
