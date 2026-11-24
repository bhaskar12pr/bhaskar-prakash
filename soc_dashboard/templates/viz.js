  /* Shared chart helpers, inlined into every page by socdash.py.
     Follows the dataviz rules: thin marks with 4px rounded data-ends and 2px surface gaps,
     end dots with a 2px surface ring, a crosshair + tooltip on line charts, a per-mark
     tooltip on bars, and a data table under every chart so no value is hover-only.
     All labels go into the DOM with textContent, because names come from CSV files. */
  var Viz = (function () {
    var NS = "http://www.w3.org/2000/svg", tip = null;

    function node(parent, tag, attrs, text) {
      var e = document.createElementNS(NS, tag);
      for (var k in attrs) e.setAttribute(k, attrs[k]);
      if (text != null) e.textContent = text;
      parent.appendChild(e);
      return e;
    }

    /* A bar or stack segment: square at the bottom, 4px rounded top when it is the data end. */
    function bar(parent, x, y, w, h, fill, roundTop) {
      if (h <= 0) return null;
      var r = roundTop ? Math.min(4, w / 2, h) : 0;
      var d = "M" + x + "," + (y + h) + "V" + (y + r) +
        (r ? "Q" + x + "," + y + " " + (x + r) + "," + y : "") + "H" + (x + w - r) +
        (r ? "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) : "") + "V" + (y + h) + "Z";
      return node(parent, "path", { d: d, fill: fill });
    }

    /* Stack segments bottom-up with a 2px surface gap between them. parts: [{value, color, label}]. */
    function stack(parent, x, base, w, scale, parts, onTip) {
      var y = base, drawn = parts.filter(function (p) { return p.value > 0; });
      drawn.forEach(function (p, i) {
        var h = p.value * scale - (i > 0 ? 2 : 0);
        var top = y - p.value * scale;
        var seg = bar(parent, x, top, w, Math.max(0, h), p.color, i === drawn.length - 1);
        if (seg && onTip) hover(seg, onTip);
        y = top;
      });
      return y;
    }

    /* End dot: >= 8px, filled with the series colour, with a 2px surface ring. */
    function dot(parent, cx, cy, color, r) {
      return node(parent, "circle", { cx: cx, cy: cy, r: r || 4, fill: color, stroke: "var(--surface)", "stroke-width": 2 });
    }

    function ensureTip() {
      if (tip) return tip;
      tip = document.createElement("div");
      tip.className = "viz-tip";
      tip.setAttribute("role", "status");
      tip.hidden = true;
      document.body.appendChild(tip);
      return tip;
    }
    /* rows: [{value, label, color, key: "line" | "box"}]; values lead, labels follow. */
    function showTip(clientX, clientY, title, rows) {
      var t = ensureTip();
      t.textContent = "";
      var h = document.createElement("div"); h.className = "viz-tip-title"; h.textContent = title; t.appendChild(h);
      rows.forEach(function (r) {
        var row = document.createElement("div"); row.className = "viz-tip-row";
        var key = document.createElement("i"); key.className = r.key === "box" ? "box" : "line";
        if (r.color) key.style.background = r.color; else key.style.visibility = "hidden";
        var v = document.createElement("b"); v.textContent = r.value;
        var l = document.createElement("span"); l.textContent = r.label;
        row.appendChild(key); row.appendChild(v); row.appendChild(l); t.appendChild(row);
      });
      t.hidden = false;
      var pad = 14, w = t.offsetWidth, hgt = t.offsetHeight;
      var left = clientX + pad + w > window.innerWidth - 8 ? clientX - pad - w : clientX + pad;
      var top = Math.min(window.innerHeight - hgt - 8, Math.max(8, clientY - hgt / 2));
      t.style.left = Math.max(8, left) + "px";
      t.style.top = top + "px";
    }
    function hideTip() { if (tip) tip.hidden = true; }

    /* Per-mark tooltip for bars, cells and segments. fn() returns {title, rows}. */
    function hover(el, fn) {
      el.style.cursor = "default";
      el.addEventListener("pointermove", function (e) { var c = fn(); showTip(e.clientX, e.clientY, c.title, c.rows); el.setAttribute("data-hover", "1"); });
      el.addEventListener("pointerleave", function () { hideTip(); el.removeAttribute("data-hover"); });
    }

    /* Crosshair over a line chart. xs: pixel x per point (null where nothing ran).
       read(i) returns {title, rows}. Arrow keys move it when the chart has focus. */
    function crosshair(svg, xs, top, bottom, left, right, read) {
      var guide = node(svg, "line", { x1: 0, x2: 0, y1: top, y2: bottom, stroke: "var(--muted)", "stroke-width": 1, visibility: "hidden", "pointer-events": "none" });
      var layer = node(svg, "rect", { x: left, y: top, width: Math.max(0, right - left), height: Math.max(0, bottom - top), fill: "transparent" });
      var current = -1;
      function nearest(px) {
        var best = -1, dist = Infinity;
        xs.forEach(function (x, i) { if (x == null) return; var dd = Math.abs(x - px); if (dd < dist) { dist = dd; best = i; } });
        return best;
      }
      function place(i, clientX, clientY) {
        if (i < 0) return;
        current = i;
        guide.setAttribute("x1", xs[i]); guide.setAttribute("x2", xs[i]); guide.setAttribute("visibility", "visible");
        var c = read(i); showTip(clientX, clientY, c.title, c.rows);
      }
      function toSvgX(clientX) {
        var r = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
        return (clientX - r.left) / r.width * vb.width;
      }
      layer.addEventListener("pointermove", function (e) { place(nearest(toSvgX(e.clientX)), e.clientX, e.clientY); });
      layer.addEventListener("pointerleave", function () { guide.setAttribute("visibility", "hidden"); hideTip(); });
      svg.setAttribute("tabindex", "0");
      svg.addEventListener("keydown", function (e) {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") return;
        e.preventDefault();
        var valid = xs.map(function (x, i) { return x == null ? -1 : i; }).filter(function (i) { return i >= 0; });
        if (!valid.length) return;
        var pos = valid.indexOf(current);
        pos = e.key === "Home" ? 0 : e.key === "End" ? valid.length - 1 : pos < 0 ? valid.length - 1 : Math.max(0, Math.min(valid.length - 1, pos + (e.key === "ArrowRight" ? 1 : -1)));
        var r = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
        place(valid[pos], r.left + xs[valid[pos]] / vb.width * r.width, r.top + r.height / 3);
      });
      svg.addEventListener("focus", function () {
        if (current < 0) { var last = xs.length - 1; while (last > 0 && xs[last] == null) last--; current = last; }
        var r = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
        place(current, r.left + xs[current] / vb.width * r.width, r.top + r.height / 3);
      });
      svg.addEventListener("blur", function () { guide.setAttribute("visibility", "hidden"); hideTip(); });
    }

    /* "Show as table" twin for a chart. rows are arrays of display strings. */
    function table(container, summary, headers, rows) {
      var old = container.querySelector(":scope > details.viz-table");
      var open = old ? old.open : false;
      if (old) old.remove();
      var det = document.createElement("details"); det.className = "viz-table"; det.open = open;
      var sum = document.createElement("summary"); sum.textContent = summary; det.appendChild(sum);
      var wrap = document.createElement("div"); wrap.className = "scroll";
      var tbl = document.createElement("table"), thead = document.createElement("thead"), tr = document.createElement("tr");
      headers.forEach(function (h, i) { var th = document.createElement("th"); th.textContent = h; if (i) th.className = "r"; tr.appendChild(th); });
      thead.appendChild(tr); tbl.appendChild(thead);
      var body = document.createElement("tbody");
      rows.forEach(function (r) {
        var row = document.createElement("tr");
        r.forEach(function (c, i) { var td = document.createElement("td"); td.textContent = c; if (i) td.className = "r"; row.appendChild(td); });
        body.appendChild(row);
      });
      tbl.appendChild(body); wrap.appendChild(tbl); det.appendChild(wrap); container.appendChild(det);
    }

    return { bar: bar, stack: stack, dot: dot, hover: hover, crosshair: crosshair, table: table, showTip: showTip, hideTip: hideTip };
  })();

  /* Motion: short, purposeful, and off when the viewer asks for reduced motion.
     Numbers glide from their old value to the new one and the tile that changed flashes once;
     chart lines redraw when the data under them changes. Nothing starts hidden, so a page
     with no animation at all is complete. */
  var Motion = (function () {
    var mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    function reduced() { return !!(mq && mq.matches); }
    function ease(t) { return 1 - Math.pow(1 - t, 3); }  // ease-out cubic

    /* Tween the leading number of each `.value` under `root` from what it showed last time. */
    var last = {};
    function numbers(root, key) {
      var vals = root.querySelectorAll(".value");
      Array.prototype.forEach.call(vals, function (el, i) {
        var node = el.firstChild;
        while (node && node.nodeType !== 3) node = node.firstChild;
        if (!node) return;
        var m = /^(\s*)(-?\d+(?:\.\d+)?)(.*)$/.exec(node.nodeValue);
        if (!m) return;
        var id = key + ":" + i, to = parseFloat(m[2]), dec = (m[2].split(".")[1] || "").length, from = last[id];
        last[id] = to;
        if (from == null || from === to || reduced()) return;
        var tile = el.closest(".kpi");
        if (tile) { tile.classList.remove("changed"); void tile.offsetWidth; tile.classList.add("changed"); }
        var start = null, dur = 450;
        function step(ts) {
          if (start === null) start = ts;
          var t = Math.min(1, (ts - start) / dur);
          node.nodeValue = m[1] + (from + (to - from) * ease(t)).toFixed(dec) + m[3];
          if (t < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
      });
    }

    /* Redraw a path from its start (stroke-dash trick). */
    function draw(path, dur) {
      if (reduced() || !path || !path.getTotalLength) return;
      var len = path.getTotalLength();
      if (!len) return;
      path.style.strokeDasharray = len;
      path.style.strokeDashoffset = len;
      path.getBoundingClientRect();
      path.style.transition = "stroke-dashoffset " + (dur || 600) + "ms cubic-bezier(.2,.8,.2,1)";
      path.style.strokeDashoffset = "0";
      setTimeout(function () { path.style.strokeDasharray = ""; path.style.strokeDashoffset = ""; path.style.transition = ""; }, (dur || 600) + 50);
    }
    /* Draw every line in a chart container, but only after its first render. */
    var seen = {};
    function drawLines(container) {
      var id = container.id;
      if (!seen[id]) { seen[id] = true; return; }
      Array.prototype.forEach.call(container.querySelectorAll("path[data-line]"), function (p) { draw(p, 600); });
    }
    return { reduced: reduced, numbers: numbers, draw: draw, drawLines: drawLines };
  })();

  /* Run waveform: a logic-analyzer style sample-and-hold trace of the pass rate per run, with
     the milestone bar as a dashed threshold and a clock tick per run. Shared by every page.
     opts: { name, rates[], runs[], dates[], need, mark (index to highlight), compact } */
  Viz.wave = (function () {
  var NS = "http://www.w3.org/2000/svg";
  function node(parent, tag, attrs, text) { var e = document.createElementNS(NS, tag); for (var k in attrs) e.setAttribute(k, attrs[k]); if (text != null) e.textContent = text; parent.appendChild(e); return e; }
  return function wave(box, o) {
    var compact = !!o.compact, N = o.rates.length;
    var Wd = compact ? 120 : 340, H = compact ? 34 : 70, Lm = compact ? 2 : 8, R = compact ? 2 : 30, T = compact ? 6 : 16, B = compact ? 4 : 16;
    var s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", "0 0 " + Wd + " " + H); s.setAttribute("class", "chart"); s.setAttribute("role", "img");
    var ran = o.rates.filter(function (r) { return r != null; });
    var need = o.need == null ? 0.9 : o.need, met = ran.filter(function (r) { return r >= need; }).length;
    var pc = function (v) { return (100 * v).toFixed(1) + "%"; };
    s.setAttribute("aria-label", "Pass rate per run for " + o.name + (ran.length ? ", from " + pc(ran[0]) + " to " + pc(ran[ran.length - 1]) : "") + "; " + met + " of " + ran.length + " runs at or above " + Math.round(need * 100) + "%");
    var lo = Math.max(0, Math.floor((Math.min.apply(null, ran.concat([need])) - 0.03) * 20) / 20), hi = 1;
    function y(v) { return T + (hi - v) / ((hi - lo) || 1) * (H - T - B); }
    var cw = (Wd - Lm - R) / Math.max(1, N);
    function x(i) { return Lm + cw * i; }
    if (!compact) for (var i = 0; i < N; i++) node(s, "line", { x1: x(i), x2: x(i), y1: 4, y2: i === o.mark ? 12 : 9, stroke: i === o.mark ? "var(--accent)" : "var(--line)", "stroke-width": i === o.mark ? 2 : 1 });
    var d = "", area = "", prev = null;
    o.rates.forEach(function (r, i) {
      if (r == null) { prev = null; return; }
      var yy = y(r).toFixed(1);
      d += (prev === null ? "M" + x(i) + "," + yy : "V" + yy) + "H" + (x(i) + cw);
      area += "M" + x(i) + "," + yy + "H" + (x(i) + cw) + "V" + y(lo) + "H" + x(i) + "Z";
      prev = r;
    });
    node(s, "path", { d: area, fill: "var(--accent)", "fill-opacity": 0.12 });
    node(s, "line", { x1: Lm, x2: Wd - R, y1: y(need), y2: y(need), stroke: "var(--ink)", "stroke-dasharray": "3 3" });
    if (!compact) node(s, "text", { x: Wd - R + 4, y: y(need) + 4, style: "fill:var(--ink)" }, Math.round(need * 100) + "%");
    node(s, "path", { d: d, fill: "none", stroke: "var(--accent)", "stroke-width": 2, "stroke-linejoin": "miter", "data-line": "1" });
    var m = o.mark == null ? N - 1 : o.mark;
    if (o.rates[m] != null) Viz.dot(s, x(m) + cw / 2, y(o.rates[m]), "var(--accent)", compact ? 3 : 4);
    if (!compact) {
      node(s, "text", { x: Lm, y: H - 3 }, (o.dates[0] || "").slice(5));
      node(s, "text", { x: Wd - R, y: H - 3, "text-anchor": "end" }, (o.dates[N - 1] || "").slice(5));
    }
    Viz.crosshair(s, o.rates.map(function (r, i) { return r == null ? null : x(i) + cw / 2; }), T, H - B, Lm, Wd - R, function (i) {
      var r = o.rates[i];
      return { title: (o.runs[i] || "") + " · " + (o.dates[i] || ""), rows: [{ value: pc(r), label: r >= need ? "at or above the bar" : (100 * (need - r)).toFixed(1) + " pts below the bar", color: "var(--accent)" }] };
    });
    box.textContent = "";
    if (!compact) {
      var cap = document.createElement("figcaption");
      var nm = document.createElement("span"); nm.className = "mono"; nm.textContent = "sim_pass[" + o.name + "]";
      var ct = document.createElement("span"); ct.textContent = met + "/" + ran.length + " runs ≥ " + Math.round(need * 100) + "%";
      cap.appendChild(nm); cap.appendChild(ct); box.appendChild(cap);
    }
    box.appendChild(s);
  };
  })();

  /* Quick search (Ctrl+K, Cmd+K or /): a native <dialog> listbox shared by every page.
     Each page supplies items {kind, label, sub, rank, go}. Results are built only with
     createElement + textContent, since names come from CSV files; nothing leaves the page. */
  var Quick = (function () {
    var dlg, input, list, empty, build, items = null, shown = [], active = 0;
    function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
    function search(q) {
      var words = q.toLowerCase().split(/\s+/).filter(Boolean), first = words[0] || "";
      var out = items.filter(function (it) {
        var hay = (it.label + " " + it.sub + " " + it.kind).toLowerCase();
        return words.every(function (w) { return hay.indexOf(w) >= 0; });
      });
      function score(it) { var l = it.label.toLowerCase(); return l === first ? 0 : l.indexOf(first) === 0 ? 1 : l.indexOf(first) >= 0 ? 2 : 3; }
      out.sort(function (a, b) {
        var la = a.label.toLowerCase(), lb = b.label.toLowerCase();
        return score(a) - score(b) || (a.rank || 0) - (b.rank || 0) || (la < lb ? -1 : la > lb ? 1 : 0);
      });
      return out.slice(0, 50);
    }
    function mark() {
      Array.prototype.forEach.call(list.children, function (li, i) { li.setAttribute("aria-selected", String(i === active)); });
      if (shown.length) { input.setAttribute("aria-activedescendant", "pal-opt-" + active); var a = document.getElementById("pal-opt-" + active); if (a) a.scrollIntoView({ block: "nearest" }); }
    }
    function render() {
      shown = search(input.value.trim());
      active = Math.min(active, Math.max(0, shown.length - 1));
      list.textContent = "";
      list.hidden = !shown.length;
      empty.textContent = shown.length ? "" : "Nothing matches. Try another name.";
      if (!shown.length) { input.removeAttribute("aria-activedescendant"); return; }
      shown.forEach(function (it, i) {
        var li = el("li");
        li.id = "pal-opt-" + i; li.setAttribute("role", "option"); li.setAttribute("aria-selected", String(i === active));
        li.appendChild(el("span", "pal-kind", it.kind)); li.appendChild(el("span", "pal-label", it.label)); li.appendChild(el("span", "pal-sub", it.sub));
        li.addEventListener("click", function () { choose(i); });
        li.addEventListener("pointermove", function () { if (active !== i) { active = i; mark(); } });
        list.appendChild(li);
      });
      mark();
    }
    function choose(i) { var it = shown[i]; if (!it) return; close(); it.go(); }
    function open() {
      if (dlg.open) return;
      if (!items) items = build();
      input.value = ""; active = 0; render();
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
      input.focus();
    }
    function close() { if (dlg.open) dlg.close(); }
    /* builder() returns the items; host is where the Search button goes. */
    function setup(builder, host, placeholder) {
      build = builder;
      var btn = el("button", "pal-open");
      btn.type = "button"; btn.id = "pal-open";
      btn.setAttribute("aria-keyshortcuts", "Control+K Meta+K /"); btn.setAttribute("aria-haspopup", "dialog");
      btn.appendChild(document.createTextNode("Search "));
      btn.appendChild(el("kbd", null, /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘ K" : "Ctrl K"));
      host.appendChild(btn);
      dlg = el("dialog"); dlg.id = "palette"; dlg.setAttribute("aria-labelledby", "pal-title");
      var title = el("h2", "sr-only", "Search this page"); title.id = "pal-title";
      input = el("input"); input.id = "pal-input"; input.type = "text"; input.autocomplete = "off"; input.spellcheck = false;
      input.setAttribute("role", "combobox"); input.setAttribute("aria-expanded", "true"); input.setAttribute("aria-controls", "pal-list");
      input.setAttribute("aria-autocomplete", "list"); input.setAttribute("aria-label", "Search"); input.placeholder = placeholder || "Search…";
      list = el("ul"); list.id = "pal-list"; list.setAttribute("role", "listbox"); list.setAttribute("aria-label", "Results");
      empty = el("p", "pal-empty"); empty.id = "pal-empty"; empty.setAttribute("aria-live", "polite");
      dlg.appendChild(title); dlg.appendChild(input); dlg.appendChild(list); dlg.appendChild(empty);
      dlg.appendChild(el("p", "pal-hint", "↑ ↓ to move · Enter to open · Esc to close"));
      (document.querySelector("main") || document.body).appendChild(dlg);
      input.addEventListener("input", function () { active = 0; render(); });
      input.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(shown.length - 1, active + 1); mark(); }
        else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); mark(); }
        else if (e.key === "Enter") { e.preventDefault(); choose(active); }
      });
      dlg.addEventListener("click", function (e) { if (e.target === dlg) close(); });
      btn.addEventListener("click", open);
      document.addEventListener("keydown", function (e) {
        var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
        if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); open(); }
        else if (e.key === "/" && !typing && !dlg.open) { e.preventDefault(); open(); }
      });
    }
    return { setup: setup, open: open, close: close };
  })();
