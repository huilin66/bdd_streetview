[English](./README.md) | [中文](./README_zh.md)

# Hong Kong Street View Panorama Downloader

Batch download high-resolution Hong Kong street view panorama cube-map tiles from the Lands Department MMS API. Supports both Tile and GTPanos storage formats.

## Project Structure

```
├── main.py                  # Entry point
├── config/                  # Global configuration (paths, credentials, API constants)
├── pan_tools/               # Core toolkit
│   ├── downloader.py        # Download engine (discovery → extraction → download)
│   ├── reader.py            # GeoJSON reader (3.37M coordinate points)
│   └── frontend/            # Puppeteer extraction script (GTPanos format)
└── data/hk_streetscape360/  # Data directory
    ├── .env                 # API credentials (create manually)
    ├── streetscape-360-api-wholehk.geojson
    └── pan_download/        # Download output
```

## Requirements

- **Python** 3.8+
- **Node.js** 18+ (GTPanos format only)
- **Chromium/Chrome** (Puppeteer reuses the local installation automatically)

## Installation

```bash
# 1. Python dependencies
pip install -r requirements.txt

# 2. Node dependencies (Puppeteer)
cd pan_tools/frontend && npm install && cd ../..

# 3. Configure API credentials
# Create data/hk_streetscape360/.env with:
#   API_KEY=your_api_key
#   SHARE_CODE=your_share_code
```

## Usage

```bash
# Download 10 random panoramas
python main.py --random 10

# Download first 100 panoramas in order
python main.py --sample 100

# Download by coordinates
python main.py --lng 114.168 --lat 22.284 --z 18.5

# Custom output directory
python main.py --random 5 --output ./my_output

# Show all options
python main.py --help
```

| Argument | Description | Default |
|---|---|---|
| `--lng` | Longitude | — |
| `--lat` | Latitude | — |
| `--z` | Elevation in meters | 16.0 |
| `--random N` | Download N random panoramas | 10 |
| `--sample N` | Download first N panoramas | — |
| `--output` | Output directory | `data/hk_streetscape360/pan_download` |

## Output Structure

```
pan_download/
├── {panoName}/
│   ├── metadata.json        # Panorama metadata (format, coordinates, layerId, raw detail)
│   └── r2/                  # 24 high-res 1024px tiles
│       ├── px_0_0.jpg ... px_1_1.jpg
│       ├── nx_0_0.jpg ... nx_1_1.jpg
│       ├── py_0_0.jpg ... py_1_1.jpg
│       ├── ny_0_0.jpg ... ny_1_1.jpg
│       ├── pz_0_0.jpg ... pz_1_1.jpg
│       └── nz_0_0.jpg ... nz_1_1.jpg
├── gtpanos_data/            # GTPanos extraction intermediates (auto-cleaned each run)
└── point_pano_map.json      # Coordinate → panorama mapping
```

Each tile JPEG has embedded EXIF GPS coordinates and panorama name.

## Data

See [DATA.md](./DATA.md) ([中文](./DATA_zh.md)) for dataset details, GeoJSON schema, panorama formats, and output structure.

## Technical Notes

- **Two formats**: Auto-detected — URL ending with `.gtpanos` or numeric panoName → GTPanos format; otherwise → Tile format
- **GTPanos**: Puppeteer loads the MMS SDK page and extracts HTTP Range byte offsets from the internal `_panoObj` state, then downloads tiles via Range requests
- **Tile**: Direct URL construction with concurrent `.pano` file downloads (8-byte header + JPEG stream)
- **High-res only**: Downloads only r2 level (1024px), skipping r0 (128px) and r1 (invalid)
- **Resumable**: Existing files larger than 100 bytes are automatically skipped
