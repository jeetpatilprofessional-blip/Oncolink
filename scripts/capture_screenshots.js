const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");
const WebSocket = require("C:/OncoLink/frontend/node_modules/ws");

const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9222;
const OUT_DIR = "C:\\OncoLink\\docs\\screenshots";

if (!fs.existsSync(OUT_DIR)) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
}

const SCREENS = [
  { name: "login", path: "/login" },
  { name: "register", path: "/register" },
  { name: "forbidden", path: "/forbidden" },
  { name: "2fa-setup", path: "/dev/2fa" },
  { name: "admin", path: "/dev/admin" },
  { name: "patient-home", path: "/dev/patient" },
  { name: "screener-home", path: "/dev/screener" },
  { name: "doctor-home", path: "/dev/doctor" },
  { name: "coordinator-home", path: "/dev/coordinator" },
];

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => {
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            reject(e);
          }
        });
      })
      .on("error", reject);
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function waitForChrome() {
  for (let i = 0; i < 30; i++) {
    try {
      const version = await fetchJson(`http://127.0.0.1:${PORT}/json/version`);
      return version.webSocketDebuggerUrl;
    } catch {
      await sleep(200);
    }
  }
  throw new Error("Chrome did not start in time");
}

class CdpSession {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.id = 1;
    this.callbacks = new Map();
  }

  connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.on("open", resolve);
      this.ws.on("error", reject);
      this.ws.on("message", (raw) => {
        const msg = JSON.parse(raw);
        if (msg.id && this.callbacks.has(msg.id)) {
          const { res, rej } = this.callbacks.get(msg.id);
          this.callbacks.delete(msg.id);
          if (msg.error) rej(msg.error);
          else res(msg.result);
        }
      });
    });
  }

  send(method, params = {}) {
    return new Promise((res, rej) => {
      const id = this.id++;
      this.callbacks.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    if (this.ws) {
      this.ws.close();
    }
  }
}

async function waitForReact(session, timeoutMs = 8000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const res = await session.send("Runtime.evaluate", {
      expression: "document.getElementById('root') ? document.getElementById('root').innerHTML.length : 0",
      returnByValue: true,
    });
    const len = res.result && res.result.value ? res.result.value : 0;
    if (len > 50) {
      return true;
    }
    await sleep(200);
  }
  return false;
}

async function main() {
  console.log("Starting headless Chrome with remote debugging...");
  const chromeProc = spawn(CHROME_PATH, [
    "--headless=new",
    "--disable-gpu",
    "--no-sandbox",
    `--remote-debugging-port=${PORT}`,
    "about:blank",
  ]);

  try {
    await waitForChrome();
    console.log("Chrome debugger available on port", PORT);

    const targets = await fetchJson(`http://127.0.0.1:${PORT}/json/list`);
    const pageTarget = targets.find((t) => t.type === "page") || targets[0];
    const pageSession = new CdpSession(pageTarget.webSocketDebuggerUrl);
    await pageSession.connect();

    await pageSession.send("Page.enable");
    await pageSession.send("DOM.enable");
    await pageSession.send("Runtime.enable");

    for (const screen of SCREENS) {
      for (const width of [360, 1280]) {
        const height = width === 360 ? 800 : 900;
        console.log(`Capturing ${screen.name} at ${width}px...`);

        await pageSession.send("Emulation.setDeviceMetricsOverride", {
          width,
          height,
          deviceScaleFactor: 1,
          mobile: width === 360,
        });

        const targetUrl = `http://127.0.0.1:5173${screen.path}`;
        await pageSession.send("Page.navigate", { url: targetUrl });

        const ready = await waitForReact(pageSession);
        if (!ready) {
          console.warn(`Warning: React did not report content for ${screen.name} within timeout`);
        }
        // Small extra pause for SVG / fonts / animations
        await sleep(500);

        const { data } = await pageSession.send("Page.captureScreenshot", {
          format: "png",
        });

        const filePath = path.join(OUT_DIR, `${screen.name}-${width}px.png`);
        fs.writeFileSync(filePath, Buffer.from(data, "base64"));
        console.log(`Saved: ${filePath} (${fs.statSync(filePath).size} bytes)`);
      }
    }

    pageSession.close();
  } finally {
    chromeProc.kill("SIGKILL");
    console.log("Chrome stopped.");
  }
}

main().catch((err) => {
  console.error("Error capturing screenshots:", err);
  process.exit(1);
});
