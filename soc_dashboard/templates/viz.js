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
