(() => {
  "use strict";

  const root = document.querySelector(".dashboard-shell");
  if (!root) return;

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const state = {
    resources: { roles: [], channels: [], members: [] },
    ticketTypes: [],
    grants: [],
  };

  const escapeHtml = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
    })[char]);

  const api = async (url, options = {}) => {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body && typeof options.body !== "string") {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    if (!["GET", "HEAD"].includes((options.method || "GET").toUpperCase())) {
      headers["X-CSRFToken"] = csrf;
    }
    const response = await fetch(url, { credentials: "same-origin", ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || "Die Anfrage ist fehlgeschlagen.");
    return data;
  };

  const toast = (message, type = "success") => {
    const stack = document.querySelector("[data-toasts]");
    if (!stack) return;
    const item = document.createElement("div");
    item.className = `toast toast-${type}`;
    item.innerHTML = `<span class="toast-dot"></span><span>${escapeHtml(message)}</span>`;
    stack.append(item);
    window.setTimeout(() => item.remove(), 5100);
  };

  const busy = (button, active) => {
    if (!button) return;
    if (active) {
      button.dataset.label = button.innerHTML;
      button.innerHTML = "Bitte warten …";
      button.disabled = true;
    } else {
      button.innerHTML = button.dataset.label || button.innerHTML;
      button.disabled = false;
    }
  };

  const formatDate = (value) => {
    if (!value) return "–";
    return new Intl.DateTimeFormat("de-DE", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    }).format(new Date(value));
  };

  const relativeTime = (value) => {
    if (!value) return "";
    const seconds = Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
    if (seconds < 60) return "gerade eben";
    if (seconds < 3600) return `vor ${Math.floor(seconds / 60)} Min.`;
    if (seconds < 86400) return `vor ${Math.floor(seconds / 3600)} Std.`;
    return `vor ${Math.floor(seconds / 86400)} Tag(en)`;
  };

  function initializePickers() {
    document.querySelectorAll(".resource-picker").forEach((picker) => {
      picker._selected = [];
      const trigger = picker.querySelector(".picker-trigger");
      const search = picker.querySelector(".picker-search");
      trigger.addEventListener("click", (event) => {
        event.stopPropagation();
        document.querySelectorAll(".resource-picker.open").forEach((open) => {
          if (open !== picker) open.classList.remove("open");
        });
        picker.classList.toggle("open");
        trigger.setAttribute("aria-expanded", String(picker.classList.contains("open")));
        if (picker.classList.contains("open")) {
          renderPicker(picker);
          window.setTimeout(() => search.focus(), 20);
        }
      });
      search.addEventListener("input", () => renderPicker(picker));
      picker.querySelector(".picker-menu").addEventListener("click", (event) => event.stopPropagation());
    });
    document.addEventListener("click", () => {
      document.querySelectorAll(".resource-picker.open").forEach((picker) => {
        picker.classList.remove("open");
        picker.querySelector(".picker-trigger").setAttribute("aria-expanded", "false");
      });
    });
  }

  function availableForPicker(picker) {
    const type = picker.dataset.resource;
    const filters = (picker.dataset.filters || "").split(",").filter(Boolean);
    let items = state.resources[type] || [];
    if (type === "channels" && filters.length) {
      items = items.filter((item) => filters.includes(item.type));
    }
    if (type === "roles") items = items.filter((item) => item.usable !== false);
    return items;
  }

  function renderPicker(picker) {
    const options = picker.querySelector(".picker-options");
    const empty = picker.querySelector(".picker-empty");
    const query = picker.querySelector(".picker-search").value.trim().toLocaleLowerCase("de");
    const items = availableForPicker(picker).filter((item) => {
      const text = `${item.name || ""} ${item.username || ""}`.toLocaleLowerCase("de");
      return text.includes(query);
    });
    options.innerHTML = items.map((item) => {
      const selected = picker._selected.includes(String(item.id));
      const meta = item.type ? item.type : (item.username && item.username !== item.name ? `@${item.username}` : "");
      return `<button type="button" class="picker-option ${selected ? "selected" : ""}" data-value="${escapeHtml(item.id)}">
        <i></i><span>${escapeHtml(item.name)}</span><small>${escapeHtml(meta)}</small>${selected ? "<b>✓</b>" : ""}
      </button>`;
    }).join("");
    empty.classList.toggle("visible", items.length === 0);
    options.querySelectorAll(".picker-option").forEach((option) => {
      option.addEventListener("click", () => selectPickerValue(picker, option.dataset.value));
    });
  }

  function selectPickerValue(picker, value) {
    const multiple = picker.dataset.multiple === "true";
    if (multiple) {
      picker._selected = picker._selected.includes(value)
        ? picker._selected.filter((entry) => entry !== value)
        : [...picker._selected, value];
    } else {
      picker._selected = [value];
      picker.classList.remove("open");
    }
    syncPicker(picker);
    renderPicker(picker);
  }

  function setPickerValue(picker, value) {
    if (!picker) return;
    const values = Array.isArray(value) ? value : (value ? [value] : []);
    picker._selected = values.map(String);
    syncPicker(picker);
  }

  function syncPicker(picker) {
    const multiple = picker.dataset.multiple === "true";
    const items = availableForPicker(picker);
    const selectedItems = picker._selected
      .map((id) => items.find((item) => String(item.id) === String(id)))
      .filter(Boolean);
    picker._selected = selectedItems.map((item) => String(item.id));
    const hidden = picker.querySelector('input[type="hidden"]');
    hidden.value = multiple ? JSON.stringify(picker._selected) : (picker._selected[0] || "");
    picker.querySelector(".picker-value").textContent = multiple
      ? (selectedItems.length ? `${selectedItems.length} ausgewählt` : "Auswählen …")
      : (selectedItems[0]?.name || "Auswählen …");
    const tags = picker.querySelector(".picker-tags");
    tags.innerHTML = multiple ? selectedItems.map((item) =>
      `<span class="picker-tag">${escapeHtml(item.name)}<button type="button" data-remove="${escapeHtml(item.id)}">×</button></span>`
    ).join("") : "";
    if (multiple && selectedItems.length > 1) {
      tags.insertAdjacentHTML("beforeend", '<button type="button" class="picker-clear">Alle entfernen</button>');
    }
    tags.querySelectorAll("[data-remove]").forEach((button) => button.addEventListener("click", () => {
      picker._selected = picker._selected.filter((id) => id !== button.dataset.remove);
      syncPicker(picker);
    }));
    tags.querySelector(".picker-clear")?.addEventListener("click", () => {
      picker._selected = [];
      syncPicker(picker);
    });
    hidden.dispatchEvent(new CustomEvent("pickerchange", { bubbles: true, detail: selectedItems }));
  }

  async function loadResources() {
    try {
      const data = await api("/api/resources");
      state.resources = {
        roles: data.roles || [],
        channels: data.channels || [],
        members: data.members || [],
      };
      document.querySelectorAll(".resource-picker").forEach((picker) => {
        const current = [...(picker._selected || [])];
        setPickerValue(picker, current);
        renderPicker(picker);
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function serializeForm(form) {
    const data = {};
    form.querySelectorAll("[name]").forEach((input) => {
      if (input.disabled || input.name.endsWith("_picker")) return;
      if (input.type === "checkbox") {
        data[input.name] = input.checked;
      } else if (input.type === "number") {
        data[input.name] = input.value === "" ? 0 : Number(input.value);
      } else if (input.closest(".resource-picker")?.dataset.multiple === "true") {
        try { data[input.name] = JSON.parse(input.value || "[]"); } catch { data[input.name] = []; }
      } else {
        data[input.name] = input.value;
      }
    });
    return data;
  }

  function fillForm(form, values) {
    Object.entries(values || {}).forEach(([name, value]) => {
      const input = form.elements.namedItem(name);
      if (!input) return;
      const picker = input.closest?.(".resource-picker");
      if (picker) {
        setPickerValue(picker, value);
      } else if (input.type === "checkbox") {
        input.checked = Boolean(value);
      } else {
        input.value = value ?? "";
      }
    });
    form.querySelectorAll('input[name$="_picker"]').forEach((color) => {
      const text = form.elements.namedItem(color.name.replace("_picker", ""));
      if (text?.value) color.value = text.value;
    });
    form.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function setupColorInputs() {
    document.querySelectorAll(".color-input").forEach((wrap) => {
      const picker = wrap.querySelector('input[type="color"]');
      const text = wrap.querySelector('input:not([type="color"])');
      picker.addEventListener("input", () => {
        text.value = picker.value;
        text.dispatchEvent(new Event("input", { bubbles: true }));
      });
      text.addEventListener("input", () => {
        if (/^#[0-9a-f]{6}$/i.test(text.value)) picker.value = text.value;
      });
    });
  }

  async function loadOverview() {
    try {
      const data = await api("/api/overview");
      Object.entries(data.stats || {}).forEach(([name, value]) => {
        document.querySelectorAll(`[data-stat="${name}"]`).forEach((element) => {
          element.textContent = Number(value).toLocaleString("de-DE");
        });
      });
      document.querySelectorAll("[data-open-ticket-badge]").forEach((badge) => {
        badge.textContent = data.stats?.open_tickets ?? 0;
      });
      const serverName = document.querySelector("[data-server-name]");
      const botState = document.querySelector("[data-bot-state]");
      if (serverName) serverName.textContent = data.server.guild_name || "Discord Server";
      if (botState) botState.textContent = data.server.online ? `${data.server.latency_ms} ms · online` : "Bot offline";
      document.querySelectorAll("[data-connection]").forEach((element) => {
        element.textContent = data.server.online ? "Bot verbunden" : "Bot nicht verbunden";
        element.closest(".connection-pill")?.classList.toggle("offline", !data.server.online);
      });
      const icon = document.querySelector("[data-server-icon]");
      if (icon && data.server.guild_icon) icon.innerHTML = `<img src="${escapeHtml(data.server.guild_icon)}" alt="">`;
      document.querySelectorAll("[data-last-update]").forEach((item) => item.textContent = "gerade eben");
      renderChart(data.chart || []);
      renderActivity(data.recent_activity || []);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function renderChart(points) {
    const target = document.querySelector("[data-chart]");
    if (!target || !points.length) return;
    const width = 700;
    const height = 220;
    const padding = { top: 18, right: 20, bottom: 27, left: 25 };
    const max = Math.max(4, ...points.map((point) => Number(point.tickets)));
    const x = (index) => padding.left + index * ((width - padding.left - padding.right) / Math.max(1, points.length - 1));
    const y = (value) => padding.top + (height - padding.top - padding.bottom) * (1 - value / max);
    const line = points.map((point, index) => `${index ? "L" : "M"}${x(index)},${y(point.tickets)}`).join(" ");
    const area = `${line} L${x(points.length - 1)},${height - padding.bottom} L${x(0)},${height - padding.bottom} Z`;
    const grids = [0, .25, .5, .75, 1].map((fraction) => {
      const yy = padding.top + fraction * (height - padding.top - padding.bottom);
      return `<line class="axis-line" x1="${padding.left}" y1="${yy}" x2="${width - padding.right}" y2="${yy}"/>`;
    }).join("");
    target.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-label="Ticket-Diagramm">
      <defs><linearGradient id="dashboard-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#9f70ff" stop-opacity=".35"/><stop offset="100%" stop-color="#9f70ff" stop-opacity="0"/></linearGradient></defs>
      ${grids}<path class="area" d="${area}"/><path class="line" d="${line}"/>
      ${points.map((point, index) => `<circle class="dot" cx="${x(index)}" cy="${y(point.tickets)}" r="4"><title>${point.tickets} Tickets</title></circle><text x="${x(index)}" y="${height - 6}" text-anchor="middle">${escapeHtml(point.label)}</text>`).join("")}
    </svg>`;
  }

  function renderActivity(items) {
    const target = document.querySelector("[data-activity-list]");
    if (!target) return;
    target.innerHTML = items.length ? items.map((item) => `
      <div class="activity-item"><span class="activity-icon">✦</span><div><b>${escapeHtml(item.action)}</b><small>${escapeHtml(item.actor_name)} · ${escapeHtml(item.area)}</small></div><span class="activity-time">${relativeTime(item.created_at)}</span></div>
    `).join("") : '<div class="empty-state small">Noch keine Dashboard-Aktivität.</div>';
  }

  async function loadTicketTypes(selectFirst = true) {
    const data = await api("/api/ticket-types");
    state.ticketTypes = data.items || [];
    const count = document.querySelector("[data-ticket-type-count]");
    if (count) count.textContent = state.ticketTypes.length;
    const list = document.querySelector("[data-ticket-type-list]");
    if (list) {
      list.innerHTML = state.ticketTypes.length ? state.ticketTypes.map((item) => `
        <button type="button" class="type-item" data-ticket-type="${item.id}">
          <span class="type-emoji">${escapeHtml(item.emoji)}</span><span><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.description || "Keine Beschreibung")}</small></span><i class="type-state ${item.enabled ? "" : "off"}"></i>
        </button>`).join("") : '<div class="empty-state">Noch keine Ticket-Art angelegt.</div>';
      list.querySelectorAll("[data-ticket-type]").forEach((button) => button.addEventListener("click", () => editTicketType(Number(button.dataset.ticketType))));
    }
    populateWebTicketTypes();
    if (selectFirst && state.ticketTypes.length && document.querySelector("[data-ticket-editor]")) {
      editTicketType(state.ticketTypes[0].id);
    }
  }

  function editTicketType(id) {
    const item = state.ticketTypes.find((entry) => entry.id === id);
    const form = document.querySelector('[data-form="ticket-type"]');
    if (!form || !item) return;
    fillForm(form, item);
    renderFormFields(item.form_fields || []);
    document.querySelector("[data-editor-title]").textContent = item.name;
    document.querySelectorAll("[data-ticket-type]").forEach((button) => button.classList.toggle("active", Number(button.dataset.ticketType) === id));
  }

  function newTicketType() {
    const form = document.querySelector('[data-form="ticket-type"]');
    if (!form) return;
    form.reset();
    fillForm(form, {
      id: "", emoji: "🎫", color: "#8b5cf6", enabled: true,
      max_open_per_user: 1, cooldown_minutes: 10, inactivity_hours: 72,
      greeting: "Willkommen {mention}! Das Team ist gleich für dich da.",
    });
    document.querySelectorAll("[data-ticket-type]").forEach((button) => button.classList.remove("active"));
    document.querySelector("[data-editor-title]").textContent = "Neue Ticket-Art";
    renderFormFields([{ id: crypto.randomUUID(), label: "Wie können wir helfen?", type: "long", required: true, placeholder: "", min_length: 1, max_length: 1000 }]);
    form.querySelector('[name="name"]').focus();
  }

  function renderFormFields(fields) {
    const target = document.querySelector("[data-form-fields]");
    if (!target) return;
    target.innerHTML = fields.map((field) => `
      <div class="form-field-row" data-field-id="${escapeHtml(field.id || crypto.randomUUID())}">
        <input data-field="label" maxlength="45" required value="${escapeHtml(field.label)}" placeholder="Frage">
        <select data-field="type"><option value="short" ${field.type !== "long" ? "selected" : ""}>Kurz</option><option value="long" ${field.type === "long" ? "selected" : ""}>Lang</option></select>
        <label class="permission-check"><input type="checkbox" data-field="required" ${field.required ? "checked" : ""}> Pflicht</label>
        <button type="button" class="remove-row" title="Feld entfernen">×</button>
      </div>`).join("");
    target.querySelectorAll(".remove-row").forEach((button) => button.addEventListener("click", () => button.closest(".form-field-row").remove()));
  }

  function collectFormFields() {
    return [...document.querySelectorAll("[data-form-fields] .form-field-row")].map((row) => ({
      id: row.dataset.fieldId,
      label: row.querySelector('[data-field="label"]').value,
      type: row.querySelector('[data-field="type"]').value,
      required: row.querySelector('[data-field="required"]').checked,
      placeholder: "",
      min_length: 0,
      max_length: row.querySelector('[data-field="type"]').value === "long" ? 1000 : 200,
    }));
  }

  async function submitTicketType(form, button) {
    const data = serializeForm(form);
    const id = data.id;
    delete data.id;
    data.form_fields = collectFormFields();
    busy(button, true);
    try {
      const result = await api(id ? `/api/ticket-types/${id}` : "/api/ticket-types", {
        method: id ? "PUT" : "POST", body: data,
      });
      toast(result.message);
      await loadTicketTypes(false);
      editTicketType(result.item.id);
    } catch (error) { toast(error.message, "error"); } finally { busy(button, false); }
  }

  async function deleteTicketType() {
    const id = document.querySelector('[data-form="ticket-type"] [name="id"]')?.value;
    if (!id || !window.confirm("Diese Ticket-Art wirklich löschen?")) return;
    try {
      const result = await api(`/api/ticket-types/${id}`, { method: "DELETE" });
      toast(result.message);
      await loadTicketTypes();
    } catch (error) { toast(error.message, "error"); }
  }

  async function loadTickets() {
    const targets = document.querySelectorAll("[data-ticket-list]");
    if (!targets.length) return;
    try {
      const data = await api("/api/tickets");
      const html = data.items?.length ? data.items.map((item) => `
        <div class="ticket-row"><div><b>${escapeHtml(item.number)}</b><small>${escapeHtml(item.type)}</small></div><div><b>${escapeHtml(item.creator_name)}</b><small>${formatDate(item.created_at)}</small></div><span class="status-label ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span><div><b>${escapeHtml(item.claimed_by_name || "Nicht übernommen")}</b><small>${escapeHtml(item.priority)}</small></div>${!["closed","archived"].includes(item.status) ? `<button class="text-button" type="button" data-close-ticket="${item.id}">Schließen</button>` : "<span></span>"}</div>
      `).join("") : '<div class="empty-state">Keine Tickets vorhanden.</div>';
      targets.forEach((target) => {
        target.innerHTML = html;
        target.querySelectorAll("[data-close-ticket]").forEach((button) => button.addEventListener("click", () => closeTicket(button.dataset.closeTicket)));
      });
    } catch (error) { targets.forEach((target) => target.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`); }
  }

  async function closeTicket(id) {
    const reason = window.prompt("Warum wird das Ticket geschlossen?", "Im Dashboard geschlossen");
    if (reason === null) return;
    try {
      const result = await api(`/api/tickets/${id}/close`, { method: "POST", body: { reason } });
      toast(result.message);
      loadTickets();
      loadOverview();
    } catch (error) { toast(error.message, "error"); }
  }

  function populateWebTicketTypes() {
    const select = document.querySelector("[data-web-ticket-types]");
    if (!select) return;
    const enabled = state.ticketTypes.filter((item) => item.enabled);
    select.innerHTML = enabled.map((item) => `<option value="${item.id}">${escapeHtml(item.emoji)} ${escapeHtml(item.name)}</option>`).join("");
    select.onchange = renderWebTicketFields;
    renderWebTicketFields();
  }

  function renderWebTicketFields() {
    const select = document.querySelector("[data-web-ticket-types]");
    const target = document.querySelector("[data-web-ticket-fields]");
    if (!select || !target) return;
    const item = state.ticketTypes.find((entry) => String(entry.id) === select.value);
    target.innerHTML = (item?.form_fields || []).map((field) => `
      <div class="field"><label>${escapeHtml(field.label)}</label>${field.type === "long"
        ? `<textarea data-answer="${escapeHtml(field.id)}" rows="4" maxlength="${field.max_length || 1000}" ${field.required ? "required" : ""}></textarea>`
        : `<input data-answer="${escapeHtml(field.id)}" maxlength="${field.max_length || 200}" ${field.required ? "required" : ""}>`
      }</div>`).join("");
  }

  async function loadSettings(area) {
    const form = document.querySelector(`[data-form="settings"][data-area="${area}"]`);
    if (!form) return;
    try {
      const data = await api(`/api/settings/${area}`);
      fillForm(form, data.settings);
    } catch (error) { toast(error.message, "error"); }
  }

  async function saveSettings(form, button) {
    const area = form.dataset.area;
    busy(button, true);
    try {
      const result = await api(`/api/settings/${area}`, { method: "PUT", body: serializeForm(form) });
      toast(result.bot_online === false ? "Gespeichert – der Bot übernimmt es beim Verbinden." : result.message);
    } catch (error) { toast(error.message, "error"); } finally { busy(button, false); }
  }

  async function loadWordFilters() {
    const target = document.querySelector("[data-word-filter-list]");
    if (!target) return;
    try {
      const data = await api("/api/word-filters");
      target.innerHTML = data.items.length ? data.items.map((item) => `
        <div class="filter-item"><span class="type-emoji">Aa</span><div><b>${escapeHtml(item.phrase)}</b><small>${escapeHtml(item.match_type)} · ${escapeHtml(item.action)}</small></div><button type="button" data-delete-filter="${item.id}" title="Löschen">×</button></div>
      `).join("") : '<div class="empty-state">Noch keine individuellen Wortfilter.</div>';
      target.querySelectorAll("[data-delete-filter]").forEach((button) => button.addEventListener("click", async () => {
        try {
          const result = await api(`/api/word-filters/${button.dataset.deleteFilter}`, { method: "DELETE" });
          toast(result.message); loadWordFilters();
        } catch (error) { toast(error.message, "error"); }
      }));
    } catch (error) { target.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`; }
  }

  async function loadModeration() {
    const target = document.querySelector("[data-case-list]");
    if (!target) return;
    try {
      const data = await api("/api/moderation");
      target.innerHTML = data.items.length ? data.items.map((item) => `
        <div class="case-item"><span class="case-action">${escapeHtml(item.action)}</span><div><b>${escapeHtml(item.user_name)} · ${escapeHtml(item.case_number)}</b><small>${escapeHtml(item.reason)} · ${formatDate(item.created_at)}</small></div></div>
      `).join("") : '<div class="empty-state">Noch keine Moderationsfälle.</div>';
    } catch (error) { target.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`; }
  }

  function setupEmbedPreview() {
    const form = document.querySelector('[data-form="embed"]');
    if (!form) return;
    const render = () => {
      ["content", "title", "description", "footer"].forEach((name) => {
        const preview = document.querySelector(`[data-embed-preview="${name}"]`);
        if (preview) preview.textContent = form.elements[name].value || ({ title: "Dein Embed-Titel", description: "Die Vorschau aktualisiert sich während du schreibst.", footer: "zyrahd.net" }[name] || "");
      });
      const card = document.querySelector("[data-embed-card]");
      card?.style.setProperty("--preview-color", form.elements.color.value || "#8b5cf6");
      const image = document.querySelector("[data-embed-preview-image]");
      if (image) {
        image.src = form.elements.image_url.value || "";
        image.classList.toggle("visible", Boolean(form.elements.image_url.value));
      }
    };
    form.addEventListener("input", render);
    render();
  }

  function setupWelcomePreview() {
    const form = document.querySelector('[data-area="welcome"]');
    if (!form) return;
    const render = () => {
      const title = document.querySelector('[data-preview="title"]');
      const message = document.querySelector('[data-preview="message"]');
      if (title) title.textContent = (form.elements.title.value || "Willkommen bei {server}").replaceAll("{server}", "Zyrahd Community");
      if (message) message.textContent = (form.elements.message.value || "Willkommen {mention}!").replaceAll("{mention}", "@User").replaceAll("{server}", "Zyrahd Community").replaceAll("{member_count}", "8.429");
      document.querySelector(".discord-embed")?.style.setProperty("--preview-color", form.elements.color.value || "#8b5cf6");
    };
    form.addEventListener("input", render);
    render();
  }

  async function loadAnnouncements() {
    const target = document.querySelector("[data-announcement-list]");
    if (!target) return;
    try {
      const data = await api("/api/announcements");
      target.innerHTML = data.items.length ? data.items.map((item) => `
        <div class="announcement-item"><span class="priority-pill ${escapeHtml(item.priority)}">${escapeHtml(item.priority)}</span><div><b>${escapeHtml(item.title)}</b><small>${escapeHtml(item.created_by_name)} · ${formatDate(item.created_at)}</small></div><span class="type-state ${item.published ? "" : "off"}"></span></div>
      `).join("") : '<div class="empty-state">Noch keine Team-Ankündigung.</div>';
    } catch (error) { target.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`; }
  }

  async function loadPermissions() {
    const target = document.querySelector("[data-grant-list]");
    const checks = document.querySelector("[data-permission-checks]");
    if (!target || !checks) return;
    try {
      const data = await api("/api/permissions");
      state.grants = data.items || [];
      state.availablePermissions = data.available || {};
      checks.innerHTML = Object.entries(data.available).map(([key, label]) => `<label class="permission-check"><input type="checkbox" name="permissions" value="${escapeHtml(key)}"> ${escapeHtml(label)}</label>`).join("");
      target.innerHTML = state.grants.length ? state.grants.map((grant) => `
        <div class="grant-item" data-grant="${grant.id}"><span class="grant-role">@</span><div><b>${escapeHtml(grant.role_name)}</b><small>${grant.permissions.length} Berechtigung(en)</small></div><span>→</span></div>
      `).join("") : '<div class="empty-state">Noch keine Dashboard-Rolle zugewiesen.</div>';
      target.querySelectorAll("[data-grant]").forEach((item) => item.addEventListener("click", () => editGrant(Number(item.dataset.grant))));
    } catch (error) { target.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`; }
  }

  function editGrant(id) {
    const grant = state.grants.find((entry) => entry.id === id);
    const form = document.querySelector('[data-form="permissions"]');
    if (!grant || !form) return;
    setPickerValue(form.querySelector(".resource-picker"), grant.role_id);
    form.elements.role_name.value = grant.role_name;
    form.querySelectorAll('[name="permissions"]').forEach((input) => { input.checked = grant.permissions.includes(input.value); });
  }

  async function loadAudit() {
    const target = document.querySelector("[data-audit-list]");
    if (!target) return;
    try {
      const data = await api("/api/audit");
      target.innerHTML = data.items.length ? data.items.map((item) => `<tr><td>${formatDate(item.created_at)}</td><td>${escapeHtml(item.actor_name)}</td><td>${escapeHtml(item.area)}</td><td>${escapeHtml(item.action)}</td><td>${escapeHtml(item.target || "–")}</td></tr>`).join("") : '<tr><td colspan="5"><div class="empty-state">Noch keine Änderungen protokolliert.</div></td></tr>';
    } catch (error) { target.innerHTML = `<tr><td colspan="5"><div class="empty-state">${escapeHtml(error.message)}</div></td></tr>`; }
  }

  function setupActions() {
    document.querySelectorAll('[data-action="toggle-sidebar"]').forEach((button) => button.addEventListener("click", () => document.querySelector("#sidebar")?.classList.toggle("open")));
    document.querySelectorAll('[data-action="refresh"]').forEach((button) => button.addEventListener("click", () => window.location.reload()));
    document.querySelector('[data-action="new-ticket-type"]')?.addEventListener("click", newTicketType);
    document.querySelector('[data-action="delete-ticket-type"]')?.addEventListener("click", deleteTicketType);
    document.querySelector('[data-action="add-form-field"]')?.addEventListener("click", () => {
      const rows = document.querySelectorAll("[data-form-fields] .form-field-row");
      if (rows.length >= 5) return toast("Discord unterstützt maximal fünf Formularfelder.", "error");
      const fields = [...rows].map((row) => ({
        id: row.dataset.fieldId,
        label: row.querySelector('[data-field="label"]').value,
        type: row.querySelector('[data-field="type"]').value,
        required: row.querySelector('[data-field="required"]').checked,
      }));
      fields.push({ id: crypto.randomUUID(), label: "", type: "short", required: true });
      renderFormFields(fields);
    });
    document.querySelector('[data-action="show-word-filter"]')?.addEventListener("click", () => document.querySelector('[data-form="word-filter"]')?.classList.toggle("visible"));
    document.querySelector('[data-action="publish-verify"]')?.addEventListener("click", async (event) => {
      busy(event.currentTarget, true);
      try { const result = await api("/api/verify/publish", { method: "POST", body: {} }); toast(result.message); }
      catch (error) { toast(error.message, "error"); } finally { busy(event.currentTarget, false); }
    });
    document.querySelector('[data-action="create-web-ticket"]')?.addEventListener("click", () => {
      populateWebTicketTypes();
      const modal = document.querySelector('[data-modal="web-ticket"]');
      modal?.classList.add("open"); modal?.setAttribute("aria-hidden", "false");
    });
    document.querySelectorAll('[data-action="close-modal"]').forEach((button) => button.addEventListener("click", () => {
      const modal = button.closest(".modal") || document.querySelector(".modal.open");
      modal?.classList.remove("open"); modal?.setAttribute("aria-hidden", "true");
    }));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") document.querySelector(".modal.open")?.classList.remove("open");
    });
  }

  function setupForms() {
    document.querySelectorAll("form[data-form]").forEach((form) => form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      const kind = form.dataset.form;
      if (kind === "ticket-type") return submitTicketType(form, button);
      if (kind === "settings") return saveSettings(form, button);
      busy(button, true);
      try {
        let result;
        if (kind === "ticket-panel") result = await api("/api/ticket-panel/publish", { method: "POST", body: serializeForm(form) });
        if (kind === "word-filter") result = await api("/api/word-filters", { method: "POST", body: serializeForm(form) });
        if (kind === "moderation") result = await api("/api/moderation", { method: "POST", body: serializeForm(form) });
        if (kind === "embed") result = await api("/api/embeds/send", { method: "POST", body: serializeForm(form) });
        if (kind === "announcement") result = await api("/api/announcements", { method: "POST", body: serializeForm(form) });
        if (kind === "permissions") {
          const data = serializeForm(form);
          data.permissions = [...form.querySelectorAll('[name="permissions"]:checked')].map((input) => input.value);
          const role = state.resources.roles.find((item) => String(item.id) === String(data.role_id));
          data.role_name = role?.name || data.role_name;
          result = await api("/api/permissions", { method: "PUT", body: data });
        }
        if (kind === "web-ticket") {
          const data = serializeForm(form);
          data.answers = {};
          form.querySelectorAll("[data-answer]").forEach((input) => { data.answers[input.dataset.answer] = input.value; });
          result = await api("/api/tickets", { method: "POST", body: data });
          document.querySelector('[data-modal="web-ticket"]')?.classList.remove("open");
          loadTickets();
        }
        if (result) toast(result.message);
        if (kind === "word-filter") { form.reset(); form.classList.remove("visible"); loadWordFilters(); }
        if (kind === "moderation") loadModeration();
        if (kind === "announcement") { form.reset(); loadAnnouncements(); }
        if (kind === "permissions") loadPermissions();
      } catch (error) { toast(error.message, "error"); } finally { busy(button, false); }
    }));
    document.addEventListener("pickerchange", (event) => {
      const hidden = event.target;
      if (hidden.name === "role_id" && hidden.closest('[data-form="permissions"]')) {
        hidden.form.elements.role_name.value = event.detail[0]?.name || "";
      }
    });
  }

  async function initializePage() {
    initializePickers();
    setupColorInputs();
    setupActions();
    setupForms();
    setupEmbedPreview();
    setupWelcomePreview();
    await Promise.allSettled([loadOverview(), loadResources()]);
    const section = root.dataset.section;
    try {
      if (section === "tickets") await Promise.all([loadTicketTypes(), loadTickets()]);
      if (["welcome", "verify", "security"].includes(section)) await loadSettings(section);
      if (section === "security") await loadWordFilters();
      if (section === "moderation") await loadModeration();
      if (section === "announcements") await loadAnnouncements();
      if (section === "permissions") await loadPermissions();
      if (section === "audit") await loadAudit();
    } catch (error) { toast(error.message, "error"); }
  }

  initializePage();
})();
