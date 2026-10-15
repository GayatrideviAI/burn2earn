/* Offline Mitra app.
 *
 * Everything the Mitra does is saved on the phone first (IndexedDB) as a "change" with an id
 * made on the phone. When there is a signal the changes are sent to the server in order. The
 * server uses the id as the record's id, so a change sent twice is only saved once.
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- small helpers
  function uuid() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function today() {
    var d = new Date();
    var pad = function (n) { return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function byId(list, id) {
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  /** The farmers the Mitra should see: the downloaded list plus anything saved but not yet sent. */
  function applyOps(snapshot, queue) {
    var farmers = JSON.parse(JSON.stringify((snapshot && snapshot.farmers) || []));
    var villages = (snapshot && snapshot.villages) || [];
    var crops = (snapshot && snapshot.crops) || [];
    var seasons = (snapshot && snapshot.seasons) || [];
    queue.slice().sort(function (a, b) { return a.seq - b.seq; }).forEach(function (op) {
      var d = op.data;
      if (op.type === "farmer.create") {
        var village = byId(villages, d.village_id);
        farmers.push({
          id: op.id, code: "Not sent yet", name: d.name, mobile: d.mobile,
          village_id: d.village_id, village: village ? village.name : "", plots: [], pending: true,
        });
      } else if (op.type === "plot.create") {
        var farmer = byId(farmers, d.farmer_id);
        if (farmer) farmer.plots.push({ id: op.id, area_acres: String(d.area_acres), cell: null, seasons: [], pending: true });
      } else if (op.type === "season.create") {
        farmers.forEach(function (f) {
          var plot = byId(f.plots, d.plot_id);
          if (!plot) return;
          var crop = byId(crops, d.crop_id), season = byId(seasons, d.season_id);
          plot.seasons.push({
            id: op.id, season: season ? season.name : "", year: d.year,
            crop: crop ? crop.name : "", variety: d.variety || "", pending: true,
          });
        });
      }
    });
    return farmers;
  }

  /** One line describing a saved change, for the "waiting to send" list. */
  function describe(op, snapshot) {
    var d = op.data, s = snapshot || {};
    var farmer = function (id) {
      var f = byId((s.farmers) || [], id);
      return f ? f.name : "a farmer";
    };
    switch (op.type) {
      case "farmer.create": return "Register farmer " + d.name;
      case "plot.create": return "Add a " + d.area_acres + " acre plot for " + farmer(d.farmer_id);
      case "season.create": return "Add a crop (" + d.year + ")";
      case "collection.create": return "Pickup of " + d.quantity_tonnes + " t from " + farmer(d.farmer_id);
      case "output.create": return "Output of " + d.quantity_tonnes + " t";
      default: return op.type;
    }
  }

  function pendingTotals(queue) {
    var t = { pickups: 0, pickupTonnes: 0, outputs: 0, outputTonnes: 0 };
    queue.forEach(function (op) {
      if (op.type === "collection.create") { t.pickups++; t.pickupTonnes += Number(op.data.quantity_tonnes) || 0; }
      if (op.type === "output.create") { t.outputs++; t.outputTonnes += Number(op.data.quantity_tonnes) || 0; }
    });
    return t;
  }

  var core = { uuid: uuid, applyOps: applyOps, describe: describe, pendingTotals: pendingTotals, today: today };
  if (typeof module !== "undefined" && module.exports) module.exports = core;
  if (typeof window === "undefined" || !window.MITRA) return; // loaded by a test, not a browser page

  // ---------------------------------------------------------------- storage
  var cfg = window.MITRA;
  var dbPromise = new Promise(function (resolve, reject) {
    var request = indexedDB.open("mitra-app", 1);
    request.onupgradeneeded = function () {
      var db = request.result;
      db.createObjectStore("kv");
      db.createObjectStore("queue", { keyPath: "id" });
    };
    request.onsuccess = function () { resolve(request.result); };
    request.onerror = function () { reject(request.error); };
  });

  function tx(store, mode, work) {
    return dbPromise.then(function (db) {
      return new Promise(function (resolve, reject) {
        var t = db.transaction(store, mode);
        var result = work(t.objectStore(store));
        t.oncomplete = function () { resolve(result && result.result !== undefined ? result.result : undefined); };
        t.onerror = function () { reject(t.error); };
      });
    });
  }
  function kvGet(key) { return tx("kv", "readonly", function (s) { return s.get(key); }); }
  function kvSet(key, value) { return tx("kv", "readwrite", function (s) { return s.put(value, key); }); }
  function queueAll() {
    return tx("queue", "readonly", function (s) { return s.getAll(); }).then(function (rows) {
      return (rows || []).sort(function (a, b) { return a.seq - b.seq; });
    });
  }
  function queuePut(op) { return tx("queue", "readwrite", function (s) { return s.put(op); }); }
  function queueDelete(id) { return tx("queue", "readwrite", function (s) { return s.delete(id); }); }

  var counter = 0;
  function addChange(type, data) {
    var op = { id: uuid(), type: type, data: data, seq: Date.now() * 1000 + (counter++ % 1000), saved_at: new Date().toISOString() };
    // The list of waiting changes must be up to date before the screen changes.
    return queuePut(op).then(refreshStatus).then(function () { scheduleSync(); return op; });
  }

  // ---------------------------------------------------------------- state
  var state = { snapshot: null, queue: [], history: [], online: navigator.onLine, syncing: false, needLogin: false };

  function load() {
    return Promise.all([kvGet("snapshot"), queueAll(), kvGet("history")]).then(function (r) {
      state.snapshot = r[0] || null;
      state.queue = r[1];
      state.history = r[2] || [];
    });
  }

  // ---------------------------------------------------------------- talking to the server
  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function fetchJson(url, options) {
    options = options || {};
    options.credentials = "same-origin";
    options.headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    return fetch(url, options).then(function (response) {
      var type = response.headers.get("content-type") || "";
      if (response.status === 401 || response.status === 403 || response.redirected || type.indexOf("json") < 0) {
        state.needLogin = true;
        throw new Error("login");
      }
      if (!response.ok) throw new Error("server " + response.status);
      state.needLogin = false;
      return response.json();
    });
  }

  function downloadData() {
    return fetchJson(cfg.bootstrapUrl).then(function (data) {
      state.snapshot = data;
      return kvSet("snapshot", data);
    });
  }

  function rememberHistory(entries) {
    state.history = entries.concat(state.history).slice(0, 30);
    return kvSet("history", state.history);
  }

  function syncNow() {
    if (state.syncing || !navigator.onLine) return Promise.resolve();
    var waiting = state.queue.filter(function (op) { return !op.error; });
    var before = waiting.length;
    state.syncing = true;
    render();
    var chain = Promise.resolve();
    if (waiting.length) {
      var batch = waiting.slice(0, 50);
      chain = fetchJson(cfg.syncUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ operations: batch.map(function (op) { return { id: op.id, type: op.type, data: op.data }; }) }),
      }).then(function (reply) {
        var entries = [];
        var jobs = reply.results.map(function (result) {
          var op = byId(batch, result.id);
          var text = op ? describe(op, state.snapshot) : result.id;
          if (result.status === "error") {
            if (op) { op.error = result.message; return queuePut(op); }
          } else {
            entries.push({ at: new Date().toISOString(), text: text, status: result.status, message: result.message });
            return queueDelete(result.id);
          }
        });
        return Promise.all(jobs).then(function () { return rememberHistory(entries); });
      });
    }
    return chain
      .then(function () { return downloadData(); })
      .then(function () { return queueAll(); })
      .then(function (rows) { state.queue = rows; })
      .catch(function () { /* no signal or login needed: keep everything on the phone */ })
      .then(function () {
        state.syncing = false;
        refreshStatus();
        render();
        var left = state.queue.filter(function (op) { return !op.error; }).length;
        if (left && left < before && navigator.onLine && !state.needLogin) {
          // progress was made but more than one batch was waiting
          setTimeout(syncNow, 500);
        }
      });
  }

  var syncTimer = null;
  function scheduleSync() {
    clearTimeout(syncTimer);
    syncTimer = setTimeout(syncNow, 300);
  }

  function refreshStatus() {
    return queueAll().then(function (rows) {
      state.queue = rows;
      var net = document.getElementById("net");
      var waiting = rows.filter(function (op) { return !op.error; }).length;
      var errors = rows.length - waiting;
      net.className = "net " + (navigator.onLine ? "on" : "off");
      net.textContent = (navigator.onLine ? "Online" : "Offline") + (waiting ? " · " + waiting + " waiting" : "") + (errors ? " · " + errors + " need attention" : "");
    });
  }

  // ---------------------------------------------------------------- tiny DOM toolkit (text only, never HTML)
  function h(tag, attrs) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") el.className = attrs[k];
      else if (k.indexOf("on") === 0) el.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== false && attrs[k] != null) el.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
    return el;
  }
  function append(el, child) {
    if (child == null || child === false) return;
    if (Array.isArray(child)) child.forEach(function (c) { append(el, c); });
    else el.appendChild(typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child);
  }
  function link(text, href, cls) { return h("a", { href: href, class: cls || "" }, text); }

  function select(name, options, blankLabel, value) {
    var s = h("select", { name: name, id: "f_" + name });
    if (blankLabel != null) s.appendChild(h("option", { value: "" }, blankLabel));
    options.forEach(function (o) {
      var opt = h("option", { value: o.value }, o.label);
      if (value === o.value) opt.selected = true;
      s.appendChild(opt);
    });
    return s;
  }
  function input(name, type, extra) {
    return h("input", Object.assign({ name: name, id: "f_" + name, type: type || "text" }, extra || {}));
  }
  function row(label, control) {
    return h("div", { class: "field" }, h("label", { for: control.id }, label), control);
  }

  /** Build a form. `fields` are the rows; `onSubmit(values)` returns an error string or saves. */
  function form(fields, submitLabel, onSubmit, cancelHref) {
    var error = h("p", { class: "msg error", hidden: true });
    var f = h("form", { novalidate: true });
    var button = h("button", { class: "primary", type: "submit" }, submitLabel);
    f.appendChild(error);
    fields.forEach(function (x) { f.appendChild(x); });
    f.appendChild(button);
    if (cancelHref) f.appendChild(link("Cancel", cancelHref, "button"));
    f.addEventListener("submit", function (e) {
      e.preventDefault();
      var values = {};
      Array.prototype.forEach.call(f.elements, function (el) {
        if (!el.name) return;
        values[el.name] = el.type === "checkbox" ? el.checked : el.value.trim();
      });
      var problem = onSubmit(values);
      if (problem) { error.textContent = problem; error.hidden = false; window.scrollTo(0, 0); }
    });
    return f;
  }

  function optionsOf(list, key) {
    return (list || []).map(function (x) { return { value: x.id, label: x[key || "name"] }; });
  }

  function positive(value) { var n = Number(value); return value !== "" && isFinite(n) && n > 0; }
  function notFuture(value) { return value <= today(); }

  // ---------------------------------------------------------------- screens
  var views = {};

  views.home = function () {
    var totals = pendingTotals(state.queue);
    var farmers = applyOps(state.snapshot, state.queue);
    var plots = farmers.reduce(function (n, f) { return n + f.plots.length; }, 0);
    var waiting = state.queue.filter(function (op) { return !op.error; }).length;
    return [
      h("h1", {}, "Hello, " + (state.snapshot ? state.snapshot.mitra.name : "Mitra")),
      state.snapshot && state.snapshot.grid ? h("p", { class: "muted" }, "Grid " + state.snapshot.grid.code) : null,
      h("div", { class: "stats" },
        h("div", {}, h("strong", {}, farmers.length), h("span", {}, "Farmers")),
        h("div", {}, h("strong", {}, plots), h("span", {}, "Plots")),
        h("div", {}, h("strong", {}, waiting), h("span", {}, "To send"))),
      totals.pickups || totals.outputs
        ? h("p", { class: "muted" }, "Saved on this phone, not sent yet: " + totals.pickups + " pickup(s), " + totals.pickupTonnes.toFixed(2) + " t; " + totals.outputs + " output report(s), " + totals.outputTonnes.toFixed(2) + " t.")
        : null,
      h("p", {}, link("Register a farmer", "#/farmer/new", "button primary"), " ", link("Report output", "#/output", "button")),
      !state.snapshot ? h("p", { class: "msg warning" }, "Connect to the internet once so your farmers and lists can be downloaded.") : null,
      state.needLogin ? h("p", { class: "msg warning" }, ["Please log in again to send your changes. ", h("a", { href: cfg.loginUrl + "?next=" + encodeURIComponent(location.pathname) }, "Log in")]) : null,
      h("p", { class: "muted" }, "Everything you enter is saved on this phone first. It is sent when there is a signal."),
    ];
  };

  views.farmers = function () {
    var q = (state.search || "").toLowerCase();
    var farmers = applyOps(state.snapshot, state.queue).filter(function (f) {
      return !q || (f.name + " " + f.mobile + " " + f.code).toLowerCase().indexOf(q) >= 0;
    });
    var box = h("input", { type: "search", placeholder: "Name, mobile or code", value: state.search || "", id: "q" });
    box.addEventListener("input", function () {
      state.search = box.value;
      var list = document.getElementById("farmer-list");
      var next = views.farmerList();
      list.replaceWith(next);
    });
    return [h("h1", {}, "Farmers"), h("div", { class: "search" }, box), h("p", {}, link("Register a farmer", "#/farmer/new", "button primary")), views.farmerList()];
  };

  views.farmerList = function () {
    var q = (state.search || "").toLowerCase();
    var farmers = applyOps(state.snapshot, state.queue).filter(function (f) {
      return !q || (f.name + " " + f.mobile + " " + f.code).toLowerCase().indexOf(q) >= 0;
    });
    return h("ul", { class: "list", id: "farmer-list" },
      farmers.length
        ? farmers.map(function (f) {
            return h("li", {}, h("a", { href: "#/farmer/" + f.id }, f.name,
              h("small", {}, f.code + " · " + f.village + " · " + f.plots.length + " plot(s)" + (f.pending ? " · waiting to send" : ""))));
          })
        : h("li", { class: "muted" }, "No farmers found."));
  };

  views.farmerNew = function () {
    var snap = state.snapshot;
    if (!snap) return [h("h1", {}, "Register a farmer"), h("p", { class: "msg warning" }, "Connect to the internet once to download the village list.")];
    var consent = h("input", { type: "checkbox", name: "consent", id: "f_consent" });
    return [h("h1", {}, "Register a farmer"), form([
      row("Name", input("name")),
      row("Mobile number", input("mobile", "tel", { inputmode: "tel", autocomplete: "off" })),
      row("Village", select("village_id", optionsOf(snap.villages), "Choose a village")),
      row("Preferred language", select("preferred_language", [{ value: "hi", label: "Hindi" }, { value: "en", label: "English" }, { value: "pa", label: "Punjabi" }, { value: "other", label: "Other" }], "Not stated")),
      h("div", { class: "field" }, consent, h("label", { for: "f_consent", class: "inline" }, "The farmer has been told how their information will be used and agrees.")),
    ], "Save farmer", function (v) {
      if (!v.name) return "Enter the farmer's name.";
      if (!/^\+?\d{10,15}$/.test(v.mobile.replace(/\s/g, ""))) return "Enter a mobile number with 10 to 15 digits.";
      if (!v.village_id) return "Choose the farmer's village.";
      if (!v.consent) return "Consent is needed before a farmer can be registered.";
      var duplicate = applyOps(snap, state.queue).filter(function (f) { return f.mobile === v.mobile.replace(/\s/g, ""); })[0];
      if (duplicate && !state.confirmDuplicate) {
        state.confirmDuplicate = true;
        return duplicate.name + " already has this mobile number. Families often share a phone. Press Save farmer again to register anyway.";
      }
      state.confirmDuplicate = false;
      addChange("farmer.create", {
        name: v.name, mobile: v.mobile.replace(/\s/g, ""), village_id: v.village_id,
        preferred_language: v.preferred_language, consent: true, consented_at: new Date().toISOString(),
      }).then(function (op) { location.hash = "#/farmer/" + op.id; });
    }, "#/farmers")];
  };

  function farmerFor(id) { return byId(applyOps(state.snapshot, state.queue), id); }

  views.farmer = function (id) {
    var f = farmerFor(id);
    if (!f) return [h("p", {}, "Farmer not found."), link("Back", "#/farmers", "button")];
    return [
      h("h1", {}, f.name),
      h("p", { class: "muted" }, f.code + " · " + f.mobile + " · " + f.village + (f.pending ? " · waiting to send" : "")),
      h("p", {}, link("Log a pickup", "#/pickup/" + f.id, "button primary"), " ", link("Add a plot", "#/plot/" + f.id, "button")),
      h("h2", {}, "Land"),
      f.plots.length ? f.plots.map(function (p) {
        return h("section", { class: "card" },
          h("h3", {}, p.area_acres + " acres"),
          h("p", { class: "muted" }, (p.cell ? "GeoCell " + p.cell : p.pending ? "Waiting to send" : "Outside every GeoCell")),
          h("ul", { class: "list" }, p.seasons.length
            ? p.seasons.map(function (s) { return h("li", {}, s.season + " " + s.year + ": " + s.crop + (s.variety ? " (" + s.variety + ")" : "") + (s.pending ? " · waiting to send" : "")); })
            : h("li", { class: "muted" }, "No crops recorded.")),
          link("Add crop", "#/crop/" + f.id + "/" + p.id, "button"));
      }) : h("p", { class: "muted" }, "No land added yet."),
    ];
  };

  views.plot = function (id) {
    var f = farmerFor(id);
    if (!f) return [h("p", {}, "Farmer not found.")];
    var status = h("small", { class: "muted", id: "gps" }, "");
    var lat = input("latitude", "text", { inputmode: "decimal" }), lon = input("longitude", "text", { inputmode: "decimal" });
    var gps = h("button", { type: "button", id: "locate" }, "Use my location");
    gps.addEventListener("click", function () {
      if (!navigator.geolocation) { status.textContent = "Location is not available on this device."; return; }
      status.textContent = "Finding location…";
      navigator.geolocation.getCurrentPosition(function (pos) {
        lat.value = pos.coords.latitude.toFixed(6);
        lon.value = pos.coords.longitude.toFixed(6);
        status.textContent = "Done. Stand at the plot for the best accuracy.";
      }, function () { status.textContent = "Could not get location. Type it in instead."; });
    });
    return [h("h1", {}, "Add a plot for " + f.name), h("p", {}, gps, " ", status), form([
      row("Latitude", lat), row("Longitude", lon),
      row("Area (acres)", input("area_acres", "text", { inputmode: "decimal" })),
      row("Ownership", select("ownership", [{ value: "owned", label: "Owned" }, { value: "leased", label: "Leased" }, { value: "sharecropped", label: "Sharecropped" }], "Not stated")),
      row("Irrigation", select("irrigation", [{ value: "canal", label: "Canal" }, { value: "tubewell", label: "Tubewell" }, { value: "rainfed", label: "Rain-fed" }, { value: "other", label: "Other" }], "Not stated")),
    ], "Save plot", function (v) {
      var la = Number(v.latitude), lo = Number(v.longitude);
      if (v.latitude === "" || !(la >= 6 && la <= 38)) return "Latitude should be between 6 and 38 for India.";
      if (v.longitude === "" || !(lo >= 68 && lo <= 98)) return "Longitude should be between 68 and 98 for India.";
      if (!positive(v.area_acres)) return "Enter the area in acres.";
      addChange("plot.create", { farmer_id: f.id, latitude: v.latitude, longitude: v.longitude, area_acres: v.area_acres, ownership: v.ownership, irrigation: v.irrigation })
        .then(function () { location.hash = "#/farmer/" + f.id; });
    }, "#/farmer/" + f.id)];
  };

  views.crop = function (farmerId, plotId) {
    var f = farmerFor(farmerId), snap = state.snapshot;
    if (!f || !snap) return [h("p", {}, "Not found.")];
    return [h("h1", {}, "Add a crop"), form([
      row("Season", select("season_id", optionsOf(snap.seasons), "Choose")),
      row("Year", input("year", "number", { value: new Date().getFullYear() })),
      row("Crop", select("crop_id", optionsOf(snap.crops), "Choose")),
      row("Variety (optional)", input("variety")),
      row("Sowing date (optional)", input("sowing_date", "date")),
      row("Expected harvest date (optional)", input("expected_harvest_date", "date")),
    ], "Save crop", function (v) {
      if (!v.season_id || !v.crop_id) return "Choose the season and the crop.";
      if (!(Number(v.year) >= 2000 && Number(v.year) <= 2100)) return "Enter a year between 2000 and 2100.";
      if (v.sowing_date && v.expected_harvest_date && v.expected_harvest_date < v.sowing_date) return "The harvest date cannot be before the sowing date.";
      addChange("season.create", { plot_id: plotId, season_id: v.season_id, crop_id: v.crop_id, year: Number(v.year), variety: v.variety, sowing_date: v.sowing_date, expected_harvest_date: v.expected_harvest_date })
        .then(function () { location.hash = "#/farmer/" + f.id; });
    }, "#/farmer/" + f.id)];
  };

  views.pickup = function (id) {
    var f = farmerFor(id), snap = state.snapshot;
    if (!f || !snap) return [h("p", {}, "Not found.")];
    return [h("h1", {}, "Log a pickup from " + f.name), form([
      row("Plot (optional)", select("plot_id", f.plots.map(function (p) { return { value: p.id, label: p.area_acres + " acres" }; }), "Not stated")),
      row("Residue", select("biomass_type_id", optionsOf(snap.biomass_types), "Choose")),
      row("Quantity picked up (tonnes)", input("quantity_tonnes", "text", { inputmode: "decimal" })),
      row("Price paid to the farmer (₹, total)", input("price_paid", "text", { inputmode: "decimal" })),
      row("Date", input("collected_on", "date", { value: today() })),
      row("Notes (optional)", input("notes")),
    ], "Save pickup", function (v) {
      if (!v.biomass_type_id) return "Choose the residue type.";
      if (!positive(v.quantity_tonnes)) return "Enter the quantity in tonnes.";
      if (v.price_paid === "" || !(Number(v.price_paid) >= 0)) return "Enter the price paid (0 if nothing was paid).";
      if (!v.collected_on || !notFuture(v.collected_on)) return "The pickup date cannot be in the future.";
      addChange("collection.create", { farmer_id: f.id, plot_id: v.plot_id, biomass_type_id: v.biomass_type_id, quantity_tonnes: v.quantity_tonnes, price_paid: v.price_paid, collected_on: v.collected_on, notes: v.notes })
        .then(function () { location.hash = "#/farmer/" + f.id; });
    }, "#/farmer/" + f.id)];
  };

  views.output = function () {
    var snap = state.snapshot;
    if (!snap) return [h("p", { class: "msg warning" }, "Connect to the internet once to download the product list.")];
    return [h("h1", {}, "Report what you made"), h("p", { class: "muted" }, "Pellets, briquettes and other products. This goes up to your Grid and its Hub."), form([
      row("What was made", select("product_id", optionsOf(snap.products), "Choose")),
      row("Quantity made (tonnes, rough is fine)", input("quantity_tonnes", "text", { inputmode: "decimal" })),
      row("Residue used up (tonnes, if known)", input("biomass_used_tonnes", "text", { inputmode: "decimal" })),
      row("Date", input("produced_on", "date", { value: today() })),
      row("Notes (optional)", input("notes")),
    ], "Report output", function (v) {
      if (!v.product_id) return "Choose what was made.";
      if (!positive(v.quantity_tonnes)) return "Enter the quantity in tonnes.";
      if (v.biomass_used_tonnes !== "" && !(Number(v.biomass_used_tonnes) >= 0)) return "Residue used must be a number.";
      if (!v.produced_on || !notFuture(v.produced_on)) return "The date cannot be in the future.";
      addChange("output.create", { product_id: v.product_id, quantity_tonnes: v.quantity_tonnes, biomass_used_tonnes: v.biomass_used_tonnes, produced_on: v.produced_on, notes: v.notes })
        .then(function () { location.hash = "#/sync"; });
    }, "#/")];
  };

  views.sync = function () {
    var button = h("button", { class: "primary", id: "sync-now" }, state.syncing ? "Sending…" : "Send now");
    button.addEventListener("click", function () { syncNow(); });
    return [
      h("h1", {}, "To send"),
      state.needLogin ? h("p", { class: "msg warning" }, ["Please log in again to send your changes. ", h("a", { href: cfg.loginUrl + "?next=" + encodeURIComponent(location.pathname) }, "Log in")]) : null,
      h("p", {}, button, " ", h("small", { class: "muted" }, navigator.onLine ? "You are online." : "No signal. Changes stay on this phone.")),
      h("ul", { class: "list", id: "queue" }, state.queue.length
        ? state.queue.map(function (op) {
            var discard = h("button", { type: "button", class: "small" }, "Discard");
            discard.addEventListener("click", function () {
              if (confirm("Discard this change? It will not be saved on the server.")) queueDelete(op.id).then(function () { refreshStatus().then(render); });
            });
            var retry = h("button", { type: "button", class: "small" }, "Try again");
            retry.addEventListener("click", function () { delete op.error; queuePut(op).then(function () { refreshStatus(); syncNow(); }); });
            return h("li", {}, describe(op, state.snapshot), h("small", { class: op.error ? "err" : "" }, op.error ? op.error : "Waiting to send"),
              op.error ? h("span", {}, retry, " ", discard) : null);
          })
        : h("li", { class: "muted" }, "Nothing waiting. All changes are sent.")),
      h("h2", {}, "Sent recently"),
      h("ul", { class: "list", id: "history" }, state.history.length
        ? state.history.map(function (e) { return h("li", {}, e.text, h("small", {}, (e.status === "flagged" ? "Sent. " + e.message : "Sent") + " · " + new Date(e.at).toLocaleString())); })
        : h("li", { class: "muted" }, "Nothing yet.")),
    ];
  };

  // ---------------------------------------------------------------- router
  function render() {
    var parts = (location.hash.replace(/^#\/?/, "") || "").split("/");
    var main = document.getElementById("view");
    var out;
    switch (parts[0]) {
      case "farmers": out = views.farmers(); break;
      case "farmer": out = parts[1] === "new" ? views.farmerNew() : views.farmer(parts[1]); break;
      case "plot": out = views.plot(parts[1]); break;
      case "crop": out = views.crop(parts[1], parts[2]); break;
      case "pickup": out = views.pickup(parts[1]); break;
      case "output": out = views.output(); break;
      case "sync": out = views.sync(); break;
      default: out = views.home();
    }
    main.textContent = "";
    append(main, out);
    var tabs = document.getElementById("tabs");
    tabs.textContent = "";
    [["#/", "Home"], ["#/farmers", "Farmers"], ["#/output", "Output"], ["#/sync", "To send (" + state.queue.length + ")"]].forEach(function (t) {
      tabs.appendChild(h("a", { href: t[0], class: (location.hash || "#/") === t[0] ? "active" : "" }, t[1]));
    });
  }

  window.addEventListener("hashchange", function () { state.confirmDuplicate = false; render(); });
  window.addEventListener("online", function () { refreshStatus(); syncNow(); });
  window.addEventListener("offline", function () { refreshStatus(); render(); });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register(cfg.swUrl, { scope: "/mitra/" }).catch(function () {});
  }

  load().then(function () {
    return refreshStatus();
  }).then(function () {
    render();
    if (navigator.onLine) syncNow();
    setInterval(function () { if (navigator.onLine && !state.syncing) syncNow(); }, 60000);
  });

  window.__mitra = { state: state, syncNow: syncNow };
})();
