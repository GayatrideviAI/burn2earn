// Runs the offline yard app in a real browser against a small fake server, with the network
// switched off part-way. Needs Playwright and Chromium:
//   NODE_PATH=<global node_modules> node apps/yardops/js_tests/offline_smoke.mjs
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const here = path.dirname(fileURLToPath(import.meta.url));
const yardDir = path.join(here, "..");
const fieldDir = path.join(yardDir, "..", "field");
const photoDir = path.join(yardDir, "..", "weightphotos");
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
const photoUploads = [];
const order = [];

const received = [];
const saved = new Map();
const PILE = "11111111-1111-4111-8111-111111111111";
const BATCH = "22222222-2222-4222-8222-222222222222";
const ALERT = "33333333-3333-4333-8333-333333333333";
const snapshot = {
  server_time: new Date().toISOString(),
  operator: { name: "Gurdeep" },
  thresholds: { warm: 50, watch: 65, act: 70, emergency: 80 },
  count_methods: [{ id: "audit", name: "Audit" }, { id: "estimate", name: "Estimate" }],
  piles: [{
    id: PILE, label: "A-01", yard_id: "y1", yard: "Yard A", length_m: "", width_m: "", height_m: "", cover_type: "",
    assessment: { level: 1, stale: true, reasons: ["No temperature reading has been taken yet."], rise_per_day: null, projection: "" },
    batches: [{ id: BATCH, code: "BAT-0001", book_tonnes: "100.000", received_on: "2026-10-01" }],
    readings: [], last_inspection: null,
  }],
  photos_to_weigh: [{ id: "44444444-4444-4444-8444-444444444444", code: "WPH-000009", subject: "stack", taken_at: new Date().toISOString(), label: "Yard A / A-01" }],
  alerts: [{ id: ALERT, code: "ALR-0001", pile_id: PILE, pile: "A-01", yard: "Yard A", level: 2, reasons: "Temperature is 66 °C", raised_at: new Date().toISOString(), acknowledged: false }],
};

function template(file) {
  const dir = file === "app.css" ? fieldDir : yardDir;
  let text = fs.readFileSync(path.join(yardDir, "templates/yardops", file), "utf8");
  return text
    .replace(/{% load static( i18n)? %}/g, "")
    .replace("{% get_current_language as LANGUAGE_CODE %}", "")
    .replace(/{{ LANGUAGE_CODE }}/g, "en")
    .replace("{{ catalog_json|safe }}", JSON.stringify({ hi: { "Normal": "सामान्य", "Alerts": "चेतावनियाँ", "Hello, %(name)s": "नमस्ते, %(name)s" } }))
    .replace(/{% static '([^']+)' %}/g, "/static/$1")
    .replace("{% url 'yardops:api_photos' %}", "/yard/api/photos/")
    .replace("{% url 'yardops:app' %}", "/yard/app/")
    .replace("{% url 'yardops:manifest' %}", "/yard/manifest.webmanifest")
    .replace("{% url 'yardops:api_bootstrap' %}", "/yard/api/bootstrap/")
    .replace("{% url 'yardops:api_sync' %}", "/yard/api/sync/")
    .replace("{% url 'yardops:service_worker' %}", "/yard/sw.js")
    .replace("{% url 'yardops:login' %}", "/yard/login/")
    .replace("{% url 'yardops:home' %}", "/yard/");
}

const server = http.createServer((req, res) => {
  const url = req.url.split("?")[0];
  const send = (type, body, headers = {}) => { res.writeHead(200, { "Content-Type": type, ...headers }); res.end(body); };
  if (url === "/yard/app/") return send("text/html", template("app.html"));
  if (url === "/yard/sw.js") return send("text/javascript", template("sw.js"), { "Service-Worker-Allowed": "/yard/" });
  if (url === "/yard/manifest.webmanifest") return send("application/manifest+json", template("manifest.webmanifest"));
  if (url.startsWith("/static/")) {
    const rel = url.replace("/static/", "");
    const root = rel.startsWith("yardops/") ? yardDir : rel.startsWith("weightphotos/") ? photoDir : fieldDir;
    const file = path.join(root, "static", rel);
    const type = file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "image/svg+xml";
    return send(type, fs.readFileSync(file));
  }
  if (url === "/yard/api/bootstrap/") {
    const acked = [...saved.values()].some((o) => o.type === "alert.acknowledge");
    const s = JSON.parse(JSON.stringify(snapshot));
    s.alerts[0].acknowledged = acked;
    return send("application/json", JSON.stringify(s));
  }
  if (url === "/yard/api/photos/" && req.method === "POST") {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("latin1");
      photoUploads.push(raw);
      order.push("photo");
      const id = /name="id"\r\n\r\n([^\r]+)/.exec(raw)[1];
      if (raw.includes("BADPHOTO")) return send("application/json", JSON.stringify({ status: "error", message: "This file is not a photo." }));
      send("application/json", JSON.stringify({ status: "ok", message: "", id }));
    });
    return;
  }
  if (url === "/yard/api/sync/" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const results = JSON.parse(body).operations.map((op) => {
        received.push(op);
        if (op.type === "photo.weigh") order.push("weigh");
        if (saved.has(op.id)) return { id: op.id, status: "exists", message: "" };
        if (op.type === "heat.create" && op.data.spot === "BAD") return { id: op.id, status: "error", message: "Spot: not allowed" };
        saved.set(op.id, op);
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

await page.goto(base + "/yard/app/");
await page.waitForSelector("text=Hello, Gurdeep");
check("home loads online with downloaded piles", await page.locator("text=Pile A-01").count() > 0);
check("the open alert is shown", await page.locator("button:has-text('I have seen this')").count() === 1);
await page.evaluate(() => navigator.serviceWorker.ready);
await page.waitForTimeout(500);

await context.setOffline(true);
await page.reload();
await page.waitForSelector("text=Hello, Gurdeep", { timeout: 5000 }).catch(() => {});
check("app reopens with no network", await page.locator("text=Hello, Gurdeep").count() > 0);
check("shows Offline", (await page.locator("#net").textContent()).startsWith("Offline"));

// acknowledge the alert offline
await page.click("button:has-text('I have seen this')");
await page.waitForFunction(() => document.querySelectorAll(".alertbox").length === 0, null, { timeout: 5000 }).catch(() => {});
check("alert disappears once acknowledged on the phone", await page.locator(".alertbox").count() === 0);

// log a hot temperature offline: the level goes up at once with the advice
await page.click("a:has-text('Pile A-01')");
await page.click("text=Log a temperature");
await page.fill("#f_temperature_c", "900");
await page.click("button:has-text('Save temperature')");
check("an impossible temperature is rejected", await page.locator("text=Enter a temperature between").count() > 0);
await page.fill("#f_temperature_c", "72");
await page.fill("#f_spot", "north <b>face</b>");
await page.click("button:has-text('Save temperature')");
await page.waitForSelector("h1:has-text('Pile A-01')");
check("level raised on the phone to 'Check twice a day'", await page.locator(".tag:has-text('Check twice a day')").count() > 0);
check("advice is shown right away", await page.locator("text=open up the stack").count() > 0);
check("says it was raised on this phone", await page.locator("text=Raised on this phone").count() > 0);
check("reading shown, marked waiting", await page.locator("li:has-text('72 °C'):has-text('waiting to send')").count() > 0);
check("spot is shown as text, never as HTML", await page.locator("li b").count() === 0);

// inspection, count, moisture, size
await page.click("text=Log an inspection");
await page.check("#f_looks_wet");
await page.click("button:has-text('Save inspection')");
await page.waitForSelector("h1:has-text('Pile A-01')");
await page.click("text=Count the stock");
await page.fill("#f_tonnes", "98.5");
await page.click("button:has-text('Save count')");
await page.waitForSelector("h1:has-text('Pile A-01')");
await page.click("text=Log a moisture reading");
await page.fill("#f_percent", "130");
await page.click("button:has-text('Save moisture')");
check("moisture above 100 is rejected", await page.locator("text=Enter a moisture between").count() > 0);
await page.fill("#f_percent", "13.5");
await page.click("button:has-text('Save moisture')");
await page.waitForSelector("h1:has-text('Pile A-01')");
await page.click("text=Pile size and cover");
await page.fill("#f_height_m", "5.5");
await page.click("button:has-text('Save pile details')");
await page.waitForSelector("h1:has-text('Pile A-01')");
check("six changes waiting offline", (await page.locator("#net").textContent()).includes("6 waiting"), await page.locator("#net").textContent());

// back online: everything goes up in order
await context.setOffline(false);
await page.waitForFunction(() => { const n = document.getElementById("net").textContent; return n.startsWith("Online") && !n.includes("waiting"); }, null, { timeout: 10000 }).catch(() => {});
check("changes sent automatically when the network returns", (await page.locator("#net").textContent()) === "Online", await page.locator("#net").textContent());
check("server received them in order", received.map((o) => o.type).join() === "alert.acknowledge,heat.create,inspection.create,count.create,moisture.create,size.update", received.map((o) => o.type).join());
check("the temperature carries the phone's time", !!received[1].data.taken_at && new Date(received[1].data.taken_at) <= new Date());
check("the acknowledgement carries the time it was pressed", !!received[0].data.acknowledged_at);

const again = await page.evaluate(async (op) => {
  const r = await fetch("/yard/api/sync/", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operations: [op] }) });
  return (await r.json()).results[0].status;
}, received[1]);
check("a change sent twice is recognised", again === "exists", again);

// a rejected change stays visible with its reason
await context.setOffline(true);
await page.goto(base + "/yard/app/#/heat/" + PILE);
await page.fill("#f_temperature_c", "41");
await page.fill("#f_spot", "BAD");
await page.click("button:has-text('Save temperature')");
await page.waitForSelector("h1:has-text('Pile A-01')");
await context.setOffline(false);
await page.goto(base + "/yard/app/#/sync");
await page.waitForSelector("text=Spot: not allowed", { timeout: 10000 }).catch(() => {});
check("a rejected change shows its reason", await page.locator("text=Spot: not allowed").count() > 0);
check("it can be discarded", await page.locator("button:has-text('Discard')").count() > 0);
check("sent items appear in history", await page.locator("#history li").count() >= 6);

// photos: a loaded vehicle and a stack, taken with no network
await context.setOffline(true);
await page.goto(base + "/yard/app/#/");
await page.click("text=Photograph a loaded vehicle");
await page.click("button:has-text('Save photo')");
check("a photo is needed", await page.locator("text=Take or choose a photo first").count() > 0);
await page.setInputFiles("#f_photo", { name: "truck.png", mimeType: "image/png", buffer: PNG });
await page.click("button:has-text('Save photo')");
check("the vehicle must be chosen", await page.locator("text=Choose the vehicle").count() > 0);
await page.selectOption("#f_vehicle_type", "truck");
await page.fill("#f_vehicle_ref", "HR 26 AB 1234");
await page.fill("#f_weighed_tonnes", "11.25");
await page.fill("#f_slip_number", "S-77");
await page.click("button:has-text('Save photo')");
await page.waitForSelector("text=Photo saved on this phone");
check("load photo saved offline", true);
await page.goto(base + "/yard/app/#/pile/" + PILE);
await page.click("text=Photograph this stack");
await page.setInputFiles("#f_photo", { name: "stack.png", mimeType: "image/png", buffer: PNG });
await page.fill("#f_bale_count", "120");
await page.fill("#f_reference_note", "2 m pole on the left");
await page.click("button:has-text('Save photo')");
await page.waitForSelector("h1:has-text('Pile A-01')");
check("two photos waiting", (await page.locator("#net").textContent()).includes("2 waiting"), await page.locator("#net").textContent());
await page.goto(base + "/yard/app/#/photos");
await page.waitForSelector("#photo-queue li");
check("they are listed as waiting to send", await page.locator("#photo-queue li").count() === 2);
check("the stack photo offers a place to add the weight later", await page.locator("#photo-queue li:has-text('Stack') button:has-text('Save weight')").count() === 1);
check("a sent photo still needing a weight is listed", await page.locator("#photo-weigh li:has-text('WPH') , #photo-weigh li:has-text('Yard A / A-01')").count() === 1);

// online: photos upload first, then the weight for the already-sent photo
await page.fill("#photo-weigh input[name=weighed_tonnes]", "8.5");
await page.click("#photo-weigh button:has-text('Save weight')");
await context.setOffline(false);
await page.waitForFunction(() => { const n = document.getElementById("net").textContent; return n.startsWith("Online") && !n.includes("waiting"); }, null, { timeout: 10000 }).catch(() => {});
check("photos sent when the network returns", photoUploads.length === 2, String(photoUploads.length));
check("the upload carries the details", photoUploads[0].includes("HR 26 AB 1234") && photoUploads[0].includes('name="weighed_tonnes"') && photoUploads[0].includes("S-77"));
check("the second carries bale count and reference note", photoUploads[1].includes("120") && photoUploads[1].includes("2 m pole on the left"));
check("the photo is a JPEG", photoUploads[0].includes("Content-Type: image/jpeg"));
check("the late weight was sent as a change", received.some((o) => o.type === "photo.weigh" && o.data.weighed_tonnes === "8.5"));
check("photos are sent before changes", order.indexOf("weigh") > order.lastIndexOf("photo"), order.join());

// language with no network
await context.setOffline(true);
await page.goto(base + "/yard/app/#/");
await page.click("#langs button[lang=hi]");
check("Hindi shows with no network", await page.locator("h1:has-text('नमस्ते, Gurdeep')").count() > 0);
check("the choice is remembered", (await page.evaluate(() => localStorage.getItem("yard_lang"))) === "hi");
await page.click("#langs button[lang=en]");
check("English comes back", await page.locator("h1:has-text('Hello, Gurdeep')").count() > 0);
await context.setOffline(false);

await browser.close();
server.close();
console.log(failures ? `\n${failures} check(s) failed` : "\nAll checks passed");
process.exit(failures ? 1 : 0);
