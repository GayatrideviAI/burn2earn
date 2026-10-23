/* Offline Mitra app.
 *
 * Everything the Mitra does is saved on the phone first (IndexedDB) as a "change" with an id
 * made on the phone. When there is a signal the changes are sent to the server in order. The
 * server uses the id as the record's id, so a change sent twice is only saved once.
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- language
  // Every sentence the Mitra reads goes through t(). The catalogue is sent with the page, so the
  // translations work with no signal. A phrase with no translation shows in English.
  var LANG = "en";
  var CATALOG = (typeof window !== "undefined" && window.MITRA && window.MITRA.catalog) || {};

  function t(text, vars) {
    var table = CATALOG[LANG];
    var out = (table && table[text]) || text;
    if (vars) out = out.replace(/%\((\w+)\)s/g, function (m, k) { return vars[k] != null ? vars[k] : m; });
    return out;
  }

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
          id: op.id, code: t("Not sent yet"), name: d.name, mobile: d.mobile,
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
      return f ? f.name : t("a farmer");
    };
    switch (op.type) {
      case "farmer.create": return t("Register farmer %(name)s", { name: d.name });
      case "plot.create": return t("Add a %(area)s acre plot for %(farmer)s", { area: d.area_acres, farmer: farmer(d.farmer_id) });
      case "season.create": return t("Add a crop (%(year)s)", { year: d.year });
      case "collection.create": return t("Pickup of %(tonnes)s t from %(farmer)s", { tonnes: d.quantity_tonnes, farmer: farmer(d.farmer_id) });
      case "output.create": return t("Output of %(tonnes)s t", { tonnes: d.quantity_tonnes });
      case "photo.weigh": return t("Weighbridge weight %(tonnes)s t for a photo", { tonnes: d.weighed_tonnes });
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

  // ---------------------------------------------------------------- language choice
  // Remembered on the phone, and also in the cookie the server pages use, so both agree.
  function knownLanguage(code) {
    return (cfg.languages || []).some(function (l) { return l[0] === code; }) ? code : null;
  }
  function chosenLanguage() {
    var stored = null;
    try { stored = localStorage.getItem("mitra_lang"); } catch (e) { /* private mode */ }
    var cookie = document.cookie.match(/(?:^|; )django_language=([^;]+)/);
    return knownLanguage(stored) || knownLanguage(cookie && cookie[1]) || knownLanguage(cfg.serverLanguage) || "en";
  }
  function setLanguage(code) {
    LANG = code;
    try { localStorage.setItem("mitra_lang", code); } catch (e) { /* private mode */ }
    document.cookie = "django_language=" + code + "; path=/; max-age=31536000; SameSite=Lax";
    document.documentElement.lang = code;
    refreshStatus();
    render();
  }
  function drawLangs() {
    var box = document.getElementById("langs");
    if (!box) return;
    box.textContent = "";
    (cfg.languages || []).forEach(function (l) {
      var b = h("button", { type: "button", class: "link" + (l[0] === LANG ? " on" : ""), lang: l[0] }, l[1]);
      b.addEventListener("click", function () { setLanguage(l[0]); });
      box.appendChild(b);
    });
  }
  LANG = chosenLanguage();
  document.documentElement.lang = LANG;
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
  var state = { snapshot: null, queue: [], history: [], online: navigator.onLine, syncing: false, needLogin: false, flash: null, photoCount: 0 };

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
    var chain = photos.uploadAll().catch(function (e) {
      if (e && e.message === "login") { state.needLogin = true; throw e; }
    });
    if (waiting.length) {
      var batch = waiting.slice(0, 50);
      chain = chain.then(function () { return fetchJson(cfg.syncUrl, {
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
      }); });
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
    return Promise.all([queueAll(), photos.all()]).then(function (both) {
      var rows = both[0], pics = both[1];
      state.queue = rows;
      state.photoCount = pics.length;
      var net = document.getElementById("net");
      var waiting = rows.filter(function (op) { return !op.error; }).length + pics.filter(function (p) { return !p.error; }).length;
      var errors = rows.length - rows.filter(function (op) { return !op.error; }).length + pics.filter(function (p) { return p.error; }).length;
      net.className = "net " + (navigator.onLine ? "on" : "off");
      var bits = [navigator.onLine ? t("Online") : t("Offline")];
      if (waiting) bits.push(t("%(n)s waiting", { n: waiting }));
      if (errors) bits.push(t("%(n)s need attention", { n: errors }));
      net.textContent = bits.join(" · ");
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
    if (cancelHref) f.appendChild(link(t("Cancel"), cancelHref, "button"));
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

  // ---------------------------------------------------------------- photos (shared with the Yard app)
  var photos = window.WeightPhotos.create({
    app: "mitra", uploadUrl: cfg.photosUrl, t: t, csrf: csrf, today: today,
    ui: { h: h, row: row, input: input, select: select, form: form },
    saved: function (params) {
      state.flash = { text: t("Photo saved on this phone."), level: 0 };
      // Counts first, then move: the move redraws the screen and shows the message once.
      refreshStatus().then(function () { location.hash = params.back; scheduleSync(); });
    },
    refresh: function () { refreshStatus().then(render); scheduleSync(); },
    queuedWeights: function () {
      return state.queue.filter(function (op) { return op.type === "photo.weigh"; }).map(function (op) { return op.data.photo_id; });
    },
    addWeight: function (photoId, w) {
      addChange("photo.weigh", { photo_id: photoId, weighed_tonnes: w.weighed_tonnes, slip_number: w.slip_number, weighed_on: w.weighed_on }).then(render);
    },
  });

  // ---------------------------------------------------------------- screens
  var views = {};

  views.photo = function (subject) {
    return photos.capture({ subject: subject === "stack" ? "stack" : "load", pile: null, back: "#/" });
  };

  views.photos = function () {
    return photos.list(state.snapshot ? state.snapshot.photos_to_weigh : []);
  };

  function flashBox() {
    if (!state.flash) return null;
    var text = state.flash.text;
    state.flash = null;
    return h("p", { class: "msg" }, text);
  }

  views.home = function () {
    var totals = pendingTotals(state.queue);
    var farmers = applyOps(state.snapshot, state.queue);
    var plots = farmers.reduce(function (n, f) { return n + f.plots.length; }, 0);
    var waiting = state.queue.filter(function (op) { return !op.error; }).length;
    return [
      h("h1", {}, t("Hello, %(name)s", { name: state.snapshot ? state.snapshot.mitra.name : "Mitra" })),
      state.snapshot && state.snapshot.grid ? h("p", { class: "muted" }, t("Grid %(code)s", { code: state.snapshot.grid.code })) : null,
      h("div", { class: "stats" },
        h("div", {}, h("strong", {}, farmers.length), h("span", {}, t("Farmers"))),
        h("div", {}, h("strong", {}, plots), h("span", {}, t("Plots"))),
        h("div", {}, h("strong", {}, waiting), h("span", {}, t("To send")))),
      totals.pickups || totals.outputs
        ? h("p", { class: "muted" }, t("Saved on this phone, not sent yet: %(pickups)s pickup(s), %(pt)s t; %(outputs)s output report(s), %(ot)s t.", { pickups: totals.pickups, pt: totals.pickupTonnes.toFixed(2), outputs: totals.outputs, ot: totals.outputTonnes.toFixed(2) }))
        : null,
      flashBox(),
      h("p", {}, link(t("Register a farmer"), "#/farmer/new", "button primary"), " ", link(t("Report output"), "#/output", "button")),
      h("p", {}, link(t("Photograph a loaded vehicle"), "#/photo/load", "button"), " ", link(t("Photograph a stack"), "#/photo/stack", "button")),
      !state.snapshot ? h("p", { class: "msg warning" }, t("Connect to the internet once so your farmers and lists can be downloaded.")) : null,
      state.needLogin ? h("p", { class: "msg warning" }, [t("Please log in again to send your changes.") + " ", h("a", { href: cfg.loginUrl + "?next=" + encodeURIComponent(location.pathname) }, t("Log in"))]) : null,
      h("p", { class: "muted" }, t("Everything you enter is saved on this phone first. It is sent when there is a signal.")),
    ];
  };

  views.farmers = function () {
    var q = (state.search || "").toLowerCase();
    var farmers = applyOps(state.snapshot, state.queue).filter(function (f) {
      return !q || (f.name + " " + f.mobile + " " + f.code).toLowerCase().indexOf(q) >= 0;
    });
    var box = h("input", { type: "search", placeholder: t("Name, mobile or code"), value: state.search || "", id: "q" });
    box.addEventListener("input", function () {
      state.search = box.value;
      var list = document.getElementById("farmer-list");
      var next = views.farmerList();
      list.replaceWith(next);
    });
    return [h("h1", {}, t("Farmers")), h("div", { class: "search" }, box), h("p", {}, link(t("Register a farmer"), "#/farmer/new", "button primary")), views.farmerList()];
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
              h("small", {}, f.code + " · " + f.village + " · " + t("%(n)s plot(s)", { n: f.plots.length }) + (f.pending ? " · " + t("waiting to send") : ""))));
          })
        : h("li", { class: "muted" }, t("No farmers found.")));
  };

  views.farmerNew = function () {
    var snap = state.snapshot;
    if (!snap) return [h("h1", {}, t("Register a farmer")), h("p", { class: "msg warning" }, t("Connect to the internet once to download the village list."))];
    var consent = h("input", { type: "checkbox", name: "consent", id: "f_consent" });
    return [h("h1", {}, t("Register a farmer")), form([
      row(t("Name"), input("name")),
      row(t("Mobile number"), input("mobile", "tel", { inputmode: "tel", autocomplete: "off" })),
      row(t("Village"), select("village_id", optionsOf(snap.villages), t("Choose a village"))),
      row(t("Preferred language"), select("preferred_language", [{ value: "hi", label: t("Hindi") }, { value: "en", label: t("English") }, { value: "pa", label: t("Punjabi") }, { value: "other", label: t("Other") }], t("Not stated"))),
      h("div", { class: "field" }, consent, h("label", { for: "f_consent", class: "inline" }, t("The farmer has been told how their information will be used and agrees."))),
    ], t("Save farmer"), function (v) {
      if (!v.name) return t("Enter the farmer's name.");
      if (!/^\+?\d{10,15}$/.test(v.mobile.replace(/\s/g, ""))) return t("Enter a mobile number with 10 to 15 digits.");
      if (!v.village_id) return t("Choose the farmer's village.");
      if (!v.consent) return t("Consent is needed before a farmer can be registered.");
      var duplicate = applyOps(snap, state.queue).filter(function (f) { return f.mobile === v.mobile.replace(/\s/g, ""); })[0];
      if (duplicate && !state.confirmDuplicate) {
        state.confirmDuplicate = true;
        return t("%(name)s already has this mobile number. Families often share a phone. Press Save farmer again to register anyway.", { name: duplicate.name });
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
    if (!f) return [h("p", {}, t("Farmer not found.")), link(t("Back"), "#/farmers", "button")];
    return [
      h("h1", {}, f.name),
      h("p", { class: "muted" }, f.code + " · " + f.mobile + " · " + f.village + (f.pending ? " · " + t("waiting to send") : "")),
      h("p", {}, link(t("Log a pickup"), "#/pickup/" + f.id, "button primary"), " ", link(t("Add a plot"), "#/plot/" + f.id, "button")),
      h("h2", {}, t("Land")),
      f.plots.length ? f.plots.map(function (p) {
        return h("section", { class: "card" },
          h("h3", {}, t("%(a)s acres", { a: p.area_acres })),
          h("p", { class: "muted" }, (p.cell ? t("GeoCell %(code)s", { code: p.cell }) : p.pending ? t("Waiting to send") : t("Outside every GeoCell"))),
          h("ul", { class: "list" }, p.seasons.length
            ? p.seasons.map(function (s) { return h("li", {}, s.season + " " + s.year + ": " + s.crop + (s.variety ? " (" + s.variety + ")" : "") + (s.pending ? " · " + t("waiting to send") : "")); })
            : h("li", { class: "muted" }, t("No crops recorded."))),
          link(t("Add crop"), "#/crop/" + f.id + "/" + p.id, "button"));
      }) : h("p", { class: "muted" }, t("No land added yet.")),
    ];
  };

  views.plot = function (id) {
    var f = farmerFor(id);
    if (!f) return [h("p", {}, t("Farmer not found."))];
    var status = h("small", { class: "muted", id: "gps" }, "");
    var lat = input("latitude", "text", { inputmode: "decimal" }), lon = input("longitude", "text", { inputmode: "decimal" });
    var gps = h("button", { type: "button", id: "locate" }, t("Use my location"));
    gps.addEventListener("click", function () {
      if (!navigator.geolocation) { status.textContent = t("Location is not available on this device."); return; }
      status.textContent = t("Finding location…");
      navigator.geolocation.getCurrentPosition(function (pos) {
        lat.value = pos.coords.latitude.toFixed(6);
        lon.value = pos.coords.longitude.toFixed(6);
        status.textContent = t("Done. Stand at the plot for the best accuracy.");
      }, function () { status.textContent = t("Could not get location. Type it in instead."); });
    });
    return [h("h1", {}, t("Add a plot for %(name)s", { name: f.name })), h("p", {}, gps, " ", status), form([
      row(t("Latitude"), lat), row(t("Longitude"), lon),
      row(t("Area (acres)"), input("area_acres", "text", { inputmode: "decimal" })),
      row(t("Ownership"), select("ownership", [{ value: "owned", label: t("Owned") }, { value: "leased", label: t("Leased") }, { value: "sharecropped", label: t("Sharecropped") }], t("Not stated"))),
      row(t("Irrigation"), select("irrigation", [{ value: "canal", label: t("Canal") }, { value: "tubewell", label: t("Tubewell") }, { value: "rainfed", label: t("Rain-fed") }, { value: "other", label: t("Other") }], t("Not stated"))),
    ], t("Save plot"), function (v) {
      var la = Number(v.latitude), lo = Number(v.longitude);
      if (v.latitude === "" || !(la >= 6 && la <= 38)) return t("Latitude should be between 6 and 38 for India.");
      if (v.longitude === "" || !(lo >= 68 && lo <= 98)) return t("Longitude should be between 68 and 98 for India.");
      if (!positive(v.area_acres)) return t("Enter the area in acres.");
      addChange("plot.create", { farmer_id: f.id, latitude: v.latitude, longitude: v.longitude, area_acres: v.area_acres, ownership: v.ownership, irrigation: v.irrigation })
        .then(function () { location.hash = "#/farmer/" + f.id; });
    }, "#/farmer/" + f.id)];
  };

  views.crop = function (farmerId, plotId) {
    var f = farmerFor(farmerId), snap = state.snapshot;
    if (!f || !snap) return [h("p", {}, t("Not found."))];
    return [h("h1", {}, t("Add a crop")), form([
      row(t("Season"), select("season_id", optionsOf(snap.seasons), t("Choose"))),
      row(t("Year"), input("year", "number", { value: new Date().getFullYear() })),
      row(t("Crop"), select("crop_id", optionsOf(snap.crops), t("Choose"))),
      row(t("Variety (optional)"), input("variety")),
      row(t("Sowing date (optional)"), input("sowing_date", "date")),
      row(t("Expected harvest date (optional)"), input("expected_harvest_date", "date")),
    ], t("Save crop"), function (v) {
      if (!v.season_id || !v.crop_id) return t("Choose the season and the crop.");
      if (!(Number(v.year) >= 2000 && Number(v.year) <= 2100)) return t("Enter a year between 2000 and 2100.");
      if (v.sowing_date && v.expected_harvest_date && v.expected_harvest_date < v.sowing_date) return t("The harvest date cannot be before the sowing date.");
      addChange("season.create", { plot_id: plotId, season_id: v.season_id, crop_id: v.crop_id, year: Number(v.year), variety: v.variety, sowing_date: v.sowing_date, expected_harvest_date: v.expected_harvest_date })
        .then(function () { location.hash = "#/farmer/" + f.id; });
    }, "#/farmer/" + f.id)];
  };

  views.pickup = function (id) {
    var f = farmerFor(id), snap = state.snapshot;
    if (!f || !snap) return [h("p", {}, t("Not found."))];
    return [h("h1", {}, t("Log a pickup from %(name)s", { name: f.name })), form([
      row(t("Plot (optional)"), select("plot_id", f.plots.map(function (p) { return { value: p.id, label: t("%(a)s acres", { a: p.area_acres }) }; }), t("Not stated"))),
      row(t("Residue"), select("biomass_type_id", optionsOf(snap.biomass_types), t("Choose"))),
      row(t("Quantity picked up (tonnes)"), input("quantity_tonnes", "text", { inputmode: "decimal" })),
      row(t("Price paid to the farmer (₹, total)"), input("price_paid", "text", { inputmode: "decimal" })),
      row(t("Date"), input("collected_on", "date", { value: today() })),
      row(t("Notes (optional)"), input("notes")),
    ], t("Save pickup"), function (v) {
      if (!v.biomass_type_id) return t("Choose the residue type.");
      if (!positive(v.quantity_tonnes)) return t("Enter the quantity in tonnes.");
      if (v.price_paid === "" || !(Number(v.price_paid) >= 0)) return t("Enter the price paid (0 if nothing was paid).");
      if (!v.collected_on || !notFuture(v.collected_on)) return t("The pickup date cannot be in the future.");
      addChange("collection.create", { farmer_id: f.id, plot_id: v.plot_id, biomass_type_id: v.biomass_type_id, quantity_tonnes: v.quantity_tonnes, price_paid: v.price_paid, collected_on: v.collected_on, notes: v.notes })
        .then(function () { location.hash = "#/farmer/" + f.id; });
    }, "#/farmer/" + f.id)];
  };

  views.output = function () {
    var snap = state.snapshot;
    if (!snap) return [h("p", { class: "msg warning" }, t("Connect to the internet once to download the product list."))];
    return [h("h1", {}, t("Report what you made")), h("p", { class: "muted" }, t("Pellets, briquettes and other products. This goes up to your Grid and its Hub.")), form([
      row(t("What was made"), select("product_id", optionsOf(snap.products), t("Choose"))),
      row(t("Quantity made (tonnes, rough is fine)"), input("quantity_tonnes", "text", { inputmode: "decimal" })),
      row(t("Residue used up (tonnes, if known)"), input("biomass_used_tonnes", "text", { inputmode: "decimal" })),
      row(t("Date"), input("produced_on", "date", { value: today() })),
      row(t("Notes (optional)"), input("notes")),
    ], t("Report output"), function (v) {
      if (!v.product_id) return t("Choose what was made.");
      if (!positive(v.quantity_tonnes)) return t("Enter the quantity in tonnes.");
      if (v.biomass_used_tonnes !== "" && !(Number(v.biomass_used_tonnes) >= 0)) return t("Residue used must be a number.");
      if (!v.produced_on || !notFuture(v.produced_on)) return t("The date cannot be in the future.");
      addChange("output.create", { product_id: v.product_id, quantity_tonnes: v.quantity_tonnes, biomass_used_tonnes: v.biomass_used_tonnes, produced_on: v.produced_on, notes: v.notes })
        .then(function () { location.hash = "#/sync"; });
    }, "#/")];
  };

  views.sync = function () {
    var button = h("button", { class: "primary", id: "sync-now" }, state.syncing ? t("Sending…") : t("Send now"));
    button.addEventListener("click", function () { syncNow(); });
    return [
      h("h1", {}, t("To send")),
      state.needLogin ? h("p", { class: "msg warning" }, [t("Please log in again to send your changes.") + " ", h("a", { href: cfg.loginUrl + "?next=" + encodeURIComponent(location.pathname) }, t("Log in"))]) : null,
      h("p", {}, button, " ", h("small", { class: "muted" }, navigator.onLine ? t("You are online.") : t("No signal. Changes stay on this phone."))),
      h("ul", { class: "list", id: "queue" }, state.queue.length
        ? state.queue.map(function (op) {
            var discard = h("button", { type: "button", class: "small" }, t("Discard"));
            discard.addEventListener("click", function () {
              if (confirm(t("Discard this change? It will not be saved on the server."))) queueDelete(op.id).then(function () { refreshStatus().then(render); });
            });
            var retry = h("button", { type: "button", class: "small" }, t("Try again"));
            retry.addEventListener("click", function () { delete op.error; queuePut(op).then(function () { refreshStatus(); syncNow(); }); });
            return h("li", {}, describe(op, state.snapshot), h("small", { class: op.error ? "err" : "" }, op.error ? op.error : t("Waiting to send")),
              op.error ? h("span", {}, retry, " ", discard) : null);
          })
        : h("li", { class: "muted" }, t("Nothing waiting. All changes are sent."))),
      h("h2", {}, t("Sent recently")),
      h("ul", { class: "list", id: "history" }, state.history.length
        ? state.history.map(function (e) { return h("li", {}, e.text, h("small", {}, (e.status === "flagged" ? t("Sent.") + " " + e.message : t("Sent")) + " · " + new Date(e.at).toLocaleString())); })
        : h("li", { class: "muted" }, t("Nothing yet."))),
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
      case "photo": out = views.photo(parts[1]); break;
      case "photos": out = views.photos(); break;
      case "sync": out = views.sync(); break;
      default: out = views.home();
    }
    drawLangs();
    var tabs = document.getElementById("tabs");
    tabs.textContent = "";
    [["#/", t("Home")], ["#/farmers", t("Farmers")], ["#/output", t("Output")], ["#/photos", t("Photos") + " (" + (state.photoCount || 0) + ")"], ["#/sync", t("To send") + " (" + state.queue.length + ")"]].forEach(function (item) {
      tabs.appendChild(h("a", { href: item[0], class: (location.hash || "#/") === item[0] ? "active" : "" }, item[1]));
    });
    // Some screens (the photo list) read from the phone's storage first.
    var draw = function (nodes) { main.textContent = ""; append(main, nodes); };
    if (out && typeof out.then === "function") out.then(draw); else draw(out);
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
