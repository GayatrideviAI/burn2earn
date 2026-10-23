/* Photos of stacks and loaded vehicles, for the offline Yard and Mitra apps.
 *
 * A photo is shrunk on the phone, saved in IndexedDB with its details, and uploaded on its own when
 * there is a signal. The phone chooses the photo's id and the server uses it as the record's id, so
 * a photo sent twice is only saved once. The weighbridge weight can be typed in with the photo, or
 * later; it is what a future weight-from-photo model will be trained and checked against.
 */
(function (root) {
  "use strict";

  var MAX_SIDE = 1600;
  var dbPromise = null;

  function open() {
    if (!dbPromise) {
      dbPromise = new Promise(function (resolve, reject) {
        var request = indexedDB.open("weight-photos", 1);
        request.onupgradeneeded = function () { request.result.createObjectStore("photos", { keyPath: "id" }); };
        request.onsuccess = function () { resolve(request.result); };
        request.onerror = function () { reject(request.error); };
      });
    }
    return dbPromise;
  }

  function tx(mode, work) {
    return open().then(function (db) {
      return new Promise(function (resolve, reject) {
        var t = db.transaction("photos", mode);
        var result = work(t.objectStore("photos"));
        t.oncomplete = function () { resolve(result && result.result !== undefined ? result.result : undefined); };
        t.onerror = function () { reject(t.error); };
      });
    });
  }

  function uuid() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  /** Shrink a photo to JPEG with its longest side at most MAX_SIDE. Resaving also drops location and camera details. */
  function shrink(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        var scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
        var canvas = document.createElement("canvas");
        canvas.width = Math.round(img.naturalWidth * scale);
        canvas.height = Math.round(img.naturalHeight * scale);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        canvas.toBlob(function (blob) { blob ? resolve(blob) : reject(new Error("shrink")); }, "image/jpeg", 0.85);
      };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error("not an image")); };
      img.src = url;
    });
  }

  function create(opts) {
    var t = opts.t, ui = opts.ui;
    var h = ui.h;

    function all() {
      return tx("readonly", function (s) { return s.getAll(); }).then(function (rows) {
        return (rows || []).filter(function (p) { return p.app === opts.app; }).sort(function (a, b) { return a.seq - b.seq; });
      });
    }
    function put(p) { return tx("readwrite", function (s) { return s.put(p); }); }
    function remove(id) { return tx("readwrite", function (s) { return s.delete(id); }); }

    /** How many photos are waiting to be sent (not counting ones the server refused). */
    function waiting() {
      return all().then(function (rows) { return rows.filter(function (p) { return !p.error; }).length; });
    }

    function formData(p) {
      var f = new FormData();
      Object.keys(p.meta).forEach(function (k) { if (p.meta[k] !== "" && p.meta[k] != null) f.append(k, p.meta[k]); });
      f.append("id", p.id);
      f.append("image", p.blob, p.id + ".jpg");
      return f;
    }

    /** Send waiting photos one at a time. Throws "login" if the session has ended. */
    function uploadAll() {
      if (!navigator.onLine) return Promise.resolve(0);
      return all().then(function (rows) {
        var sent = 0;
        var chain = Promise.resolve();
        rows.filter(function (p) { return !p.error; }).forEach(function (p) {
          chain = chain.then(function () {
            return fetch(opts.uploadUrl, {
              method: "POST", credentials: "same-origin",
              headers: { Accept: "application/json", "X-CSRFToken": opts.csrf() }, body: formData(p),
            }).then(function (response) {
              var type = response.headers.get("content-type") || "";
              if (response.status === 401 || response.status === 403 || response.redirected || type.indexOf("json") < 0) throw new Error("login");
              return response.json().then(function (body) {
                if (response.ok) { sent++; return remove(p.id); }
                p.error = body.message || "error";
                return put(p);
              });
            });
          });
        });
        return chain.then(function () { return sent; });
      });
    }

    function add(meta, blob) {
      var p = { id: uuid(), app: opts.app, meta: meta, blob: blob, seq: Date.now(), saved_at: new Date().toISOString() };
      return put(p).then(function () { return p; });
    }

    // ------------------------------------------------------------ screens
    function capture(params) {
      var fileInput = h("input", { type: "file", accept: "image/*", capture: "environment", id: "f_photo", name: "photo_file" });
      var preview = h("img", { alt: "", style: "max-width:100%;max-height:260px;display:none;border-radius:10px" });
      fileInput.addEventListener("change", function () {
        var file = fileInput.files && fileInput.files[0];
        if (!file) return;
        preview.src = URL.createObjectURL(file);
        preview.style.display = "block";
      });
      var isLoad = params.subject === "load";
      var fields = [
        h("p", { class: "muted" }, isLoad
          ? t("Stand to the side so the whole vehicle and its load are in the photo. Keep people's faces out of it.")
          : t("Stand back so the whole stack is in the photo, with its top and one end. Keep people's faces out of it.")),
        h("div", { class: "field" }, h("label", { for: "f_photo" }, t("Photo")), fileInput, preview),
      ];
      if (isLoad) {
        fields.push(ui.row(t("Vehicle"), ui.select("vehicle_type", [
          { value: "tractor_trolley", label: t("Tractor trolley") }, { value: "truck", label: t("Truck") },
          { value: "mini_truck", label: t("Mini truck or pickup") }, { value: "other", label: t("Other") },
        ], t("Choose"))));
        fields.push(ui.row(t("Vehicle number or driver (optional)"), ui.input("vehicle_ref")));
      } else if (!params.pile) {
        fields.push(ui.row(t("Where is it?"), ui.input("place_note")));
      }
      fields.push(
        ui.row(t("Number of bales, if you counted (optional)"), ui.input("bale_count", "text", { inputmode: "numeric" })),
        ui.row(t("Something in the photo that shows size, such as a 2 m pole (optional)"), ui.input("reference_note")),
        h("h2", {}, t("Weighbridge weight")),
        h("p", { class: "muted" }, t("If it has been weighed, enter the weight from the slip. You can also add it later.")),
        ui.row(t("Weight on the slip (tonnes)"), ui.input("weighed_tonnes", "text", { inputmode: "decimal" })),
        ui.row(t("Slip number (optional)"), ui.input("slip_number")),
        ui.row(t("Notes (optional)"), ui.input("notes")),
      );
      return [
        h("h1", {}, isLoad ? t("Photo of a loaded vehicle") : t("Photo of a stack") + (params.pile ? " · " + params.pile.label : "")),
        ui.form(fields, t("Save photo"), function (v) {
          var file = fileInput.files && fileInput.files[0];
          if (!file) return t("Take or choose a photo first.");
          if (isLoad && !v.vehicle_type) return t("Choose the vehicle.");
          if (v.bale_count !== "" && !/^\d+$/.test(v.bale_count)) return t("The number of bales must be a whole number.");
          if (v.weighed_tonnes !== "" && !(Number(v.weighed_tonnes) > 0)) return t("Enter the weight on the slip in tonnes.");
          var meta = {
            subject: params.subject, pile_id: params.pile ? params.pile.id : "", vehicle_type: v.vehicle_type || "",
            vehicle_ref: v.vehicle_ref || "", place_note: v.place_note || "", bale_count: v.bale_count,
            reference_note: v.reference_note, notes: v.notes, weighed_tonnes: v.weighed_tonnes, slip_number: v.slip_number,
            taken_at: new Date().toISOString(), weighed_on: v.weighed_tonnes ? opts.today() : "",
          };
          shrink(file).then(function (blob) { return add(meta, blob); }).then(function () { opts.saved(params); })
            .catch(function () {
              var box = document.querySelector("form .msg.error");
              if (box) { box.textContent = t("That file could not be read as a photo."); box.hidden = false; }
            });
        }, params.back),
      ];
    }

    function weighForm(onSave) {
      var weight = ui.input("weighed_tonnes", "text", { inputmode: "decimal" });
      var slip = ui.input("slip_number");
      var message = h("small", { class: "err" }, "");
      var save = h("button", { type: "button", class: "small primary" }, t("Save weight"));
      save.addEventListener("click", function () {
        if (!(Number(weight.value) > 0)) { message.textContent = t("Enter the weight on the slip in tonnes."); return; }
        onSave({ weighed_tonnes: weight.value.trim(), slip_number: slip.value.trim(), weighed_on: opts.today() });
      });
      return h("div", {}, h("div", { class: "row" }, weight, slip, save), message);
    }

    /** The photos screen: waiting to send, and waiting for a weighbridge weight. */
    function list(snapshotList) {
      return all().then(function (rows) {
        var out = [h("h1", {}, t("Photos"))];
        out.push(h("h2", {}, t("Waiting to send")));
        out.push(h("ul", { class: "list", id: "photo-queue" }, rows.length ? rows.map(function (p) {
          var label = (p.meta.subject === "load" ? t("Loaded vehicle") + (p.meta.vehicle_ref ? " " + p.meta.vehicle_ref : "") : t("Stack")) + " · " + new Date(p.meta.taken_at).toLocaleString();
          var discard = h("button", { type: "button", class: "small" }, t("Discard"));
          discard.addEventListener("click", function () {
            if (confirm(t("Discard this photo? It will not be saved on the server."))) remove(p.id).then(opts.refresh);
          });
          var retry = h("button", { type: "button", class: "small" }, t("Try again"));
          retry.addEventListener("click", function () { delete p.error; put(p).then(opts.refresh); });
          var weighed = p.meta.weighed_tonnes ? " · " + p.meta.weighed_tonnes + " t" : "";
          var item = [label + weighed, h("small", { class: p.error ? "err" : "" }, p.error || t("Waiting to send"))];
          if (p.error) item.push(h("span", {}, retry, " ", discard));
          else if (!p.meta.weighed_tonnes) {
            item.push(weighForm(function (w) {
              p.meta.weighed_tonnes = w.weighed_tonnes; p.meta.slip_number = w.slip_number; p.meta.weighed_on = w.weighed_on;
              put(p).then(opts.refresh);
            }));
          }
          return h("li", {}, item);
        }) : h("li", { class: "muted" }, t("No photos waiting."))));
        out.push(h("h2", {}, t("Sent, waiting for a weighbridge weight")));
        out.push(h("ul", { class: "list", id: "photo-weigh" }, (snapshotList || []).length ? snapshotList.map(function (s) {
          var already = opts.queuedWeights().indexOf(s.id) >= 0;
          var label = (s.subject === "load" ? t("Loaded vehicle") : t("Stack")) + (s.label ? " " + s.label : "") + " · " + new Date(s.taken_at).toLocaleDateString();
          if (already) return h("li", {}, label, h("small", {}, t("Weight waiting to send")));
          return h("li", {}, label, weighForm(function (w) { opts.addWeight(s.id, w); }));
        }) : h("li", { class: "muted" }, t("None. Every sent photo has a weight."))));
        return out;
      });
    }

    return { all: all, waiting: waiting, uploadAll: uploadAll, add: add, capture: capture, list: list };
  }

  root.WeightPhotos = { create: create };
})(typeof window !== "undefined" ? window : this);
