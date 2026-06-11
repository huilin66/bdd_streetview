"""
点位可视化工具 —— 读取 GeoJSON 所有点坐标，生成自包含 HTML 地图 (folium 风格)

用法:
    python pan_tools/visualize.py              # 生成文件 + 启动本地服务器
    python pan_tools/visualize.py --no-serve    # 仅生成文件
输出:
    pan_tools/frontend/
        map.html        # 地图页面
        points.bin      # Float32 二进制坐标 (~27 MB)
"""
import os
import argparse
import http.server
import json
import struct
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import GEOJSON_PATH

OUTPUT_DIR = Path(__file__).resolve().parent / "frontend"
GRID_RES = 0.001
HTTP_PORT = 18080

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>香港街景全景坐标可视化 — {count} 个点</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9/dist/leaflet.css" />
<style>
  html, body {{ margin:0; padding:0; width:100%; height:100%; overflow:hidden; font-family: 'Segoe UI', sans-serif; }}
  #map {{ width:100%; height:100%; background:#e8e8e8; }}
  #info {{
    position:absolute; bottom:20px; left:20px; z-index:1000;
    background:rgba(0,0,0,0.7); color:#fff; padding:8px 14px;
    border-radius:6px; font-size:13px; pointer-events:none;
  }}
  #status {{
    position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
    z-index:2000; background:rgba(0,0,0,0.8); color:#fff; padding:14px 24px;
    border-radius:8px; font-size:14px; text-align:center;
  }}
  .basemap-switch {{
    position:absolute; top:10px; right:10px; z-index:1000;
  }}
  .basemap-switch button {{
    margin-left:4px; padding:6px 12px; border:1px solid #999;
    border-radius:4px; background:#fff; cursor:pointer; font-size:12px;
  }}
  .basemap-switch button.active {{ background:#1a73e8; color:#fff; border-color:#1a73e8; }}
</style>
</head>
<body>
<div id="map"></div>
<div id="status">加载数据中...</div>
<div id="info"></div>
<div class="basemap-switch">
  <button id="btn-street" class="active">街道</button>
  <button id="btn-satellite">卫星</button>
</div>

<script src="https://unpkg.com/leaflet@1.9/dist/leaflet.js"></script>
<script>
const GRID_RES = {grid_res};
const POINT_RADIUS = 1.2;
const POINT_COLOR = '#ff6b35';

let rawData = null, pointCount = 0;
let grid = new Map();

// ── 底图 ─────────────────────────────────────────
const basemaps = {{
  street: L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>', maxZoom: 22, maxNativeZoom: 19,
  }}),
  satellite: L.tileLayer('https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
    attribution: 'Esri', maxZoom: 24, maxNativeZoom: 19,
  }}),
}};

const map = L.map('map', {{ preferCanvas:true, zoomControl:true }}).setView([22.38, 114.10], 11);
basemaps.street.addTo(map);

['street','satellite'].forEach(k => {{
  document.getElementById('btn-' + k).onclick = () => {{
    Object.values(basemaps).forEach(l => map.removeLayer(l));
    basemaps[k].addTo(map);
    document.querySelectorAll('.basemap-switch button').forEach(b => b.classList.remove('active'));
    document.getElementById('btn-' + k).classList.add('active');
  }};
}});

// ── Canvas 覆盖层 ───────────────────────────────
const CanvasLayer = L.Layer.extend({{
  onAdd: function() {{
    this._canvas = L.DomUtil.create('canvas', 'leaflet-canvas-layer');
    this._canvas.style.position = 'absolute';
    this._canvas.style.pointerEvents = 'none';
    this._ctx = this._canvas.getContext('2d');
    map.getPanes().overlayPane.appendChild(this._canvas);
    map.on('moveend zoomend', this._redraw, this);
    this._resize();
    this._redraw();
  }},
  onRemove: function() {{
    map.off('moveend zoomend', this._redraw, this);
    L.DomUtil.remove(this._canvas);
  }},
  _resize: function() {{
    const size = map.getSize();
    const dpr = window.devicePixelRatio || 1;
    this._canvas.width = size.x * dpr;
    this._canvas.height = size.y * dpr;
    this._canvas.style.width = size.x + 'px';
    this._canvas.style.height = size.y + 'px';
    this._ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }},
  _redraw: function() {{
    if (!rawData) return;
    const t0 = performance.now();
    const size = map.getSize();
    const bounds = map.getBounds();
    const pad = 0.002;
    const b = {{ west:bounds.getWest()-pad, east:bounds.getEast()+pad,
                south:bounds.getSouth()-pad, north:bounds.getNorth()+pad }};

    const gxMin = Math.floor(b.west/GRID_RES), gxMax = Math.floor(b.east/GRID_RES);
    const gyMin = Math.floor(b.south/GRID_RES), gyMax = Math.floor(b.north/GRID_RES);

    const ctx = this._ctx;
    ctx.clearRect(0, 0, size.x, size.y);
    ctx.fillStyle = POINT_COLOR;

    const pmap = new Uint8Array(size.x * size.y);
    let drawn = 0, skipped = 0;

    for (let gx=gxMin; gx<=gxMax; gx++) {{
      for (let gy=gyMin; gy<=gyMax; gy++) {{
        const cell = grid.get(gx+','+gy);
        if (!cell) continue;
        for (let k=0; k<cell.length; k++) {{
          const idx = cell[k];
          const lng = rawData[idx*2], lat = rawData[idx*2+1];
          if (lng<b.west || lng>b.east || lat<b.south || lat>b.north) continue;
          const pt = map.latLngToContainerPoint([lat,lng]);
          const px = Math.floor(pt.x), py = Math.floor(pt.y);
          if (px<0 || px>=size.x || py<0 || py>=size.y) continue;
          const pidx = py*size.x + px;
          if (pmap[pidx]) {{ skipped++; continue; }}
          pmap[pidx] = 1;
          ctx.fillRect(px, py, POINT_RADIUS, POINT_RADIUS);
          drawn++;
        }}
      }}
    }}

    document.getElementById('info').textContent =
      `绘制: ${{drawn.toLocaleString()}} 点 (跳过 ${{skipped.toLocaleString()}}) | ${{(performance.now()-t0).toFixed(0)}}ms | 总计: ${{pointCount.toLocaleString()}} 点`;
  }},
}});
const canvasLayer = new CanvasLayer();
canvasLayer.addTo(map);

// ── 加载数据 ─────────────────────────────────────
async function load() {{
  const resp = await fetch('points.bin');
  const buf = await resp.arrayBuffer();
  rawData = new Float32Array(buf);
  pointCount = rawData.length / 2;

  document.getElementById('status').textContent = '建立空间索引...';
  await new Promise(r => setTimeout(r, 10));

  const total = pointCount;
  for (let i=0; i<total; i++) {{
    const lng=rawData[i*2], lat=rawData[i*2+1];
    const key = Math.floor(lng/GRID_RES)+','+Math.floor(lat/GRID_RES);
    let cell = grid.get(key);
    if (!cell) {{ cell=[]; grid.set(key,cell); }}
    cell.push(i);
    if (i%1000000===0 && i>0) {{
      document.getElementById('status').textContent =
        `建立空间索引 ${{(i/1e6).toFixed(0)}}M / ${{(total/1e6).toFixed(1)}}M 个点...`;
      await new Promise(r => setTimeout(r, 0));
    }}
  }}

  document.getElementById('status').style.display='none';
  canvasLayer._resize();
  canvasLayer._redraw();
}}

load();
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="生成街景点位可视化地图")
    parser.add_argument("--no-serve", action="store_true", help="仅生成文件，不启动服务器")
    parser.add_argument("--port", type=int, default=HTTP_PORT, help=f"HTTP 端口 (默认 {HTTP_PORT})")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bin_path = OUTPUT_DIR / "points.bin"

    print(f"读取 GeoJSON: {GEOJSON_PATH}")
    with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data["features"]
    count = len(features)
    print(f"  共 {count:,} 个点")

    print(f"写入二进制坐标: {bin_path}")
    with open(bin_path, "wb") as f:
        for i, feat in enumerate(features):
            c = feat["geometry"]["coordinates"]
            f.write(struct.pack("<ff", c[0], c[1]))
            if (i + 1) % 1_000_000 == 0:
                print(f"  {i + 1:,}/{count:,}")

    size_mb = bin_path.stat().st_size / 1024 / 1024
    print(f"  {size_mb:.1f} MB ({count * 8:,} bytes)")

    html_path = OUTPUT_DIR / "map.html"
    html_path.write_text(HTML_TEMPLATE.format(count=f"{count:,}", grid_res=GRID_RES), encoding="utf-8")
    print(f"生成 HTML: {html_path}")

    if args.no_serve:
        print(f"\n用浏览器打开前先启动服务器:")
        print(f"  python -m http.server {args.port} -d {OUTPUT_DIR}")
        print(f"  然后打开 http://localhost:{args.port}/map.html")
        return

    # 启动 HTTP 服务器 + 打开浏览器
    import threading
    os.chdir(str(OUTPUT_DIR))

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *a):
            pass

    server = http.server.HTTPServer(("", args.port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://localhost:{args.port}/map.html"
    print(f"\nHTTP 服务器已启动: {url}")
    webbrowser.open(url)
    print("按 Ctrl+C 停止服务器")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("\n已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
