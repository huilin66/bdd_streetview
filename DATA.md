[English](./DATA.md) | [中文](./DATA_zh.md)

# Data Directory

## Structure

```
data/hk_streetscape360/
├── .env                              # API credentials
├── streetscape-360-api-wholehk.geojson  # Coordinate dataset (~730 MB)
└── pan_download/                     # Downloaded panorama output
    ├── {panoName}/                   # Per-panorama directory
    │   ├── metadata.json             # Panorama metadata
    │   └── r2/                       # 24 high-res tiles (1024px)
    │       ├── px_0_0.jpg ... px_1_1.jpg   # +X face
    │       ├── nx_0_0.jpg ... nx_1_1.jpg   # -X face
    │       ├── py_0_0.jpg ... py_1_1.jpg   # +Y face (up)
    │       ├── ny_0_0.jpg ... ny_1_1.jpg   # -Y face (down)
    │       ├── pz_0_0.jpg ... pz_1_1.jpg   # +Z face
    │       └── nz_0_0.jpg ... nz_1_1.jpg   # -Z face
    ├── gtpanos_data/                 # GTPanos extraction cache (auto-cleaned)
    └── point_pano_map.json           # Coordinate → panorama mapping
```

## GeoJSON Dataset

- **File**: `streetscape-360-api-wholehk.geojson`
- **Source**: [CSDI Portal — Streetscape 360 API](https://portal.csdi.gov.hk/csdi-webpage/apidoc/streetscape-360-api)
- **Size**: ~730 MB
- **Features**: 3,371,328 points covering the entire Hong Kong territory

### Schema

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

Each coordinate is `[longitude, latitude, elevation_in_meters]`. Elevation ranges approximately 8–85 m across Hong Kong. The `properties` object is empty for all features.

### Coverage

The dataset was progressively released through four phases from December 2022 to March 2025:

| Phase | Date | Coverage |
|---|---|---|
| 1 | Dec 2022 | Kowloon East |
| 2 | Sep 2023 | Kowloon Central |
| 3 | Jun 2024 | Lantau & Islands |
| 4 | Mar 2025 | HK Island, New Territories — **full territory** |

### Updates

The Lands Department continues to update and expand the dataset. New MMS collection runs produce additional coordinate points and newer imagery. Check the [CSDI Portal](https://portal.csdi.gov.hk) for the latest version.

## API Credentials (`.env`)

```
API_KEY=your_api_key_here
SHARE_CODE=your_share_code_here
```

Both values are obtained by registering on the [CSDI Portal](https://portal.csdi.gov.hk). The API is free for public use, with rate limits on call frequency and bandwidth.

## Panorama Formats

The API serves panoramas in two storage formats, automatically detected by the downloader:

| | Tile | GTPanos |
|---|---|---|
| **panoName pattern** | Date-coded, e.g. `20220225G13628` | Sequential numeric, e.g. `1074` |
| **Storage** | Individual `.pano` files per tile | Monolithic `.gtpanos` file |
| **Access method** | Direct URL per tile | HTTP Range byte requests |
| **Collection era** | 2022 onwards (newer) | Pre-2022 (older) |
| **Image quality** | Higher (newer camera equipment) | Standard |

The Tile format panoName encodes the capture date as `YYYYMMDD` (e.g., `20220225` = February 25, 2022).

### Tile Levels

| Level | Resolution | Status |
|---|---|---|
| `r0` | 128 px | Downloaded only if r2 unavailable |
| `r1` | 512 px | **Invalid** (placeholder data) |
| `r2` | 1024 px | Always downloaded (high-res) |

## Output Metadata (`metadata.json`)

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

For GTPanos format, `panoDetail` contains the full raw metadata extracted from the MMS SDK's internal `_panoObj` object.

## Visualization Tool

A map visualization of all 3.37M coordinate points is available:

```bash
python pan_tools/visualize.py
# Output: pan_tools/frontend/map.html
```

The tool generates a single self-contained HTML file (~36 MB) with coordinate data embedded inline (base64). Uses Leaflet + canvas rendering with pixel-level deduplication. Switches between LandsD / OSM / CartoDB basemaps.
