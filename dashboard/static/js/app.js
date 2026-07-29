/* zyrahd.net dashboard interactions */

(function () {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

  // Mobile sidebar
  const sidebar = document.querySelector(".sidebar");
  const overlay = document.querySelector(".overlay");
  document.querySelectorAll("[data-toggle-sidebar]").forEach((btn) => {
    btn.addEventListener("click", () => {
      sidebar?.classList.toggle("open");
      overlay?.classList.toggle("show");
    });
  });
  overlay?.addEventListener("click", () => {
    sidebar?.classList.remove("open");
    overlay.classList.remove("show");
  });

  // Auto-hide flashes
  document.querySelectorAll(".flash").forEach((el) => {
    setTimeout(() => {
      el.style.transition = "opacity .35s ease, transform .35s ease";
      el.style.opacity = "0";
      el.style.transform = "translateX(20px)";
      setTimeout(() => el.remove(), 400);
    }, 4200);
  });

  // Cache for discord resources
  const cache = { roles: null, channels: {} };

  async function fetchJSON(url) {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "Fehler");
    return data.data;
  }

  async function loadRoles(force = false) {
    if (!force && cache.roles) return cache.roles;
    cache.roles = await fetchJSON(`/api/roles?all=1${force ? "&force=1" : ""}`);
    return cache.roles;
  }

  async function loadChannels(type = "all", force = false) {
    const key = type;
    if (!force && cache.channels[key]) return cache.channels[key];
    cache.channels[key] = await fetchJSON(`/api/channels?type=${encodeURIComponent(type)}${force ? "&force=1" : ""}`);
    return cache.channels[key];
  }

  function parseSelected(el) {
    const raw = el.getAttribute("data-selected") || "";
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.map(String) : [String(parsed)];
    } catch {
      return raw.split(",").map((s) => s.trim()).filter(Boolean);
    }
  }

  function createSearchSelect(root) {
    const name = root.dataset.name;
    const multiple = root.dataset.multiple === "true";
    const type = root.dataset.type || "roles"; // roles | channels
    const channelType = root.dataset.channelType || "text,announcement";
    const placeholder = root.dataset.placeholder || "Suchen …";
    let selected = new Set(parseSelected(root));

    root.classList.add("ss");
    root.innerHTML = `
      <div class="ss-control" tabindex="0">
        <div class="ss-tags"></div>
        <span class="ss-placeholder">${placeholder}</span>
      </div>
      <div class="ss-dropdown">
        <div class="ss-search"><input type="search" placeholder="🔍 Suchen …" autocomplete="off"></div>
        <div class="ss-options"></div>
        <div class="ss-actions">
          <button type="button" class="btn btn-ghost btn-sm" data-clear>Alle entfernen</button>
          <button type="button" class="btn btn-ghost btn-sm" data-refresh>Aktualisieren</button>
        </div>
      </div>
      <div class="ss-hidden"></div>
    `;

    const control = root.querySelector(".ss-control");
    const tags = root.querySelector(".ss-tags");
    const ph = root.querySelector(".ss-placeholder");
    const dropdown = root.querySelector(".ss-dropdown");
    const search = root.querySelector(".ss-search input");
    const optionsEl = root.querySelector(".ss-options");
    const hidden = root.querySelector(".ss-hidden");
    let items = [];

    function syncHidden() {
      hidden.innerHTML = "";
      [...selected].forEach((id) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = multiple ? `${name}` : name;
        // For multiple, use name[] style via dataset
        if (multiple) input.name = name;
        input.value = id;
        hidden.appendChild(input);
      });
      // Flask getlist needs same name repeated – already handled
    }

    function renderTags() {
      tags.innerHTML = "";
      const map = Object.fromEntries(items.map((i) => [String(i.id), i]));
      [...selected].forEach((id) => {
        const item = map[id] || { id, name: id };
        const tag = document.createElement("span");
        tag.className = "ss-tag";
        const prefix = type === "roles" ? "@" : item.type === "category" ? "" : "#";
        tag.innerHTML = `<span>${prefix}${escapeHtml(item.name)}</span>`;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = "×";
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          selected.delete(String(id));
          render();
        });
        tag.appendChild(btn);
        tags.appendChild(tag);
      });
      ph.style.display = selected.size ? "none" : "inline";
      syncHidden();
    }

    function renderOptions(filter = "") {
      const q = filter.trim().toLowerCase();
      const filtered = items.filter((i) => i.name.toLowerCase().includes(q));
      optionsEl.innerHTML = "";
      if (!filtered.length) {
        optionsEl.innerHTML = `<div class="ss-empty">Kein Ergebnis gefunden</div>`;
        return;
      }
      filtered.forEach((item) => {
        const el = document.createElement("div");
        const disabled = item.selectable === false;
        el.className = "ss-option" + (selected.has(String(item.id)) ? " active" : "") + (disabled ? " disabled" : "");
        const color = item.color || "#9B5CFF";
        const prefix = type === "roles" ? "@" : item.type === "category" ? "📁 " : "#";
        el.innerHTML = `
          <span class="ss-color" style="background:${color}"></span>
          <span>${prefix}${escapeHtml(item.name)}</span>
          ${item.above_bot ? '<span class="badge warn">über Bot</span>' : ""}
          ${item.managed ? '<span class="badge">managed</span>' : ""}
        `;
        if (!disabled) {
          el.addEventListener("click", () => {
            const id = String(item.id);
            if (multiple) {
              if (selected.has(id)) selected.delete(id);
              else selected.add(id);
            } else {
              selected = new Set([id]);
              root.classList.remove("open");
            }
            render();
          });
        }
        optionsEl.appendChild(el);
      });
    }

    function render() {
      renderTags();
      renderOptions(search.value);
    }

    async function load(force = false) {
      optionsEl.innerHTML = `<div class="ss-empty">Lade …</div>`;
      try {
        if (type === "roles") {
          items = await loadRoles(force);
          // hide @everyone already filtered; keep managed marked
        } else {
          items = await loadChannels(channelType, force);
        }
        render();
      } catch (err) {
        optionsEl.innerHTML = `<div class="ss-empty">${escapeHtml(err.message)}</div>`;
      }
    }

    control.addEventListener("click", async () => {
      root.classList.toggle("open");
      if (root.classList.contains("open")) {
        search.focus();
        if (!items.length) await load();
        else render();
      }
    });

    search.addEventListener("input", () => renderOptions(search.value));
    root.querySelector("[data-clear]").addEventListener("click", (e) => {
      e.stopPropagation();
      selected.clear();
      render();
    });
    root.querySelector("[data-refresh]").addEventListener("click", async (e) => {
      e.stopPropagation();
      await load(true);
    });

    document.addEventListener("click", (e) => {
      if (!root.contains(e.target)) root.classList.remove("open");
    });

    // Initial tag render with IDs until loaded
    renderTags();
    // Prefetch labels
    load().catch(() => {});
  }

  function escapeHtml(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  document.querySelectorAll("[data-discord-select]").forEach(createSearchSelect);

  // Ticket type picker on create page
  const typeCards = document.querySelectorAll("[data-ticket-type]");
  const typeInput = document.querySelector("#ticket_type_id");
  const fieldsBox = document.querySelector("#dynamic-fields");
  if (typeCards.length && typeInput && fieldsBox) {
    const types = JSON.parse(document.getElementById("ticket-types-json")?.textContent || "[]");
    typeCards.forEach((card) => {
      card.addEventListener("click", () => {
        typeCards.forEach((c) => c.classList.remove("selected"));
        card.classList.add("selected");
        const id = Number(card.dataset.ticketType);
        typeInput.value = id;
        const t = types.find((x) => x.id === id);
        fieldsBox.innerHTML = "";
        (t?.fields || []).forEach((f) => {
          const wrap = document.createElement("div");
          wrap.className = "form-row";
          const req = f.required ? "required" : "";
          if (f.field_type === "select" && f.options?.length) {
            wrap.innerHTML = `
              <label>${escapeHtml(f.label)}${f.required ? " *" : ""}</label>
              <select name="field_${f.id}" ${req}>
                <option value="">Bitte wählen …</option>
                ${f.options.map((o) => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join("")}
              </select>
              ${f.description ? `<div class="help">${escapeHtml(f.description)}</div>` : ""}
            `;
          } else if (f.field_type === "long") {
            wrap.innerHTML = `
              <label>${escapeHtml(f.label)}${f.required ? " *" : ""}</label>
              <textarea name="field_${f.id}" placeholder="${escapeHtml(f.placeholder || "")}" ${req}
                minlength="${f.min_length || 0}" maxlength="${f.max_length || 1000}"></textarea>
              ${f.description ? `<div class="help">${escapeHtml(f.description)}</div>` : ""}
            `;
          } else {
            wrap.innerHTML = `
              <label>${escapeHtml(f.label)}${f.required ? " *" : ""}</label>
              <input type="text" name="field_${f.id}" placeholder="${escapeHtml(f.placeholder || "")}" ${req}
                minlength="${f.min_length || 0}" maxlength="${f.max_length || 200}">
              ${f.description ? `<div class="help">${escapeHtml(f.description)}</div>` : ""}
            `;
          }
          fieldsBox.appendChild(wrap);
        });
      });
    });
  }

  // Embed live preview
  const preview = document.getElementById("embed-live-preview");
  if (preview) {
    const sync = () => {
      const color = document.querySelector("[name=embed_color]")?.value || "#9B5CFF";
      const title = document.querySelector("[name=embed_title]")?.value || "";
      const desc = document.querySelector("[name=embed_description]")?.value || "";
      const footer = document.querySelector("[name=footer_text]")?.value || "";
      preview.style.borderLeftColor = color;
      preview.querySelector(".title").textContent = title;
      preview.querySelector(".desc").textContent = desc;
      preview.querySelector(".footer").textContent = footer;
    };
    ["embed_color", "embed_title", "embed_description", "footer_text"].forEach((n) => {
      document.querySelector(`[name=${n}]`)?.addEventListener("input", sync);
    });
    sync();
  }

  // Global refresh button
  document.querySelectorAll("[data-refresh-discord]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const res = await fetch("/api/cache/refresh", {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken },
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "Fehler");
        cache.roles = null;
        cache.channels = {};
        btn.textContent = "Aktualisiert ✓";
        setTimeout(() => {
          btn.textContent = "Aktualisieren";
          btn.disabled = false;
        }, 1500);
      } catch (e) {
        btn.textContent = "Fehler";
        btn.disabled = false;
      }
    });
  });
})();
