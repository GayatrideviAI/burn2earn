/* Offline yard app.
 *
 * Everything the yard operator does is saved on the phone first (IndexedDB) as a "change" with an
 * id made on the phone. When there is a signal the changes are sent to the server in order. The
 * server uses the id as the record's id, so a change sent twice is only saved once.
 *
 * The fire and spoilage risk is worked out on the server. With no signal the phone shows the last
 * level it downloaded, and raises it at once if a temperature just entered is higher.
 */
(function () {
  "use strict";

  // ---------------------------------------------------------------- language
  var LANG = "en";
  var CATALOG = (typeof window !== "undefined" && window.YARD && window.YARD.catalog) || {};

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

  // Levels, as on the server: 0 Normal, 1 Needs attention, 2 Watch closely, 3 Check twice a day, 4 Fire likely.
  function levelLabel(level) {
    return [t("Normal"), t("Needs attention"), t("Watch closely"), t("Check twice a day"), t("Fire likely")][level] || "";
  }
  function levelAction(level) {
    return [
      "",
      t("Probe the stack today and look it over."),
      t("Inspect the stack today and probe it twice a day."),
      t("Check twice a day and open up the stack. Keep the fire service number ready."),
      t("Fire is likely. Call the fire service before disturbing the stack."),
    ][level] || "";
  }
  var TAGS = ["good", "warn", "warn", "bad", "bad"];

  /** The level a temperature alone gives, using the limits the server sent. */
  function tempLevel(temp, th) {
    var x = Number(temp);
    if (!th || !isFinite(x)) return 0;
    if (x >= th.emergency) return 4;
    if (x >= th.act) return 3;
    if (x >= th.watch) return 2;
    if (x >= th.warm) return 1;
    return 0;
  }

  /** What an inspection alone gives, as on the server. */
  function inspectionLevel(d) {
    var level = 0;
    if (d.steam_or_smell) level = Math.max(level, 3);
    if (d.looks_wet) level = Math.max(level, 2);
    if (d.mould) level = Math.max(level, 1);
    if (d.cover_in_place === false) level = Math.max(level, 1);
    return level;
  }

  /** The snapshot with everything saved on the phone but not yet sent laid over it. */
  function overlay(snapshot, queue) {
    var snap = JSON.parse(JSON.stringify(snapshot || { piles: [], alerts: [], thresholds: null }));
    var piles = snap.piles || [], alerts = snap.alerts || [];
    piles.forEach(function (p) { p.local = 0; p.pending = 0; });
    var freshReading = {};
    queue.slice().sort(function (a, b) { return a.seq - b.seq; }).forEach(function (op) {
      var d = op.data, pile;
      if (op.type === "heat.create") {
        pile = byId(piles, d.pile_id);
        if (!pile) return;
        pile.readings.unshift({ at: d.taken_at, temperature_c: String(d.temperature_c), spot: d.spot || "", pending: true });
        pile.readings.sort(function (a, b) { return a.at < b.at ? 1 : -1; });
        pile.local = Math.max(pile.local, tempLevel(d.temperature_c, snap.thresholds));
        freshReading[pile.id] = true;
        pile.pending++;
      } else if (op.type === "inspection.create") {
        pile = byId(piles, d.pile_id);
        if (!pile) return;
        pile.last_inspection = {
          at: d.inspected_at, looks_wet: !!d.looks_wet, mould: !!d.mould, steam_or_smell: !!d.steam_or_smell,
          cover_in_place: d.cover_in_place !== false, pending: true,
        };
        pile.local = Math.max(pile.local, inspectionLevel(d));
        pile.pending++;
      } else if (op.type === "size.update") {
        pile = byId(piles, d.pile_id);
        if (!pile) return;
        ["length_m", "width_m", "height_m"].forEach(function (k) { if (d[k] !== "" && d[k] != null) pile[k] = String(d[k]); });
        if (d.cover_type) pile.cover_type = d.cover_type;
        pile.pending++;
      } else if (op.type === "count.create" || op.type === "moisture.create") {
        piles.forEach(function (p) {
          var batch = byId(p.batches, d.batch_id);
          if (!batch) return;
          if (op.type === "count.create") batch.pending_count = d.tonnes; else batch.pending_moisture = d.percent;
          p.pending++;
        });
      } else if (op.type === "alert.acknowledge") {
        var alert = byId(alerts, d.alert_id);
        if (alert) { alert.acknowledged = true; alert.pending = true; }
      }
    });
    // A pile flagged only because it had no recent reading is no longer flagged for that once one is waiting to send.
    piles.forEach(function (p) {
      var a = p.assessment;
      var base = freshReading[p.id] && a.stale && a.level <= 1 && a.reasons.length <= 1 ? 0 : a.level;
      p.level = Math.max(base, p.local);
      p.raisedHere = p.level > a.level;
    });
    piles.sort(function (a, b) { return b.level - a.level || (a.yard + a.label).localeCompare(b.yard + b.label); });
    return snap;
  }

  function ageText(iso, now) {
    var ms = (now || Date.now()) - new Date(iso).getTime();
    var days = Math.floor(ms / 86400000);
    if (days >= 1) return t("%(n)s days ago", { n: days });
    var hours = Math.floor(ms / 3600000);
    return hours >= 1 ? t("%(n)s hours ago", { n: hours }) : t("just now");
  }

  /** One line describing a saved change, for the "waiting to send" list. */
  function describe(op, snapshot) {
    var d = op.data, s = snapshot || { piles: [], alerts: [] };
    var pile = function (id) { var p = byId(s.piles || [], id); return p ? p.label : t("a pile"); };
    var batchPile = function (id) {
      var found = t("a pile");
      (s.piles || []).forEach(function (p) { if (byId(p.batches, id)) found = p.label; });
      return found;
    };
    switch (op.type) {
      case "heat.create": return t("%(temp)s °C in pile %(pile)s", { temp: d.temperature_c, pile: pile(d.pile_id) });
      case "inspection.create": return t("Inspection of pile %(pile)s", { pile: pile(d.pile_id) });
      case "count.create": return t("Count of %(tonnes)s t in pile %(pile)s", { tonnes: d.tonnes, pile: batchPile(d.batch_id) });
      case "moisture.create": return t("Moisture %(percent)s in pile %(pile)s", { percent: d.percent + "%", pile: batchPile(d.batch_id) });
      case "size.update": return t("Size of pile %(pile)s", { pile: pile(d.pile_id) });
      case "alert.acknowledge": return t("Alert seen");
      case "photo.weigh": return t("Weighbridge weight %(tonnes)s t for a photo", { tonnes: d.weighed_tonnes });
      default: return op.type;
    }
  }

  var core = { uuid: uuid, overlay: overlay, describe: describe, tempLevel: tempLevel, inspectionLevel: inspectionLevel, today: today };
  if (typeof module !== "undefined" && module.exports) module.exports = core;
  if (typeof window === "undefined" || !window.YARD) return; // loaded by a test, not a browser page

  var cfg = window.YARD;

  // ---------------------------------------------------------------- language choice
  function knownLanguage(code) {
    return (cfg.languages || []).some(function (l) { return l[0] === code; }) ? code : null;
  }
  function chosenLanguage() {
    var stored = null;
    try { stored = localStorage.getItem("yard_lang"); } catch (e) { /* private mode */ }
    var cookie = document.cookie.match(/(?:^|; )django_language=([^;]+)/);
    return knownLanguage(stored) || knownLanguage(cookie && cookie[1]) || knownLanguage(cfg.serverLanguage) || "en";
  }
  function setLanguage(code) {
    LANG = code;
    try { localStorage.setItem("yard_lang", code); } catch (e) { /* private mode */ }
    document.cookie = "django_language=" + code + "; path=/; max-age=31536000; SameSite=Lax";
    document.documentElement.lang = code;
    refreshStatus();
    render();
    // The reasons come from the server in the chosen language, so fetch them again if we can.
    if (navigator.onLine) downloadData().then(render).catch(function () {});
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

  // ---------------------------------------------------------------- storage
  var dbPromise = new Promise(function (resolve, reject) {
    var request = indexedDB.open("yard-app", 1);
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
        var transaction = db.transaction(store, mode);
        var result = work(transaction.objectStore(store));
        transaction.oncomplete = function () { resolve(result && result.result !== undefined ? result.result : undefined); };
        transaction.onerror = function () { reject(transaction.error); };
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
    return queuePut(op).then(refreshStatus).then(function () { scheduleSync(); return op; });
  }

  // ---------------------------------------------------------------- state
  var state = { snapshot: null, queue: [], history: [], online: navigator.onLine, syncing: false, needLogin: false, flash: null };

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
        if (left && left < before && navigator.onLine && !state.needLogin) setTimeout(syncNow, 500);
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
  function tick(name, label, checked) {
    var box = h("input", { type: "checkbox", name: name, id: "f_" + name });
    if (checked) box.checked = true;
    return h("div", { class: "field" }, box, h("label", { for: "f_" + name, class: "inline" }, label));
  }

  function form(fields, submitLabel, onSubmit, cancelHref) {
    var error = h("p", { class: "msg error", hidden: true });
    var f = h("form", { novalidate: true });
    f.appendChild(error);
    fields.forEach(function (x) { f.appendChild(x); });
    f.appendChild(h("button", { class: "primary", type: "submit" }, submitLabel));
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

  function number(value) { return value !== "" && isFinite(Number(value)); }
  function positive(value) { return number(value) && Number(value) > 0; }
  function notFuture(value) { return value <= today(); }

  function tag(level) { return h("span", { class: "tag " + TAGS[level] }, levelLabel(level)); }

  // ---------------------------------------------------------------- photos (shared with the Mitra app)
  var photos = window.WeightPhotos.create({
    app: "yard", uploadUrl: cfg.photosUrl, t: t, csrf: csrf, today: today,
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

  views.photo = function (subject, pileId) {
    var pile = pileId ? pileFor(pileId) : null;
    if (pileId && !pile) return [h("p", {}, t("Pile not found."))];
    return photos.capture({ subject: subject === "load" ? "load" : "stack", pile: pile, back: pile ? "#/pile/" + pile.id : "#/" });
  };

  views.photos = function () {
    return photos.list(state.snapshot ? state.snapshot.photos_to_weigh : []);
  };

  function view() { return overlay(state.snapshot, state.queue); }

  function flashBox() {
    if (!state.flash) return null;
    var f = state.flash;
    state.flash = null;
    return h("p", { class: "msg" + (f.level >= 2 ? " warning" : "") }, f.text);
  }

  views.home = function () {
    var v = view();
    var open = v.alerts.filter(function (a) { return !a.acknowledged; });
    var waiting = state.queue.filter(function (op) { return !op.error; }).length;
    if (!state.snapshot) {
      return [h("h1", {}, t("Yard check")), h("p", { class: "msg warning" }, t("Connect to the internet once so your piles can be downloaded."))];
    }
    var stats = h("div", { class: "stats" },
      h("div", {}, h("strong", {}, v.piles.length), h("span", {}, t("Piles"))),
      h("div", {}, h("strong", {}, open.length), h("span", {}, t("Alerts"))),
      h("div", {}, h("strong", {}, waiting), h("span", {}, t("To send"))));
    return [
      h("h1", {}, t("Hello, %(name)s", { name: v.operator ? v.operator.name : "" })),
      flashBox(),
      state.needLogin ? h("p", { class: "msg warning" }, [t("Please log in again to send your changes.") + " ", h("a", { href: cfg.loginUrl + "?next=" + encodeURIComponent(location.pathname) }, t("Log in"))]) : null,
      stats,
      open.length ? h("h2", {}, t("Alerts")) : null,
      open.map(function (a) {
        var ack = h("button", { type: "button", class: "primary" }, t("I have seen this"));
        ack.addEventListener("click", function () {
          addChange("alert.acknowledge", { alert_id: a.id, acknowledged_at: new Date().toISOString() }).then(function () { render(); });
        });
        return h("section", { class: "card alertbox" },
          h("h3", {}, link(t("Pile %(pile)s", { pile: a.pile }), "#/pile/" + a.pile_id), " ", tag(a.level)),
          h("p", { class: "muted" }, a.yard + " · " + ageText(a.raised_at)),
          h("ul", { class: "reasons" }, (a.reasons || "").split("\n").filter(Boolean).map(function (r) { return h("li", {}, r); })),
          ack);
      }),
      h("p", {}, link(t("Photograph a loaded vehicle"), "#/photo/load", "button"), " ", link(t("Photos"), "#/photos", "button")),
      h("h2", {}, t("All piles")),
      v.piles.length ? h("ul", { class: "list" }, v.piles.map(function (p) {
        var last = p.readings[0];
        return h("li", {}, h("a", { href: "#/pile/" + p.id },
          t("Pile %(pile)s", { pile: p.label }), " ", tag(p.level),
          h("small", {}, p.yard + " · " + (last ? last.temperature_c + " °C · " + ageText(last.at) : t("No temperature readings yet.")) + (p.pending ? " · " + t("waiting to send") : ""))));
      })) : h("p", { class: "muted" }, t("No piles with stock in this yard.")),
      h("p", { class: "muted" }, t("Everything you enter is saved on this phone first. It is sent when there is a signal.")),
    ];
  };

  function pileFor(id) { return byId(view().piles, id); }

  views.pile = function (id) {
    var p = pileFor(id);
    if (!p) return [h("p", {}, t("Pile not found.")), link(t("Back"), "#/", "button")];
    var a = p.assessment;
    var reasons = a.reasons.filter(Boolean);
    return [
      h("h1", {}, t("Pile %(pile)s", { pile: p.label })),
      h("p", { class: "muted" }, p.yard),
      flashBox(),
      h("p", {}, tag(p.level), p.raisedHere ? h("small", { class: "muted" }, " " + t("Raised on this phone from what you just entered. The server will confirm it when it is sent.")) : null),
      levelAction(p.level) ? h("p", { class: "big" }, levelAction(p.level)) : null,
      h("h2", {}, t("Why this is flagged")),
      reasons.length ? h("ul", { class: "reasons" }, reasons.map(function (r) { return h("li", {}, r); })) : h("p", { class: "muted" }, t("Nothing is flagged on this pile.")),
      a.projection ? h("p", { class: "muted" }, a.projection) : null,
      h("div", { class: "actions" },
        link(t("Log a temperature"), "#/heat/" + p.id, "button primary"),
        link(t("Log an inspection"), "#/inspect/" + p.id, "button"),
        link(t("Count the stock"), "#/count/" + p.id, "button"),
        link(t("Log a moisture reading"), "#/moisture/" + p.id, "button"),
        link(t("Pile size and cover"), "#/size/" + p.id, "button"),
        link(t("Photograph this stack"), "#/photo/stack/" + p.id, "button")),
      h("h2", {}, t("Recent temperatures")),
      p.readings.length ? h("ul", { class: "list" }, p.readings.map(function (r) {
        return h("li", {}, r.temperature_c + " °C", h("small", {}, ageText(r.at) + (r.spot ? " · " + r.spot : "") + (r.pending ? " · " + t("waiting to send") : "")));
      })) : h("p", { class: "muted" }, t("No temperature readings yet.")),
      h("h2", {}, t("Recent inspections")),
      p.last_inspection ? h("p", {}, ageText(p.last_inspection.at) + ": " + inspectionText(p.last_inspection) + (p.last_inspection.pending ? " · " + t("waiting to send") : "")) : h("p", { class: "muted" }, t("No inspections yet.")),
      h("h2", {}, t("Batches in this pile")),
      h("ul", { class: "list" }, p.batches.map(function (b) {
        return h("li", {}, b.code, h("small", {}, t("%(t)s on the books, received %(d)s", { t: b.book_tonnes + " t", d: b.received_on }) +
          (b.pending_count || b.pending_moisture ? " · " + t("waiting to send") : "")));
      })),
      p.height_m ? h("p", { class: "muted" }, t("%(h)s m high", { h: p.height_m })) : null,
    ];
  };

  function inspectionText(i) {
    var bits = [];
    if (i.looks_wet) bits.push(t("wet"));
    if (i.mould) bits.push(t("mould"));
    if (i.steam_or_smell) bits.push(t("steam or smell"));
    if (!i.cover_in_place) bits.push(t("cover missing"));
    return bits.length ? bits.join(", ") : t("all clear");
  }

  function backToPile(p, extra) {
    if (extra) state.flash = extra;
    location.hash = "#/pile/" + p.id;
  }

  views.heat = function (id) {
    var p = pileFor(id), snap = state.snapshot;
    if (!p) return [h("p", {}, t("Pile not found."))];
    return [h("h1", {}, t("Log a temperature") + " · " + p.label), form([
      row(t("Temperature (°C)"), input("temperature_c", "text", { inputmode: "decimal" })),
      row(t("Where in the stack"), input("spot", "text", { placeholder: t("For example north face, 1 m deep") })),
      row(t("Probe depth (cm)"), input("depth_cm", "text", { inputmode: "numeric" })),
    ], t("Save temperature"), function (v) {
      if (!number(v.temperature_c) || Number(v.temperature_c) < -20 || Number(v.temperature_c) > 200) return t("Enter a temperature between -20 and 200 °C.");
      if (v.depth_cm !== "" && !(/^\d+$/.test(v.depth_cm) && Number(v.depth_cm) <= 500)) return t("Probe depth must be a whole number of centimetres, up to 500.");
      var level = tempLevel(v.temperature_c, snap && snap.thresholds);
      addChange("heat.create", { pile_id: p.id, temperature_c: v.temperature_c, spot: v.spot, depth_cm: v.depth_cm === "" ? null : Number(v.depth_cm), taken_at: new Date().toISOString() })
        .then(function () {
          var text = t("Saved on this phone.");
          if (level >= 2) text += " " + levelLabel(level) + ". " + levelAction(level);
          backToPile(p, { text: text, level: level });
        });
    }, "#/pile/" + p.id)];
  };

  views.inspect = function (id) {
    var p = pileFor(id);
    if (!p) return [h("p", {}, t("Pile not found."))];
    return [h("h1", {}, t("Log an inspection") + " · " + p.label), form([
      tick("looks_wet", t("The stack looks wet")),
      tick("mould", t("Mould is visible")),
      tick("steam_or_smell", t("Steam, or a burnt or musty smell")),
      tick("cover_in_place", t("Cover is in place and secure"), true),
      row(t("Notes"), h("textarea", { name: "notes", id: "f_notes", rows: "2" })),
    ], t("Save inspection"), function (v) {
      var data = { pile_id: p.id, looks_wet: v.looks_wet, mould: v.mould, steam_or_smell: v.steam_or_smell, cover_in_place: v.cover_in_place, notes: v.notes, inspected_at: new Date().toISOString() };
      var level = inspectionLevel(data);
      addChange("inspection.create", data).then(function () {
        var text = t("Saved on this phone.");
        if (level >= 2) text += " " + levelLabel(level) + ". " + levelAction(level);
        backToPile(p, { text: text, level: level });
      });
    }, "#/pile/" + p.id)];
  };

  function batchOptions(p) {
    return p.batches.map(function (b) { return { value: b.id, label: b.code + " (" + b.book_tonnes + " t)" }; });
  }

  views.count = function (id) {
    var p = pileFor(id), snap = state.snapshot;
    if (!p || !snap) return [h("p", {}, t("Pile not found."))];
    return [h("h1", {}, t("Count the stock") + " · " + p.label), form([
      row(t("Batch"), select("batch_id", batchOptions(p), null)),
      row(t("Counted (tonnes)"), input("tonnes", "text", { inputmode: "decimal" })),
      row(t("How it was counted"), select("method", snap.count_methods.map(function (m) { return { value: m.id, label: m.name }; }), null)),
      row(t("Date"), input("counted_on", "date", { value: today() })),
    ], t("Save count"), function (v) {
      if (!v.batch_id) return t("Choose the batch.");
      if (!number(v.tonnes) || Number(v.tonnes) < 0) return t("Enter the quantity in tonnes.");
      if (!v.counted_on || !notFuture(v.counted_on)) return t("The date cannot be in the future.");
      addChange("count.create", { batch_id: v.batch_id, tonnes: v.tonnes, method: v.method, counted_on: v.counted_on })
        .then(function () { backToPile(p, { text: t("Saved on this phone."), level: 0 }); });
    }, "#/pile/" + p.id)];
  };

  views.moisture = function (id) {
    var p = pileFor(id);
    if (!p) return [h("p", {}, t("Pile not found."))];
    return [h("h1", {}, t("Log a moisture reading") + " · " + p.label), form([
      row(t("Batch"), select("batch_id", batchOptions(p), null)),
      row(t("Moisture (%)"), input("percent", "text", { inputmode: "decimal" })),
      row(t("Method"), input("method", "text", { value: "handheld meter" })),
    ], t("Save moisture"), function (v) {
      if (!v.batch_id) return t("Choose the batch.");
      if (!number(v.percent) || Number(v.percent) < 0 || Number(v.percent) > 100) return t("Enter a moisture between 0 and 100.");
      addChange("moisture.create", { batch_id: v.batch_id, percent: v.percent, method: v.method, observed_at: new Date().toISOString() })
        .then(function () { backToPile(p, { text: t("Saved on this phone."), level: 0 }); });
    }, "#/pile/" + p.id)];
  };

  views.size = function (id) {
    var p = pileFor(id);
    if (!p) return [h("p", {}, t("Pile not found."))];
    return [h("h1", {}, t("Pile size and cover") + " · " + p.label), form([
      row(t("Length (m)"), input("length_m", "text", { inputmode: "decimal", value: p.length_m })),
      row(t("Width (m)"), input("width_m", "text", { inputmode: "decimal", value: p.width_m })),
      row(t("Height (m)"), input("height_m", "text", { inputmode: "decimal", value: p.height_m })),
      row(t("Cover"), input("cover_type", "text", { value: p.cover_type, placeholder: t("For example tarp, shed, none") })),
    ], t("Save pile details"), function (v) {
      var bad = ["length_m", "width_m", "height_m"].some(function (k) { return v[k] !== "" && !positive(v[k]); });
      if (bad) return t("Sizes must be numbers above zero.");
      addChange("size.update", { pile_id: p.id, length_m: v.length_m, width_m: v.width_m, height_m: v.height_m, cover_type: v.cover_type })
        .then(function () { backToPile(p, { text: t("Saved on this phone."), level: 0 }); });
    }, "#/pile/" + p.id)];
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
      case "pile": out = views.pile(parts[1]); break;
      case "heat": out = views.heat(parts[1]); break;
      case "inspect": out = views.inspect(parts[1]); break;
      case "count": out = views.count(parts[1]); break;
      case "moisture": out = views.moisture(parts[1]); break;
      case "size": out = views.size(parts[1]); break;
      case "photo": out = views.photo(parts[1], parts[2]); break;
      case "photos": out = views.photos(); break;
      case "sync": out = views.sync(); break;
      default: out = views.home();
    }
    drawLangs();
    var tabs = document.getElementById("tabs");
    tabs.textContent = "";
    [["#/", t("Home")], ["#/photos", t("Photos") + " (" + (state.photoCount || 0) + ")"], ["#/sync", t("To send") + " (" + state.queue.length + ")"]].forEach(function (item) {
      tabs.appendChild(h("a", { href: item[0], class: (location.hash || "#/") === item[0] ? "active" : "" }, item[1]));
    });
    // Some screens (the photo list) read from the phone's storage first.
    var draw = function (nodes) { main.textContent = ""; append(main, nodes); };
    if (out && typeof out.then === "function") out.then(draw); else draw(out);
  }

  window.addEventListener("hashchange", render);
  window.addEventListener("online", function () { refreshStatus(); syncNow(); });
  window.addEventListener("offline", function () { refreshStatus(); render(); });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register(cfg.swUrl, { scope: "/yard/" }).catch(function () {});
  }

  load().then(function () {
    return refreshStatus();
  }).then(function () {
    render();
    if (navigator.onLine) syncNow();
    setInterval(function () { if (navigator.onLine && !state.syncing) syncNow(); }, 60000);
  });

  window.__yard = { state: state, syncNow: syncNow };
})();
