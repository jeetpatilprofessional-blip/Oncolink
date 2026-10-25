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
const PORT = 9223;
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
          if (msg.error) rej(new Error(msg.error.message));
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

  async eval(expression) {
    const res = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    return res.result ? res.result.value : undefined;
  }

  async setViewport(width, height) {
    await this.send("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: width < 600,
    });
    await this.send("Emulation.setVisibleSize", { width, height });
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

  close() {
    if (this.ws) this.ws.close();
  }
}

async function waitForSelector(session, selector, timeoutMs = 10000) {
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
    await sleep(500);
    await session.captureScreenshot(`${baseName}-${width}px.png`);
  }
}

async function main() {
  const tempProfileDir = path.join(__dirname, "..", ".tmp_chrome_screening");
  const chromeProc = spawn(
    CHROME_PATH,
    [
      `--remote-debugging-port=${PORT}`,
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--disable-extensions",
      "--disable-dev-shm-usage",
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--user-data-dir=${tempProfileDir}`,
      "about:blank",
    ],
    { stdio: "ignore" }
  );

  let createdPatientId = null;
  let createdCaseId = null;

  try {
    console.log("Starting Chrome on port " + PORT + "...");
    const browserWs = await waitForChrome();
    console.log("Connected to browser debugging at " + browserWs);

    const targets = await fetchJson(`http://127.0.0.1:${PORT}/json/list`);
    const pageTarget = targets.find((t) => t.type === "page") || targets[0];
    const session = new CdpSession(pageTarget.webSocketDebuggerUrl);
    await session.connect();
    await session.send("Page.enable");
    await session.send("Runtime.enable");
    await session.send("Network.enable");

    session.ws.on("message", (raw) => {
      const msg = JSON.parse(raw);
      if (msg.method === "Runtime.exceptionThrown") {
        console.error("PAGE JS EXCEPTION:", JSON.stringify(msg.params.exceptionDetails));
      }
      if (msg.method === "Log.entryAdded") {
        console.log("CONSOLE LOG:", msg.params.entry.text);
      }
    });

    // ==========================================
    // 1. Patient Home Screen
    // ==========================================
    console.log("\n[1] Capturing Patient Home...");
    await session.clearStorage();
    await loginAs(
      session,
      getRequiredEnv("DEMO_PATIENT_EMAIL"),
      getRequiredEnv("DEMO_PATIENT_PASSWORD")
    );
    await waitForSelector(session, "nav");
    await waitForSelector(session, "main");
    await sleep(500);
    await captureScreenAtBothSizes(session, "patient-home");

    // ==========================================
    // 2. Screener Home Screen
    // ==========================================
    console.log("\n[2] Capturing Screener Home...");
    await session.clearStorage();
    await loginAs(
      session,
      getRequiredEnv("DEMO_SCREENER_EMAIL"),
      getRequiredEnv("DEMO_SCREENER_PASSWORD")
    );
    await waitForSelector(session, "nav");
    await waitForSelector(session, "main");
    await sleep(500);
    await captureScreenAtBothSizes(session, "screener-home");

    // ==========================================
    // 3. Screener New Person Intake Screen
    // ==========================================
    console.log("\n[3] Capturing Screener New Person Intake...");
    await session.eval(`
      (() => {
        const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('Screen a new person'));
        if (btn) btn.click();
      })()
    `);
    await waitForSelector(session, 'input[type="date"]', 10000);
    await sleep(500);
    await captureScreenAtBothSizes(session, "screener-new-person");

    // Fill new person form and advance to consent
    console.log("Advancing to in-person consent agreement...");
    await session.eval(`
      (() => {
        const setVal = (el, val) => {
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
          setter.call(el, val);
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        };
        const dob = document.getElementById("patient-dob");
        if (dob) setVal(dob, "1990-04-18");
        const contact = document.getElementById("patient-contact");
        if (contact) setVal(contact, "Demo-Screener-Visual-01");
        const submitBtn = document.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.click();
      })()
    `);

    // Wait for step 2 (consent)
    await waitForSelector(session, "#in-person-consent-agreed", 10000);
    await sleep(500);

    // Agree to consent and create case
    console.log("Submitting in-person consent and creating case...");
    await session.eval(`
      (() => {
        const chk = document.getElementById("in-person-consent-agreed");
        if (chk && !chk.checked) {
          chk.click();
        }
      })()
    `);
    await sleep(400);

    await session.eval(`
      (() => {
        const submitBtn = document.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.click();
      })()
    `);

    // Wait for navigation to /cases/:id/capture
    await waitForSelector(session, "svg", 12000);
    const captureUrl = await session.eval(`window.location.href`);
    console.log(`Navigated to capture flow: ${captureUrl}`);
    const match = captureUrl.match(/\/cases\/([a-zA-Z0-9_-]+)\/capture/);
    if (match) {
      createdCaseId = match[1];
      console.log(`Detected created case ID: ${createdCaseId}`);
    }

    // ==========================================
    // 4. Capture Flow with OralSiteMap & Framing
    // ==========================================
    console.log("\n[4] Capturing Capture Flow (OralSiteMap & Camera Viewport)...");
    await sleep(1500); // Allow camera live feed / indicators loop to run
    await captureScreenAtBothSizes(session, "capture-flow");

    // ==========================================
    // 5. Questionnaire Form with Emergency Banner
    // ==========================================
    console.log("\n[5] Capturing Questionnaire Form...");
    await session.eval(`
      (() => {
        const link = document.querySelector('a[href*="/history"]');
        if (link) link.click();
      })()
    `);
    await waitForSelector(session, "#alcohol_frequency", 10000);

    // Trigger one of the red-flag checkboxes to show the emergency banner!
    await session.eval(`
      (() => {
        const chk = document.querySelector('input[name="rapid_swelling"]');
        if (chk) {
          chk.click();
        }
      })()
    `);
    await sleep(600);
    await captureScreenAtBothSizes(session, "questionnaire");

    // ==========================================
    // 6. Review & Submit Screen
    // ==========================================
    console.log("\n[6] Capturing Review & Submit Preconditions Checklist...");
    await session.eval(`
      (() => {
        const link = document.querySelector('a[href*="/review"]');
        if (link) link.click();
      })()
    `);
    await waitForSelector(session, "ul", 10000);
    await sleep(800);
    await captureScreenAtBothSizes(session, "review-submit");

    session.close();
    console.log("\nScreening screenshots captured successfully!");
  } finally {
    chromeProc.kill("SIGKILL");
    console.log("Chrome stopped.");

    // Clean up temporary profile
    try {
      fs.rmSync(tempProfileDir, { recursive: true, force: true });
    } catch {
      // ignore
    }

    // Clean up database if a case was created
    if (createdCaseId) {
      try {
        console.log(`Cleaning up test case ${createdCaseId} from MongoDB...`);
        const pyClean = [
          "import asyncio",
          "from bson import ObjectId",
          "import motor.motor_asyncio",
          "from app.config import get_settings",
          "async def clean():",
          "    settings = get_settings()",
          "    client = motor.motor_asyncio.AsyncIOMotorClient(settings.mongo_uri)",
          "    db = client[settings.mongo_db_name]",
          `    case = await db['cases'].find_one({'_id': ObjectId('${createdCaseId}')})`,
          "    if case and 'patient_id' in case:",
          "        pid = str(case['patient_id'])",
          "        await db['consents'].delete_many({'patient_id': pid})",
          "        await db['patients'].delete_one({'_id': ObjectId(pid)})",
          `    await db['cases'].delete_one({'_id': ObjectId('${createdCaseId}')})`,
          `    await db['case_history'].delete_many({'case_id': '${createdCaseId}'})`,
          `    await db['images'].delete_many({'case_id': '${createdCaseId}'})`,
          "    print('Cleaned up visual test case successfully.')",
          "asyncio.run(clean())",
        ].join("\n");

        const cmd = "docker compose -f C:/OncoLink/docker-compose.yml exec -T backend python";
        execSync(cmd, { input: pyClean, encoding: "utf8", stdio: ["pipe", "inherit", "inherit"] });
      } catch (e) {
        console.error("Cleanup error:", e);
      }
    }
  }
}

main().catch((err) => {
  console.error("Error capturing screening screenshots:", err);
  process.exit(1);
});
