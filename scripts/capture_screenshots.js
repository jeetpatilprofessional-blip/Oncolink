const { spawn, execSync } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");
const WebSocket = require("C:/OncoLink/frontend/node_modules/ws");

// Load environment variables from .env if present
const envPath = path.join(__dirname, "..", ".env");
if (fs.existsSync(envPath)) {
  const envContent = fs.readFileSync(envPath, "utf8");
  for (const line of envContent.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eqIdx = trimmed.indexOf("=");
    if (eqIdx !== -1) {
      const key = trimmed.slice(0, eqIdx).trim();
      let val = trimmed.slice(eqIdx + 1).trim();
      if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      if (!process.env[key]) {
        process.env[key] = val;
      }
    }
  }
}

function getRequiredEnv(key) {
  const val = process.env[key];
  if (!val) {
    throw new Error(`Required environment variable ${key} is missing.`);
  }
  return val;
}

const CHROME_PATH = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9222;
const OUT_DIR = "C:\\OncoLink\\docs\\screenshots";

if (!fs.existsSync(OUT_DIR)) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
}

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

function getTotpCode(secret) {
  // Use pyotp via python in docker or host python
  try {
    const cmd = `docker compose exec -T backend python -c "import pyotp; print(pyotp.TOTP('${secret}').now())"`;
    const out = execSync(cmd, { encoding: "utf8" });
    return out.trim();
  } catch (e) {
    console.error("Error generating TOTP:", e);
    throw e;
  }
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

  async eval(expression) {
    const res = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (res.exceptionDetails) {
      throw new Error(`Eval error: ${JSON.stringify(res.exceptionDetails)}`);
    }
    return res.result ? res.result.value : undefined;
  }

  async setViewport(width, height) {
    await this.send("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: width === 360,
    });
  }

  async captureScreenshot(filename) {
    const { data } = await this.send("Page.captureScreenshot", { format: "png" });
    const filePath = path.join(OUT_DIR, filename);
    fs.writeFileSync(filePath, Buffer.from(data, "base64"));
    console.log(`Saved screenshot: ${filePath} (${fs.statSync(filePath).size} bytes)`);
  }

  async clearStorage() {
    await this.send("Network.clearBrowserCookies");
    try {
      await this.send("Storage.clearDataForOrigin", {
        origin: "http://127.0.0.1:5173",
        storageTypes: "all",
      });
    } catch {
      // ignore
    }
  }
}

async function waitForReact(session, timeoutMs = 8000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const len = await session.eval(
      "document.getElementById('root') ? document.getElementById('root').innerHTML.length : 0"
    );
    if (len > 50) return true;
    await sleep(200);
  }
  return false;
}

async function waitForSelector(session, selector, timeoutMs = 8000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const found = await session.eval(`!!document.querySelector(${JSON.stringify(selector)})`);
    if (found) return true;
    await sleep(200);
  }
  const url = await session.eval(`window.location.href`);
  const bodyText = await session.eval(`document.body.innerText`);
  throw new Error(`Timeout waiting for selector: ${selector} at ${url}. Body text: ${bodyText.slice(0, 300)}`);
}

async function loginAs(session, email, password) {
  await session.send("Page.navigate", { url: "http://127.0.0.1:5173/login" });
  await waitForSelector(session, 'input[type="email"]');
  await session.eval(`
    (() => {
      const setInput = (input, val) => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        setter.call(input, val);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      };
      const emailInput = document.querySelector('input[type="email"]');
      const pwdInput = document.querySelector('input[type="password"]');
      setInput(emailInput, ${JSON.stringify(email)});
      setInput(pwdInput, ${JSON.stringify(password)});
      const submitBtn = Array.from(document.querySelectorAll('button')).find(b => b.type === 'submit');
      if (submitBtn) submitBtn.click();
    })()
  `);
  await sleep(1500);
}

async function captureScreenAtBothSizes(session, baseName) {
  for (const width of [360, 1280]) {
    const height = width === 360 ? 800 : 900;
    await session.setViewport(width, height);
    await sleep(400);
    await session.captureScreenshot(`${baseName}-${width}px.png`);
  }
}

async function complete2FaEnrollment(session) {
  // Extract secret from page (.font-mono element)
  await waitForSelector(session, ".font-mono");
  const secret = await session.eval(`document.querySelector(".font-mono").textContent.trim()`);
  console.log(`Extracted TOTP secret for setup: ${secret}`);

  const totpCode = getTotpCode(secret);
  console.log(`Calculated TOTP code: ${totpCode}`);

  await session.eval(`
    (() => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      const codeInput = document.querySelector('input[type="text"]');
      setter.call(codeInput, ${JSON.stringify(totpCode)});
      codeInput.dispatchEvent(new Event("input", { bubbles: true }));
      codeInput.dispatchEvent(new Event("change", { bubbles: true }));
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Verify'));
      if (btn) btn.click();
    })()
  `);

  await sleep(1500);

  // Check confirmation checkbox
  await waitForSelector(session, "#recovery-confirmed");
  await sleep(500);
  await session.eval(`
    (() => {
      const cb = document.getElementById('recovery-confirmed');
      if (cb && !cb.checked) {
        cb.click();
      }
    })()
  `);
  await sleep(500);
  await session.eval(`
    (() => {
      const finishBtn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Continue'));
      if (finishBtn) finishBtn.click();
    })()
  `);
  await sleep(1500);
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
    await pageSession.send("Network.enable");

    pageSession.ws.on("message", (raw) => {
      const msg = JSON.parse(raw);
      if (msg.method === "Network.requestWillBeSent") {
        const { url, method } = msg.params.request;
        if (url.includes("/auth/") || url.includes(":8000")) {
          const frames = msg.params.initiator?.stack?.callFrames || [];
          console.log(`[REQ ${method}] ${url}`, frames.slice(0, 3).map(f => `${f.url}:${f.lineNumber}:${f.functionName}`));
        }
      }
      if (msg.method === "Network.responseReceived") {
        const { url, status, statusText } = msg.params.response;
        if (url.includes("/auth/") || url.includes(":8000") || status >= 400) {
          console.log(`[HTTP ${status} ${statusText}] ${url}`);
        }
      }
    });

    // 1. Public Screens: Login, Register, Forbidden
    console.log("\n--- Capturing Public Screens ---");
    await pageSession.clearStorage();
    await pageSession.send("Page.navigate", { url: "http://127.0.0.1:5173/login" });
    await waitForReact(pageSession);
    await captureScreenAtBothSizes(pageSession, "login");

    await pageSession.send("Page.navigate", { url: "http://127.0.0.1:5173/register" });
    await waitForReact(pageSession);
    await captureScreenAtBothSizes(pageSession, "register");

    await pageSession.send("Page.navigate", { url: "http://127.0.0.1:5173/forbidden" });
    await waitForReact(pageSession);
    await captureScreenAtBothSizes(pageSession, "forbidden");

    // 2. Patient Screen
    console.log("\n--- Logging in as Patient ---");
    await pageSession.clearStorage();
    await loginAs(
      pageSession,
      getRequiredEnv("DEMO_PATIENT_EMAIL"),
      getRequiredEnv("DEMO_PATIENT_PASSWORD")
    );
    await waitForSelector(pageSession, "nav");
    await captureScreenAtBothSizes(pageSession, "patient-home");

    // 3. Screener Screen
    console.log("\n--- Logging in as Screener ---");
    await pageSession.clearStorage();
    await loginAs(
      pageSession,
      getRequiredEnv("DEMO_SCREENER_EMAIL"),
      getRequiredEnv("DEMO_SCREENER_PASSWORD")
    );
    await waitForSelector(pageSession, "nav");
    await captureScreenAtBothSizes(pageSession, "screener-home");

    // 4. Coordinator Screen
    console.log("\n--- Logging in as Hospital Coordinator ---");
    await pageSession.clearStorage();
    await loginAs(
      pageSession,
      getRequiredEnv("DEMO_HOSPITAL_COORDINATOR_EMAIL"),
      getRequiredEnv("DEMO_HOSPITAL_COORDINATOR_PASSWORD")
    );
    await waitForSelector(pageSession, "nav");
    await captureScreenAtBothSizes(pageSession, "coordinator-home");

    // 5. 2FA Setup Screen & Doctor Home
    console.log("\n--- Logging in as Doctor (Unenrolled -> 2FA Setup) ---");
    await pageSession.clearStorage();
    await loginAs(
      pageSession,
      getRequiredEnv("DEMO_DOCTOR_EMAIL"),
      getRequiredEnv("DEMO_DOCTOR_PASSWORD")
    );
    await waitForSelector(pageSession, "svg"); // QR code svg
    console.log("Capturing real 2FA setup screen...");
    await captureScreenAtBothSizes(pageSession, "2fa-setup");

    console.log("Completing 2FA enrollment for Doctor...");
    await complete2FaEnrollment(pageSession);
    await waitForSelector(pageSession, "nav");
    console.log("Capturing Doctor Home...");
    await captureScreenAtBothSizes(pageSession, "doctor-home");

    // 6. Admin Screen
    console.log("\n--- Logging in as Admin (Unenrolled -> 2FA Setup -> Admin Dashboard) ---");
    await pageSession.clearStorage();
    await loginAs(
      pageSession,
      getRequiredEnv("DEMO_ADMIN_EMAIL"),
      getRequiredEnv("DEMO_ADMIN_PASSWORD")
    );
    await waitForSelector(pageSession, "svg");
    console.log("Completing 2FA enrollment for Admin...");
    await complete2FaEnrollment(pageSession);
    await waitForSelector(pageSession, "table");
    console.log("Capturing Admin Console with live MongoDB user table...");
    await captureScreenAtBothSizes(pageSession, "admin");

    pageSession.close();
    console.log("\nAll real screenshots captured successfully!");
  } finally {
    chromeProc.kill("SIGKILL");
    console.log("Chrome stopped.");
  }
}

main().catch((err) => {
  console.error("Error capturing real screenshots:", err);
  process.exit(1);
});
