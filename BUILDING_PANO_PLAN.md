# Building facade panorama download plan

## 1. 现有项目理解

本仓库已经完成了香港 `streetscape360` 的基础下载链路：

1. `data/hk_streetscape360/streetscape-360-api-wholehk.geojson` 保存全港街景采样点，坐标为 WGS84，经纬度加海拔。
2. `pan_tools.reader.PointReader` 可读取这些采样点，并做简单网格最近邻查询。
3. `pan_tools.downloader.PanDownloader` 接收 `(lng, lat, z)` 坐标，调用 MMS `nearby` 接口找到最近 pano，再自动按 `tile` 或 `gtpanos` 格式下载 24 张高分辨率 cube tiles。
4. `main.py` 目前支持随机点、前 N 个点、指定经纬度三种入口。

因此，针对建筑的任务不需要重新写街景下载器，重点是新增一层：

`building footprint/facade -> facade sampling points -> nearby streetscape pano candidates -> PanDownloader.run(points)`

## 2. 三份 CSDI 建筑数据的差异

### 2.1 `data/Building_SHP`

这是最适合作为主数据的数据集，包含建筑轮廓和多张关系/属性表。

主表：

| 文件 | 类型 | 坐标系 | 行数 | 作用 |
|---|---:|---|---:|---|
| `Building_Outline_Public_v20260519_Building_converted.shp` | Polygon | EPSG:2326 / Hong Kong 1980 Grid | 342,350 | 建筑物二维轮廓，后续提取建筑各个立面的核心输入 |

主表关键字段：

| 字段 | 作用 |
|---|---|
| `BuildingCS` | 建筑组合/状态键，可连接名称、工程历史、OP 结构关系表 |
| `BuildingID` | 建筑 ID |
| `GeoRefNo` | 地理参考号 |
| `Status` | 状态，建议先筛选 `Active` |
| `BuildingBl` | 建筑类型，例如 `Tower`、`Temporary Structure` |
| `BuildingNa` / `Building00` | 主表内的英文/中文名称字段，部分为空 |
| `BaseHeight` / `TopHeight` | 底高/顶高，部分为空 |
| `Storeys` / `StoreysInB` | 地上/地下层数，部分为空 |
| `Shape_Leng` / `Shape_Area` | 轮廓周长/面积，单位跟 EPSG:2326 一致，可按米理解 |

辅助表：

| 文件 | 类型 | 行数 | 作用 |
|---|---:|---:|---|
| `BuildingName_converted.shp` | 空点/属性表 | 90,593 | 建筑中英文名称，按 `BuildingCS` 连接 |
| `BuildingWorksHistory_converted.shp` | 空点/属性表 | 162,936 | 工程历史，按 `BuildingCS` 连接 |
| `BuildingRelateOPStructure_converted.shp` | 空点/关系表 | 53,277 | `BuildingCS` 与 `BuildingSt` 的关系 |
| `OPStructure_converted.shp` | 空点/属性表 | 54,422 | 结构、层数、OP 编号等，按 `BuildingSt` 连接 |
| `OP_converted.shp` | 空点/属性表 | 24,425 | OP 日期、GFA 等，按 `OPNo` 连接 |
| `BuildingLotNoInfo_converted.shp` | 空点/属性表 | 87,752 | 地段信息，含 `BuildingSt` |

结论：如果目标是“根据 building_shp 获取建筑各个面的 pano”，应以 `Building_converted.shp` 的 polygon 为唯一几何主表；其他文件只用于补充建筑名称、OP 日期、楼层、地段等属性。

### 2.2 `data/Database_of_private_buildings_in_Hong_Kong_SHP`

| 文件 | 类型 | 坐标系 | 行数 | 作用 |
|---|---:|---|---:|---|
| `BO_based_20260430_converted.shp` | Point | WGS84 | 768 | 私人楼宇数据库点位，包含地址和业主委员会名称 |

字段主要是：

| 字段 | 作用 |
|---|---|
| `ADDR_OF_BU` / `ADDR_OF_00` | 中文/英文地址 |
| `NAME_OF_OC` / `NAME_OF_00` | 中文/英文业主委员会名称 |

结论：这个数据集只有少量点，没有建筑轮廓，不能直接提取建筑立面。可作为私楼样本筛选、地址匹配或后期标注补充。

### 2.3 `data/Building_information_and_age_records_CSV`

| 文件 | 类型 | 坐标系 | 行数 | 作用 |
|---|---:|---|---:|---|
| `BDBIAR_gdb_2026_02_23_BDBIAR_converted.csv` | CSV point table | WGS84 | 51,037 | 楼宇资料及楼龄记录，含地址、区域、OP 编号/日期、用途、经纬度 |

关键字段：

| 字段 | 作用 |
|---|---|
| `ADDRESS_E` / `ADDRESS_C` | 英文/中文地址 |
| `SEARCH1_E/C`、`SEARCH2_E/C` | 地区、新界/九龙/港岛等分区 |
| `NSEARCH2_E/C` | OP 编号 |
| `NSEARCH3_E/C` | OP 日期，可近似作为楼龄来源 |
| `NSEARCH4_E/C` | 建筑类型，例如 `Tower` |
| `NSEARCH5_E/C` | 用途，例如住宅/综合用途 |
| `LATITUDE` / `LONGITUDE` | 点位坐标 |

结论：这个 CSV 有楼龄和用途价值，但也是点表，不适合直接提取建筑面。它适合作为 `Building_SHP` 的属性补充，匹配方式可用 OP 编号、地址、或空间最近邻。

## 3. 目标定义

目标输出不是简单“每栋楼一个最近街景”，而是：

1. 对每栋建筑 polygon 提取外轮廓边。
2. 将相邻、近共线的小边合并成更接近真实立面的 facade segment。
3. 为每个 facade segment 生成一个或多个朝外采样点。
4. 在街景采样点中寻找最可能看到该 facade 的 pano。
5. 调用现有 `PanDownloader` 下载去重后的 pano。
6. 保存建筑、立面、采样点、pano 的映射关系，便于后续裁剪视角或模型训练。

建议把“建筑各个面的 pan”定义为“每个建筑外立面对应的一个或多个街景 panorama”。如果后续需要真正的 facade crop，再基于 pano 与 facade 的方位角裁剪 cube/equirectangular 图像。

## 4. 推荐实现方案

### 4.1 新增脚本入口

建议补全当前空文件：

`demo/shp2pan.py`

脚本参数建议：

```bash
python demo/shp2pan.py --limit 100 --output data/building_pano
python demo/shp2pan.py --building-id 1105760144 --output data/building_pano
python demo/shp2pan.py --bbox 828000 832000 829000 833000 --output data/building_pano
```

建议参数：

| 参数 | 作用 |
|---|---|
| `--building-shp` | 默认指向 `data/Building_SHP/...Building_converted.shp` |
| `--streetscape-geojson` | 默认指向现有 streetscape360 GeoJSON |
| `--output` | 输出目录 |
| `--limit` | 调试阶段限制建筑数量 |
| `--building-id` | 指定单栋建筑 |
| `--bbox` | EPSG:2326 bbox，便于按区域测试 |
| `--facade-min-len` | 最短立面长度，建议默认 4m 或 5m |
| `--sample-spacing` | 长立面采样间距，建议 12m 到 20m |
| `--offset` | 从建筑边向外偏移的距离，建议 8m 到 15m |
| `--max-pano-dist` | facade 采样点到街景点最大距离，建议 35m 到 60m |
| `--dry-run` | 只生成映射，不下载 |
| `--download` | 调用 `PanDownloader` 下载 |

### 4.2 坐标和几何处理

建筑主表是 EPSG:2326，单位是米；街景点和 MMS API 使用 WGS84 经纬度。

推荐流程：

1. 用 `geopandas.read_file()` 读取建筑 polygon。
2. 保持 EPSG:2326 做所有几何运算，因为长度、offset、距离都是米。
3. 用 `pyproj.Transformer` 在 EPSG:2326 和 EPSG:4326 之间转换：
   - facade 采样点用于空间距离匹配时保留 EPSG:2326。
   - 调用 `PanDownloader.run()` 前转换为 `(lng, lat, z)`。
4. 把 streetscape360 的 WGS84 点预处理成 EPSG:2326 坐标索引，避免每次运行重复解析 730MB GeoJSON。

建议新增缓存：

```text
data/hk_streetscape360/streetscape_points_2326.parquet
```

字段：

| 字段 | 作用 |
|---|---|
| `lng` / `lat` / `z` | 原始 MMS API 坐标 |
| `x2326` / `y2326` | 米制坐标，用于最近邻 |
| `point_id` | 原始点序号 |

如果暂时不想引入 Parquet，可先用 CSV 或 pickle 做原型，但长期建议 Parquet。

### 4.3 facade segment 提取

对每栋建筑：

1. 只处理 `Status == "Active"` 的 polygon。
2. 对 `MultiPolygon` 或带洞 polygon，优先取 exterior ring；内洞一般不是街道可见外立面。
3. 从 exterior ring 的连续顶点生成 edge。
4. 删除长度小于 `facade-min-len` 的短边，或把短边并入相邻近共线边。
5. 对角度差小于 10 度、端点距离很近的连续边做合并，减少锯齿状轮廓造成的过采样。
6. 为每条 facade 计算：
   - `facade_id`
   - 起止点 `x1,y1,x2,y2`
   - 长度
   - 中点
   - 方位角
   - 朝外法线方向

朝外法线可用一个稳健判定：

1. 取边中点。
2. 计算边的两侧单位法线。
3. 分别向两侧偏移 `offset` 米。
4. 不在建筑 polygon 内的一侧视为外侧。

### 4.4 facade 采样点生成

每条 facade 至少生成 1 个采样点；长边按间距多点采样。

建议规则：

```text
n = max(1, ceil(facade_length / sample_spacing))
采样点 = facade 上均匀插值点 + outward_normal * offset
```

每个采样点保存：

| 字段 | 作用 |
|---|---|
| `building_id` / `BuildingCS` | 建筑标识 |
| `facade_id` | 立面标识 |
| `sample_id` | 采样点标识 |
| `x2326` / `y2326` | 米制采样点 |
| `lng` / `lat` | 转换后的 WGS84 坐标 |
| `facade_mid_x2326` / `facade_mid_y2326` | 对应立面中点 |
| `facade_azimuth` | 立面方向 |
| `view_azimuth` | 从 pano 指向 facade 的推荐视角方向 |

### 4.5 街景候选点选择

不要直接把 facade 外侧采样点丢给 MMS API。更稳的做法是先在已发布的 streetscape360 点集中找附近点，再把那个点传给 `PanDownloader`。

原因：

1. `streetscape360` 点是实际可查询的采集轨迹点。
2. building facade 外偏移点可能落到建筑内部、绿化带、天桥、不可行车区域。
3. 用已知街景点可减少 MMS nearby 接口失败率。

候选筛选建议：

1. 对每个 facade sample，在 streetscape 点索引中查询 `max-pano-dist` 米内的候选。
2. 优先选择：
   - 距离 sample 最近；
   - 从候选点看向 facade 的方向与 facade 外法线相反；
   - 候选点不在建筑 polygon 内；
   - 与 facade 中点距离合理，比如 5m 到 60m。
3. 每条 facade 保留 Top K 个候选，建议默认 `K=1` 或 `K=2`。
4. 对所有建筑去重 `(lng, lat, z)`，再交给 `PanDownloader.run(points)`。

### 4.6 下载与映射输出

建议输出目录：

```text
data/building_pano/
├── facade_samples.geojson
├── facade_pano_map.csv
├── unique_download_points.csv
├── pan_download/
│   ├── {panoName}/
│   └── point_pano_map.json
└── logs/
```

`facade_pano_map.csv` 建议字段：

| 字段 | 作用 |
|---|---|
| `building_id` | `BuildingID` |
| `building_cs` | `BuildingCS` |
| `building_name_en` / `building_name_zh` | 可从主表或名称表补充 |
| `facade_id` | 立面编号 |
| `sample_id` | 采样点编号 |
| `sample_lng` / `sample_lat` | facade 外侧采样点 |
| `street_lng` / `street_lat` / `street_z` | 实际送入 MMS 的街景点 |
| `street_dist_m` | sample 到街景点距离 |
| `view_azimuth` | pano 指向 facade 的推荐水平角 |
| `panoName` | 下载后由 `point_pano_map.json` 回填 |
| `download_status` | found / missing / downloaded / skipped |

## 5. 分阶段执行计划

### Phase 1: 数据探查和最小原型

1. 在 `demo/shp2pan.py` 中读取 `Building_converted.shp`。
2. 支持 `--limit`、`--building-id`、`--bbox` 三种调试入口。
3. 只对少量建筑提取 exterior edges，不做复杂合并。
4. 生成 `facade_samples.geojson`，用 GIS 软件或简单 folium 地图检查采样点是否落在建筑外侧。

验收标准：

1. 单栋建筑能生成每条外边的 facade sample。
2. EPSG:2326 到 WGS84 转换正确，点位能落在香港真实位置。
3. 输出中能看出每个 `facade_id` 的方向和长度。

### Phase 2: 街景点索引

1. 新增预处理函数，把 337 万 streetscape 点转换为 EPSG:2326。
2. 建立可复用的空间索引缓存。
3. 对每个 facade sample 查找半径内候选街景点。
4. 输出 `unique_download_points.csv`，暂不下载。

验收标准：

1. 每个 sample 能找到 0 到 K 个候选。
2. 候选距离分布合理，大多数在 10m 到 50m。
3. 不同 facade 的候选 pano 点有去重。

### Phase 3: 复用现有下载器

1. 将候选街景点转换为 `(lng, lat, z)`。
2. 调用现有 `PanDownloader.run(points)` 下载到 `data/building_pano/pan_download`。
3. 读取下载器生成的 `point_pano_map.json`。
4. 回填 `facade_pano_map.csv` 的 `panoName` 和状态。

验收标准：

1. 能对小范围建筑成功下载 pano。
2. 同一个 pano 被多个 facade 复用时只下载一次。
3. 映射表能追溯：建筑 -> facade -> sample -> streetscape point -> panoName -> 本地文件。

### Phase 4: facade 质量优化

1. 合并近共线短边，减少复杂轮廓过采样。
2. 增加长边多点采样。
3. 增加距离、角度、可见性打分。
4. 可选：用道路中心线或街景点轨迹方向进一步判断 facade 是否临街。

验收标准：

1. 每栋建筑的 pano 数量可控。
2. 大型建筑长立面不会只取一个点。
3. 小型附属构筑物、临时结构可按规则过滤。

### Phase 5: 后续视角裁剪

当前下载器保存的是 cube tiles，不是直接对准建筑的截图。若后续要得到“每个建筑面的图像 crop”，需要再做：

1. 把 cube tiles 拼成可投影的 panorama。
2. 根据 pano 坐标到 facade 中点的 `view_azimuth` 生成朝向建筑的 perspective crop。
3. 根据建筑高度、距离、相机高度估计垂直视场。
4. 保存 `building_id/facade_id/panoName/crop.jpg`。

这一步建议放在下载链路稳定后再做。

## 6. 主要风险和处理

| 风险 | 处理 |
|---|---|
| 建筑 polygon 是 EPSG:2326，街景点是 WGS84 | 几何运算全在 EPSG:2326，API 调用前再转 WGS84 |
| building facade 外偏移点不一定有街景 | 先匹配 streetscape360 已知点，再调用 MMS API |
| 一个 pano 对应多个 facade | 下载前按街景点或 panoName 去重，映射表保留多对一关系 |
| 复杂轮廓导致 facade 过多 | 设置最短边、近共线合并、建筑类型过滤 |
| `Building_SHP` 辅助表没有真实几何 | 只作为属性表 join，不参与 facade 提取 |
| 全量 342k 建筑和 337 万街景点计算量大 | 先 bbox/limit 原型，再建缓存和批处理 |

## 7. 建议下一步

优先实现 `demo/shp2pan.py` 的 Phase 1 到 Phase 3，小范围跑通完整链路：

1. 选 `--limit 20` 或一个小 `--bbox`。
2. 生成 facade samples 和 candidate streetscape points。
3. 用 `--dry-run` 检查 CSV/GeoJSON。
4. 再开 `--download` 调用现有下载器。
5. 检查 `facade_pano_map.csv` 与 `pan_download/{panoName}` 是否能一一追溯。

