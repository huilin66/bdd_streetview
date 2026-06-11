/**
 * 使用 Puppeteer 从 MMS SDK 提取 GTPanos _gtRanges 数据
 * 用法:
 *   node extract_gtpanos.js --lng 114.242688 --lat 22.428724 [--z 16] [--output data.json]
 *   node extract_gtpanos.js --input gtpanos_pending.json [--output-dir ./gtpanos_data]
 */

const puppeteer = require('puppeteer-core');
const http = require('http');
const fs = require('fs');
const path = require('path');

const HTML_FILE = path.join(__dirname, 'index.html');
const HTTP_PORT = 18086;

function parseArgs() {
  const args = { z: 16.0 };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--lng' && i + 1 < argv.length) args.lng = parseFloat(argv[++i]);
    if (argv[i] === '--lat' && i + 1 < argv.length) args.lat = parseFloat(argv[++i]);
    if (argv[i] === '--z' && i + 1 < argv.length) args.z = parseFloat(argv[++i]);
    if (argv[i] === '--output' && i + 1 < argv.length) args.output = argv[++i];
    if (argv[i] === '--input' && i + 1 < argv.length) args.input = argv[++i];
    if (argv[i] === '--output-dir' && i + 1 < argv.length) args.outputDir = argv[++i];
  }
  return args;
}

function startHTTPServer() {
  // Serve the api_test directory so index.html and relative paths work
  const root = path.dirname(HTML_FILE);
  const server = http.createServer((req, res) => {
    let filePath = path.join(root, req.url === '/' ? 'index.html' : req.url.split('?')[0]);
    try {
      const content = fs.readFileSync(filePath);
      const ext = path.extname(filePath).toLowerCase();
      const mime = { '.html':'text/html','.js':'application/javascript','.json':'application/json',
                     '.jpg':'image/jpeg','.png':'image/png','.css':'text/css' };
      res.writeHead(200, { 'Content-Type': mime[ext] || 'application/octet-stream' });
      res.end(content);
    } catch {
      res.writeHead(404);
      res.end('Not found');
    }
  });
  server.listen(HTTP_PORT, '127.0.0.1');
  console.error(`HTTP server on http://127.0.0.1:${HTTP_PORT}`);
  return server;
}

async function main() {
  const args = parseArgs();

  // Start local HTTP server to serve index.html (no file://, no --disable-web-security)
  const httpServer = startHTTPServer();

  // Find Chrome
  const chromePaths = [
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  ];
  let executablePath = chromePaths.find(p => {
    try { return fs.existsSync(p); } catch { return false; }
  });
  if (!executablePath) {
    console.error('Chrome/Edge not found');
    httpServer.close();
    process.exit(1);
  }

  const browser = await puppeteer.launch({
    executablePath,
    headless: 'new',
    args: ['--no-sandbox', '--disable-gpu', '--enable-webgl'],
  });

  const pageUrl = `http://127.0.0.1:${HTTP_PORT}/`;

  try {
    if (args.input) {
      // Batch mode: process a list of panos
      const pending = JSON.parse(fs.readFileSync(args.input, 'utf-8'));
      const outputDir = args.outputDir || './gtpanos_data';
      fs.mkdirSync(outputDir, { recursive: true });

      const page = await browser.newPage();
      page.on('pageerror', err => console.error('PAGE_ERR:', err.message));

      await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      try {
        await page.waitForFunction(() => window.main && window.main.goto, { timeout: 15000 });
      } catch {
        console.error('SDK initialization timeout');
        process.exit(1);
      }

      for (const item of pending) {
        const lng = item.lng, lat = item.lat, panoName = item.panoName;
        console.error(`Processing ${panoName} (${lng}, ${lat})...`);

        await page.evaluate((l, a) => window.main.goto(l, a), lng, lat);

        try {
          await page.waitForFunction(
            () => window._PANODATA && window._PANODATA.gtRanges,
            { timeout: 30000, polling: 1000 }
          );
        } catch {
          console.error(`  Timeout for ${panoName}`);
          continue;
        }

        const panoData = await page.evaluate(() => window._PANODATA);
        if (panoData && panoData.gtRanges) {
          const outPath = path.join(outputDir, `${panoName}.json`);
          fs.writeFileSync(outPath, JSON.stringify(panoData, null, 2));
          console.error(`  -> ${outPath} (${panoData.gtRanges.length} ranges)`);
          console.log(JSON.stringify({ panoName, file: outPath, ranges: panoData.gtRanges.length }));
        }
      }

      await page.close();
    } else if (args.lng && args.lat) {
      // Single pano mode
      const page = await browser.newPage();
      page.on('pageerror', err => console.error('PAGE_ERR:', err.message));

      await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      try {
        await page.waitForFunction(() => window.main && window.main.goto, { timeout: 15000 });
      } catch {
        console.error('SDK initialization timeout');
        process.exit(1);
      }

      console.error(`Navigating to (${args.lng}, ${args.lat}, ${args.z})...`);
      await page.evaluate((lng, lat) => window.main.goto(lng, lat), args.lng, args.lat);

      try {
        await page.waitForFunction(
          () => window._PANODATA && window._PANODATA.gtRanges,
          { timeout: 30000, polling: 1000 }
        );
      } catch {
        console.error('Timeout waiting for _gtRanges');
      }

      const panoData = await page.evaluate(() => window._PANODATA || null);
      await page.close();

      if (panoData && panoData.gtRanges) {
        const output = JSON.stringify(panoData, null, 2);
        if (args.output) {
          fs.writeFileSync(args.output, output);
          console.error(`Saved to ${args.output}`);
        }
        console.log(output);
      } else {
        console.error('Failed to extract _gtRanges');
        process.exit(1);
      }
    } else {
      console.error('Usage: node extract_gtpanos.js --lng X --lat Y [--z Z] [--output FILE]');
      console.error('   or: node extract_gtpanos.js --input gtpanos_pending.json [--output-dir DIR]');
      process.exit(1);
    }
  } finally {
    await browser.close();
    httpServer.close();
  }
}

main().catch(err => {
  console.error('FATAL:', err.message);
  process.exit(1);
});
