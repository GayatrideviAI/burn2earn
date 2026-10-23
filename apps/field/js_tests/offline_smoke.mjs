// Runs the offline app in a real browser against a small fake server, with the network
// switched off part-way. Needs Playwright and Chromium:
//   NODE_PATH=<global node_modules> node apps/field/js_tests/offline_smoke.mjs
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const here = path.dirname(fileURLToPath(import.meta.url));
const fieldDir = path.join(here, "..");

const received = [];
const photoUploads = [];
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
const saved = new Map();
const snapshot = {
  server_time: new Date().toISOString(),
  mitra: { code: "M1", name: "Test Mitra" },
  grid: { code: "GRID-1" },
  villages: [{ id: "11111111-1111-4111-8111-111111111111", name: "Khera" }],
  biomass_types: [{ id: "22222222-2222-4222-8222-222222222222", name: "Paddy straw" }],
  crops: [{ id: "33333333-3333-4333-8333-333333333333", name: "Paddy" }],
  seasons: [{ id: "44444444-4444-4444-8444-444444444444", name: "Kharif" }],
  products: [{ id: "55555555-5555-4555-8555-555555555555", name: "Paddy pellets (A)" }],
  farmers: [],
};

function template(file, extra = {}) {
  let text = fs.readFileSync(path.join(fieldDir, "templates/field", file), "utf8");
  text = text
    .replace(/{% load static( i18n)? %}/g, "")
    .replace("{% get_current_language as LANGUAGE_CODE %}", "")
    .replace(/{{ LANGUAGE_CODE }}/g, "en")
    .replace("{{ catalog_json|safe }}", JSON.stringify({ hi: { "Farmers": "किसान", "Hello, %(name)s": "नमस्ते, %(name)s" } }))
    .replace(/{% static '([^']+)' %}/g, "/static/$1")
    .replace("{% url 'field:api_photos' %}", "/mitra/api/photos/")
    .replace("{% url 'field:app' %}", "/mitra/app/")
    .replace("{% url 'field:manifest' %}", "/mitra/manifest.webmanifest")
    .replace("{% url 'field:api_bootstrap' %}", "/mitra/api/bootstrap/")
    .replace("{% url 'field:api_sync' %}", "/mitra/api/sync/")
    .replace("{% url 'field:service_worker' %}", "/mitra/sw.js")
    .replace("{% url 'field:login' %}", "/mitra/login/")
    .replace("{% url 'field:dashboard' %}", "/mitra/");
  return text;
}

const server = http.createServer((req, res) => {
  const url = req.url.split("?")[0];
  const send = (type, body, headers = {}) => { res.writeHead(200, { "Content-Type": type, ...headers }); res.end(body); };
  if (url === "/mitra/app/") return send("text/html", template("app.html"));
  if (url === "/mitra/sw.js") return send("text/javascript", template("sw.js"), { "Service-Worker-Allowed": "/mitra/" });
  if (url === "/mitra/manifest.webmanifest") return send("application/manifest+json", template("manifest.webmanifest"));
  if (url.startsWith("/static/")) {
    const rel = url.replace("/static/", "");
    const file = rel.startsWith("weightphotos/") ? path.join(fieldDir, "..", "weightphotos/static", rel) : path.join(fieldDir, "static", rel);
    const type = file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "image/svg+xml";
    return send(type, fs.readFileSync(file));
  }
  if (url === "/mitra/api/bootstrap/") {
    return send("application/json", JSON.stringify({ ...snapshot, farmers: [...saved.values()].filter((o) => o.type === "farmer.create").map((o) => ({
      id: o.id, code: "FRM-" + o.id.slice(0, 4), name: o.data.name, mobile: o.data.mobile, village_id: o.data.village_id, village: "Khera", plots: [],
    })) }));
  }
  if (url === "/mitra/api/photos/" && req.method === "POST") {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => { photoUploads.push(Buffer.concat(chunks).toString("latin1")); send("application/json", JSON.stringify({ status: "ok", message: "" })); });
    return;
  }
  if (url === "/mitra/api/sync/" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const ops = JSON.parse(body).operations;
      const results = ops.map((op) => {
        received.push(op);
        if (saved.has(op.id)) return { id: op.id, status: "exists", message: "" };
        if (op.data.name === "BAD") return { id: op.id, status: "error", message: "Name: not allowed" };
        saved.set(op.id, op);
        if (op.type === "farmer.create" && [...saved.values()].filter((o) => o.type === "farmer.create" && o.data.mobile === op.data.mobile).length > 1)
          return { id: op.id, status: "flagged", message: "Another farmer has this mobile number" };
        return { id: op.id, status: "ok", message: "" };
      });
      send("application/json", JSON.stringify({ results }));
    });
    return;
  }
  res.writeHead(404); res.end();
});

let failures = 0;
function check(name, condition, detail = "") {
  console.log((condition ? "PASS " : "FAIL ") + name + (condition ? "" : "  " + detail));
  if (!condition) failures++;
}

await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch();
const context = await browser.newContext({ serviceWorkers: "allow" });
const page = await context.newPage();
page.on("pageerror", (e) => { console.log("PAGE ERROR", e.message); failures++; });

await page.goto(base + "/mitra/app/");
await page.waitForSelector("text=Hello, Test Mitra");
check("home loads online with downloaded data", true);
await page.evaluate(() => navigator.serviceWorker.ready);
await page.waitForTimeout(500);

await context.setOffline(true);
await page.reload();
await page.waitForSelector("text=Hello, Test Mitra", { timeout: 5000 }).catch(() => {});
check("app reopens with no network (service worker + saved data)", await page.locator("text=Hello, Test Mitra").count() > 0);
check("shows Offline", (await page.locator("#net").textContent()).startsWith("Offline"));

// register a farmer offline
await page.click("text=Register a farmer");
await page.fill("#f_name", "Ramesh <b>Kumar</b>");
await page.fill("#f_mobile", "98765 43210");
await page.selectOption("#f_village_id", { label: "Khera" });
await page.click("button:has-text('Save farmer')");
check("consent is required", await page.locator("text=Consent is needed").count() > 0);
await page.check("#f_consent");
await page.click("button:has-text('Save farmer')");
await page.waitForSelector("h1:has-text('Ramesh')");
check("farmer saved offline and shown", (await page.locator("h1").textContent()).includes("Ramesh <b>Kumar</b>"));
check("names are shown as text, never as HTML", await page.locator("h1 b").count() === 0);
check("marked waiting to send", await page.locator("text=waiting to send").count() > 0);

// plot, crop, pickup
await page.click("text=Add a plot");
await page.fill("#f_latitude", "76");
await page.fill("#f_longitude", "30");
await page.fill("#f_area_acres", "2.5");
await page.click("button:has-text('Save plot')");
check("swapped coordinates rejected", await page.locator("text=Latitude should be between").count() > 0);
await page.fill("#f_latitude", "30.1");
await page.fill("#f_longitude", "76.2");
await page.click("button:has-text('Save plot')");
await page.waitForSelector("text=2.5 acres");
await page.click("text=Add crop");
await page.selectOption("#f_season_id", { label: "Kharif" });
await page.selectOption("#f_crop_id", { label: "Paddy" });
await page.click("button:has-text('Save crop')");
await page.waitForSelector("text=Kharif");
await page.click("text=Log a pickup");
await page.selectOption("#f_biomass_type_id", { label: "Paddy straw" });
await page.fill("#f_quantity_tonnes", "2.5");
await page.fill("#f_price_paid", "3750");
await page.click("button:has-text('Save pickup')");
await page.waitForFunction(() => document.getElementById("net").textContent.includes("4 waiting"), null, { timeout: 5000 }).catch(() => {});
check("four changes waiting offline", (await page.locator("#net").textContent()).includes("4 waiting"), await page.locator("#net").textContent());

// come back online
await context.setOffline(false);
await page.waitForFunction(() => document.getElementById("net").textContent.startsWith("Online") && !document.getElementById("net").textContent.includes("waiting"), null, { timeout: 10000 }).catch(() => {});
check("changes sent automatically when the network returns", (await page.locator("#net").textContent()) === "Online", await page.locator("#net").textContent());
check("server received 4 changes in order", received.map((o) => o.type).join() === "farmer.create,plot.create,season.create,collection.create", received.map((o) => o.type).join());
check("plot refers to the farmer's phone-made id", received[1].data.farmer_id === received[0].id);

// sending the same change again does not duplicate
const again = await page.evaluate(async (op) => {
  const r = await fetch("/mitra/api/sync/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operations: [op] }) });
  return (await r.json()).results[0].status;
}, received[0]);
check("a change sent twice is recognised", again === "exists", again);

// a rejected change stays visible with its reason
await context.setOffline(true);
await page.goto(base + "/mitra/app/#/farmer/new");
await page.fill("#f_name", "BAD");
await page.fill("#f_mobile", "9811111111");
await page.selectOption("#f_village_id", { label: "Khera" });
await page.check("#f_consent");
await page.click("button:has-text('Save farmer')");
await page.waitForSelector("h1:has-text('BAD')");
await context.setOffline(false);
await page.goto(base + "/mitra/app/#/sync");
await page.waitForSelector("text=Name: not allowed", { timeout: 10000 }).catch(() => {});
check("a rejected change shows its reason", await page.locator("text=Name: not allowed").count() > 0);
check("it can be discarded", await page.locator("button:has-text('Discard')").count() > 0);
check("sent items appear in history", await page.locator("#history li").count() >= 4);

// a photo of a stack at the Grid, taken with no network, sent later
await context.setOffline(true);
await page.goto(base + "/mitra/app/#/");
await page.click("text=Photograph a stack");
await page.setInputFiles("#f_photo", { name: "shed.png", mimeType: "image/png", buffer: PNG });
await page.fill("#f_place_note", "Grid shed, north wall");
await page.click("button:has-text('Save photo')");
await page.waitForSelector("text=Photo saved on this phone");
check("a photo is saved offline and counted as waiting", (await page.locator("#net").textContent()).includes("1 waiting"), await page.locator("#net").textContent());
await context.setOffline(false);
await page.waitForFunction(() => { const n = document.getElementById("net").textContent; return n.startsWith("Online") && !n.includes("waiting"); }, null, { timeout: 10000 }).catch(() => {});
check("the photo is sent when the network returns", photoUploads.length === 1 && photoUploads[0].includes("Grid shed, north wall") && photoUploads[0].includes('name="subject"'), String(photoUploads.length));

// language: switch to Hindi with no network; phrases with a translation change, others stay English
await context.setOffline(true);
await page.goto(base + "/mitra/app/#/farmers");
await page.click("#langs button[lang=hi]");
check("Hindi heading shows with no network", await page.locator("h1:has-text('किसान')").count() > 0);
check("a phrase with no translation stays English", await page.locator("a:has-text('Register a farmer')").count() > 0);
check("the choice is remembered", (await page.evaluate(() => localStorage.getItem("mitra_lang"))) === "hi");
await page.click("#langs button[lang=en]");
check("English comes back", await page.locator("h1:has-text('Farmers')").count() > 0);
await context.setOffline(false);

await browser.close();
server.close();
console.log(failures ? `\n${failures} check(s) failed` : "\nAll checks passed");
process.exit(failures ? 1 : 0);
