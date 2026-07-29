"use strict";

const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
const toastStack = document.getElementById("toast-stack");

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[char]));
}

function toast(message, kind = "success") {
  if (!toastStack) return;
  const item = document.createElement("div");
  item.className = `toast ${kind}`;
  item.textContent = message;
  toastStack.appendChild(item);
  window.setTimeout(() => {
    item.classList.add("out");
    window.setTimeout(() => item.remove(), 260);
  }, 4200);
}

async function api(url, options = {}) {
  const config = { ...options, headers: { ...(options.headers || {}) } };
  if (config.body && typeof config.body !== "string") {
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(config.body);
  }
  if (config.method && config.method !== "GET") config.headers["X-CSRFToken"] = csrf;
  const response = await fetch(url, config);
  let data = {};
  try { data = await response.json(); } catch (_) { data = {}; }
  if (!response.ok) throw new Error(data.error || `Anfrage fehlgeschlagen (${response.status})`);
  return data;
}

document.querySelectorAll(".server-flashes .flash").forEach((item) => {
  toast(item.textContent, item.dataset.category === "error" ? "error" : "success");
});

if (document.body.dataset.page === "dashboard") {
  initDashboard();
}

function initDashboard() {
  const shell = document.querySelector(".app-shell");
  const permissions = new Set(JSON.parse(shell?.dataset.permissions || "[]"));
  const userId = shell?.dataset.userId || "";
  const state = {
    permissions,
    userId,
    resources: { roles: [], channels: [] },
    selectors: [],
    ticketTypes: [],
    tickets: [],
    cases: [],
    audit: [],
    currentTicket: null,
    editingType: null,
    editingFields: [{
      id: "request", label: "Beschreibe deine Anfrage", type: "long",
      required: true, placeholder: "Worum geht es?", min_length: 10, max_length: 1000,
    }],
  };

  class ResourceSelect {
    constructor(root) {
      this.root = root;
      this.button = root.querySelector(":scope > button");
      this.name = root.dataset.name;
      this.types = new Set((root.dataset.types || "").split(","));
      this.multiple = root.dataset.multiple === "true";
      this.selected = [];
      this.menu = null;
      this.button.addEventListener("click", () => this.toggle());
      state.selectors.push(this);
    }
    options() {
      if (this.types.has("role")) {
        return state.resources.roles.map((item) => ({ ...item, type: "role" }));
      }
      return state.resources.channels.filter((item) => this.types.has(item.type));
    }
    label(id) {
      const item = [...state.resources.roles, ...state.resources.channels]
        .find((entry) => String(entry.id) === String(id));
      if (!item) return `Nicht mehr verfügbar (${id})`;
      return `${item.type === "role" || this.types.has("role") ? "@" : "#"}${item.name}`;
    }
    set(value) {
      const values = Array.isArray(value) ? value : (value ? [value] : []);
      this.selected = values.map(String);
      this.renderButton();
      if (this.menu) this.renderOptions();
    }
    value() { return this.multiple ? [...this.selected] : (this.selected[0] || ""); }
    toggle() {
      if (this.menu) return this.close();
      document.querySelectorAll(".resource-select.open").forEach((item) => {
        if (item !== this.root) item._resourceSelect?.close();
      });
      this.open();
    }
    open() {
      this.root.classList.add("open");
      this.menu = document.createElement("div");
      this.menu.className = "resource-menu";
      this.menu.innerHTML = `
        <div class="resource-search"><input aria-label="Suchen" placeholder="🔍 Name suchen …"></div>
        <div class="resource-options"></div>
        <div class="resource-footer">
          <button class="resource-clear" type="button">${this.multiple ? "Alle entfernen" : "Auswahl entfernen"}</button>
          <button class="resource-clear resource-refresh" type="button">↻ Von Discord aktualisieren</button>
        </div>`;
      this.root.appendChild(this.menu);
      this.menu.querySelector("input").addEventListener("input", () => this.renderOptions());
      this.menu.querySelector(".resource-clear").addEventListener("click", () => {
        this.set([]);
        if (!this.multiple) this.close();
      });
      this.menu.querySelector(".resource-refresh").addEventListener("click", async () => {
        try {
          await loadResources(true);
          toast("Rollen und Kanäle wurden aktualisiert.");
          this.renderOptions();
        } catch (error) { toast(error.message, "error"); }
      });
      this.renderOptions();
      this.menu.querySelector("input").focus();
    }
    close() {
      this.menu?.remove();
      this.menu = null;
      this.root.classList.remove("open");
    }
    renderOptions() {
      if (!this.menu) return;
      const term = this.menu.querySelector("input").value.trim().toLocaleLowerCase("de");
      const options = this.options().filter((item) => item.name.toLocaleLowerCase("de").includes(term));
      const target = this.menu.querySelector(".resource-options");
      if (!options.length) {
        target.innerHTML = '<div class="resource-empty">Kein passendes Ergebnis gefunden.</div>';
        return;
      }
      target.innerHTML = options.map((item) => {
        const selected = this.selected.includes(String(item.id));
        const disabled = item.type === "role" && item.usable === false;
        const prefix = item.type === "role" ? "@" : (item.type === "category" ? "▾ " : "#");
        return `<button type="button" class="resource-option ${selected ? "selected" : ""} ${disabled ? "disabled" : ""}" data-id="${escapeHtml(item.id)}" ${disabled ? "disabled" : ""}>
          <i>${selected ? "✓" : (item.type === "role" ? "◉" : "＃")}</i>
          <span>${escapeHtml(prefix + item.name)}</span>
          <b>${disabled ? "Nicht verwendbar" : escapeHtml(item.category || item.type)}</b>
        </button>`;
      }).join("");
      target.querySelectorAll(".resource-option:not(.disabled)").forEach((option) => {
        option.addEventListener("click", () => {
          const id = String(option.dataset.id);
          if (this.multiple) {
            this.selected = this.selected.includes(id)
              ? this.selected.filter((item) => item !== id)
              : [...this.selected, id];
          } else {
            this.selected = [id];
            this.close();
          }
          this.renderButton();
          this.renderOptions();
        });
      });
    }
    renderButton() {
      if (!this.selected.length) {
        this.button.textContent = this.types.has("role") ? "Rolle auswählen …" : "Kanal auswählen …";
      } else if (this.multiple) {
        this.button.textContent = `${this.selected.length} ausgewählt`;
      } else {
        this.button.textContent = this.label(this.selected[0]);
      }
      this.root.querySelector(".resource-tags")?.remove();
      if (this.multiple && this.selected.length) {
        const tags = document.createElement("div");
        tags.className = "resource-tags";
        tags.innerHTML = this.selected.map((id) =>
          `<span class="resource-tag">${escapeHtml(this.label(id))}<button type="button" data-remove="${escapeHtml(id)}">×</button></span>`
        ).join("");
        tags.querySelectorAll("[data-remove]").forEach((button) => {
          button.addEventListener("click", () => {
            this.set(this.selected.filter((id) => id !== button.dataset.remove));
          });
        });
        this.root.appendChild(tags);
      }
    }
  }

  document.querySelectorAll(".resource-select").forEach((root) => {
    const selector = new ResourceSelect(root);
    root._resourceSelect = selector;
  });
  document.addEventListener("click", (event) => {
    state.selectors.forEach((selector) => {
      if (selector.menu && !selector.root.contains(event.target)) selector.close();
    });
  });

  function selector(form, name) {
    return state.selectors.find((item) => item.name === name && form.contains(item.root));
  }

  function gatherForm(form) {
    const data = {};
    form.querySelectorAll("input[name], textarea[name], select[name]").forEach((input) => {
      if (input.type === "checkbox") data[input.name] = input.checked;
      else if (input.type === "number") data[input.name] = input.value === "" ? null : Number(input.value);
      else data[input.name] = input.value;
    });
    state.selectors.filter((item) => form.contains(item.root)).forEach((item) => {
      data[item.name] = item.value();
    });
    return data;
  }

  function fillForm(form, data) {
    form.querySelectorAll("input[name], textarea[name], select[name]").forEach((input) => {
      if (!(input.name in data)) return;
      if (input.type === "checkbox") input.checked = Boolean(data[input.name]);
      else input.value = data[input.name] ?? "";
    });
    state.selectors.filter((item) => form.contains(item.root)).forEach((item) => {
      item.set(data[item.name] ?? []);
    });
    form.dataset.initial = JSON.stringify(data);
  }

  async function loadResources(force = false) {
    if (!permissions.has("dashboard.open")) return;
    if (!force && state.resources.roles.length) return;
    const data = await api("/api/discord/resources");
    state.resources = data;
    state.selectors.forEach((item) => item.renderButton());
  }

  const pageTitles = {
    overview: "Dashboard", "my-tickets": "Meine Tickets", tickets: "Ticket-Zentrale",
    welcome: "Willkommen", verify: "Verifizierung", security: "Sicherheit",
    moderation: "Moderation", designer: "Embed-Designer", team: "Team",
    permissions: "Berechtigungen", audit: "Audit-Log",
  };

  function navigate(name, updateHash = true) {
    const section = document.querySelector(`[data-page-section="${name}"]`);
    if (!section) return;
    document.querySelectorAll(".page-section").forEach((item) => item.classList.toggle("active", item === section));
    document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.section === name));
    document.getElementById("page-title").textContent = pageTitles[name] || "Dashboard";
    document.getElementById("sidebar").classList.remove("open");
    if (updateHash) history.replaceState(null, "", `#${name}`);
    loadSection(name);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => navigate(item.dataset.section)));
  document.querySelectorAll("[data-goto]").forEach((item) => item.addEventListener("click", () => navigate(item.dataset.goto)));
  document.getElementById("mobile-menu")?.addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));

  document.querySelectorAll("[data-open-dialog]").forEach((button) => {
    button.addEventListener("click", () => document.getElementById(button.dataset.openDialog)?.showModal());
  });
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog")?.close());
  });
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  async function loadSection(name) {
    try {
      if (name === "overview") await loadOverview();
      if (name === "my-tickets") await Promise.all([loadTicketTypes(), loadMyTickets()]);
      if (name === "tickets") await Promise.all([loadTickets(), loadTicketTypes()]);
      if (["tickets", "welcome", "verify", "security", "designer", "team", "permissions"].includes(name)) await loadResources();
      if (name === "tickets" && permissions.has("tickets.edit")) await loadSettings("ticket_panel");
      if (name === "welcome" || name === "verify" || name === "security") await loadSettings(name);
      if (name === "security") await loadWordFilters();
      if (name === "moderation") await loadCases();
      if (name === "team") await loadAnnouncements();
      if (name === "permissions") await loadPermissions();
      if (name === "audit") await loadAudit();
    } catch (error) { toast(error.message, "error"); }
  }

  async function loadOverview() {
    const data = await api("/api/overview");
    const values = [
      ["Mitglieder", data.stats.members, "Gesamt auf dem Server", "♢", ""],
      ["Online", data.stats.online, "Gerade aktiv", "●", "green"],
      ["Offene Tickets", data.stats.open_tickets, "Benötigen Aufmerksamkeit", "◫", "purple"],
      ["Heute erstellt", data.stats.today_tickets, `${data.stats.sanctions_today} Sanktionen heute`, "＋", "rose"],
    ];
    document.getElementById("stats-grid").innerHTML = values.map(([label, value, copy, icon, color]) =>
      `<article class="stat-card"><span>${label}</span><strong>${Number(value).toLocaleString("de-DE")}</strong><small>${escapeHtml(copy)}</small><i class="stat-icon ${color}">${icon}</i></article>`
    ).join("");
    const activity = document.getElementById("activity-list");
    activity.innerHTML = data.activity.length ? data.activity.map((item) =>
      `<div class="activity-item"><span class="activity-icon">✦</span><div><strong>${escapeHtml(item.user)} · ${escapeHtml(item.action)}</strong><small>${escapeHtml(item.area)}</small></div><span class="activity-time">${relativeDate(item.created_at)}</span></div>`
    ).join("") : '<div class="empty-state compact">Noch keine Dashboard-Aktivitäten.</div>';
    drawChart(data.chart);
    document.getElementById("my-ticket-badge").textContent = data.stats.open_tickets;
  }

  function drawChart(points) {
    const canvas = document.getElementById("ticket-chart");
    if (!canvas) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = canvas.clientWidth || 600;
    const height = 220;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    const pad = { left: 20, right: 18, top: 20, bottom: 30 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;
    const max = Math.max(4, ...points.map((point) => point.tickets));
    ctx.font = "9px sans-serif";
    ctx.textAlign = "center";
    ctx.fillStyle = "#625b6e";
    points.forEach((point, index) => {
      const x = pad.left + (innerW / Math.max(1, points.length - 1)) * index;
      ctx.fillText(point.date, x, height - 7);
    });
    ctx.strokeStyle = "rgba(255,255,255,.045)";
    for (let i = 0; i < 4; i += 1) {
      const y = pad.top + (innerH / 3) * i;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
    }
    const coordinates = points.map((point, index) => ({
      x: pad.left + (innerW / Math.max(1, points.length - 1)) * index,
      y: pad.top + innerH - (point.tickets / max) * innerH,
    }));
    const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + innerH);
    gradient.addColorStop(0, "rgba(130,94,255,.24)");
    gradient.addColorStop(1, "rgba(130,94,255,0)");
    ctx.beginPath();
    coordinates.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
    ctx.lineTo(coordinates.at(-1)?.x || 0, pad.top + innerH);
    ctx.lineTo(coordinates[0]?.x || 0, pad.top + innerH);
    ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
    ctx.beginPath();
    coordinates.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
    ctx.strokeStyle = "#8d6cff"; ctx.lineWidth = 2; ctx.stroke();
    coordinates.forEach((point) => {
      ctx.beginPath(); ctx.arc(point.x, point.y, 3, 0, Math.PI * 2);
      ctx.fillStyle = "#b09aff"; ctx.fill();
    });
  }

  async function loadTicketTypes(force = false) {
    if (state.ticketTypes.length && !force) return;
    const data = await api("/api/ticket-types");
    state.ticketTypes = data.items;
    renderTicketTypePicker();
    renderTicketTypeAdmin();
  }

  function renderTicketTypePicker() {
    const target = document.getElementById("ticket-type-picker");
    if (!target) return;
    const enabled = state.ticketTypes.filter((item) => item.enabled);
    target.innerHTML = enabled.length ? enabled.map((item) =>
      `<button type="button" class="type-option" data-type-id="${item.id}"><span>${escapeHtml(item.emoji)}</span><div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.description)}</small></div></button>`
    ).join("") : '<div class="empty-state">Aktuell ist keine Ticket-Art aktiviert.</div>';
    target.querySelectorAll("[data-type-id]").forEach((button) => button.addEventListener("click", () => {
      target.querySelectorAll(".type-option").forEach((item) => item.classList.toggle("selected", item === button));
      renderDynamicFields(Number(button.dataset.typeId));
    }));
  }

  function renderDynamicFields(typeId) {
    const type = state.ticketTypes.find((item) => item.id === typeId);
    const target = document.getElementById("dynamic-ticket-fields");
    target.dataset.typeId = typeId;
    const fields = type?.form_fields?.length ? type.form_fields : [{
      id: "request", label: "Beschreibe deine Anfrage", type: "long", required: true, max_length: 1000,
    }];
    target.innerHTML = fields.map((field) =>
      `<label class="field full"><span>${escapeHtml(field.label)}${field.required ? " *" : ""}</span>${field.type === "long"
        ? `<textarea class="input" name="${escapeHtml(field.id)}" rows="4" ${field.required ? "required" : ""} minlength="${field.min_length || 0}" maxlength="${field.max_length || 1000}" placeholder="${escapeHtml(field.placeholder || "")}"></textarea>`
        : `<input class="input" name="${escapeHtml(field.id)}" ${field.required ? "required" : ""} minlength="${field.min_length || 0}" maxlength="${field.max_length || 1000}" placeholder="${escapeHtml(field.placeholder || "")}">`
      }</label>`
    ).join("");
  }

  document.getElementById("new-ticket-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fields = document.getElementById("dynamic-ticket-fields");
    const typeId = Number(fields.dataset.typeId || 0);
    if (!typeId) return toast("Bitte wähle zuerst eine Ticket-Art.", "error");
    const answers = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      const data = await api("/api/tickets", { method: "POST", body: { ticket_type_id: typeId, answers } });
      event.currentTarget.closest("dialog").close();
      event.currentTarget.reset();
      fields.innerHTML = "";
      toast(`Ticket #${data.ticket.id} wurde erstellt.`);
      await loadMyTickets();
    } catch (error) { toast(error.message, "error"); }
  });

  async function loadMyTickets(status = "") {
    const data = await api(`/api/tickets${status ? `?status=${encodeURIComponent(status)}` : ""}`);
    const own = data.items.filter((item) => String(item.creator_id) === state.userId);
    const target = document.getElementById("my-ticket-list");
    if (!target) return;
    target.innerHTML = own.length ? own.map(ticketCard).join("") : '<div class="empty-state">Keine Tickets in dieser Ansicht. Erstelle deine erste Anfrage.</div>';
    target.querySelectorAll("[data-ticket-id]").forEach((item) => item.addEventListener("click", () => openTicket(Number(item.dataset.ticketId))));
  }

  function ticketCard(item) {
    return `<article class="ticket-card" data-ticket-id="${item.id}">
      <div class="ticket-card-top"><span class="ticket-number">TICKET #${item.id}</span><span class="status ${escapeHtml(item.status)}">${statusLabel(item.status)}</span></div>
      <h3>${escapeHtml(item.subject || item.type)}</h3><p>${escapeHtml(item.type)} · ${escapeHtml(item.priority)}</p>
      <div class="ticket-card-foot"><span>${item.assigned_to_name ? `Bearbeitet von ${escapeHtml(item.assigned_to_name)}` : "Noch nicht übernommen"}</span><span>${relativeDate(item.updated_at)}</span></div>
    </article>`;
  }

  document.querySelectorAll("[data-ticket-filter]").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll("[data-ticket-filter]").forEach((item) => item.classList.toggle("active", item === button));
    loadMyTickets(button.dataset.ticketFilter).catch((error) => toast(error.message, "error"));
  }));

  async function loadTickets() {
    const status = document.getElementById("team-ticket-status")?.value || "";
    const data = await api(`/api/tickets${status ? `?status=${status}` : ""}`);
    state.tickets = data.items;
    renderTeamTickets();
  }

  function renderTeamTickets() {
    const target = document.getElementById("team-ticket-list");
    if (!target) return;
    const term = document.getElementById("ticket-search")?.value.toLocaleLowerCase("de") || "";
    const rows = state.tickets.filter((item) =>
      `#${item.id} ${item.creator_name} ${item.type} ${item.subject}`.toLocaleLowerCase("de").includes(term)
    );
    target.innerHTML = rows.length ? rows.map((item) =>
      `<tr data-ticket-id="${item.id}"><td><strong>#${item.id}</strong></td><td>${escapeHtml(item.creator_name)}</td><td>${escapeHtml(item.type)}</td><td class="priority-${escapeHtml(item.priority)}">${escapeHtml(item.priority)}</td><td><span class="status ${escapeHtml(item.status)}">${statusLabel(item.status)}</span></td><td>${relativeDate(item.updated_at)}</td></tr>`
    ).join("") : '<tr><td colspan="6">Keine passenden Tickets.</td></tr>';
    target.querySelectorAll("[data-ticket-id]").forEach((item) => item.addEventListener("click", () => openTicket(Number(item.dataset.ticketId))));
  }

  document.getElementById("ticket-search")?.addEventListener("input", renderTeamTickets);
  document.getElementById("team-ticket-status")?.addEventListener("change", () => loadTickets().catch((error) => toast(error.message, "error")));

  async function openTicket(id) {
    try {
      const data = await api(`/api/tickets/${id}`);
      state.currentTicket = data.ticket;
      document.getElementById("ticket-detail-head").innerHTML = `<div class="ticket-detail-header"><span class="eyebrow small">TICKET #${id}</span><h2>${escapeHtml(data.ticket.subject || data.ticket.type)}</h2><span class="status ${escapeHtml(data.ticket.status)}">${statusLabel(data.ticket.status)}</span> <span class="ticket-number">${escapeHtml(data.ticket.creator_name)} · ${formatDate(data.ticket.created_at)}</span></div>`;
      const formData = document.getElementById("ticket-form-data");
      formData.innerHTML = Object.entries(data.ticket.form_data || {}).map(([key, value]) =>
        `<div class="answer"><span>${escapeHtml(key)}</span><p>${escapeHtml(value)}</p></div>`
      ).join("");
      const messages = document.getElementById("ticket-messages");
      messages.innerHTML = data.messages.length ? data.messages.map((item) =>
        `<div class="message ${item.source === "web" ? "web" : ""}"><div class="message-meta">${escapeHtml(item.author_name)} · ${item.source === "web" ? "Web" : "Discord"} · ${formatDate(item.created_at)}</div><div class="message-bubble">${escapeHtml(item.content)}</div>${(item.attachments || []).map((file) => `<a class="text-link" target="_blank" rel="noopener" href="${escapeHtml(file.url)}">📎 ${escapeHtml(file.name)}</a>`).join("")}</div>`
      ).join("") : '<div class="empty-state compact">Noch keine Nachrichten.</div>';
      messages.scrollTop = messages.scrollHeight;
      document.getElementById("ticket-reply-form").hidden = ["closed", "archived"].includes(data.ticket.status);
      document.getElementById("close-ticket").hidden = ["closed", "archived"].includes(data.ticket.status);
      document.getElementById("ticket-detail-dialog").showModal();
    } catch (error) { toast(error.message, "error"); }
  }

  document.getElementById("ticket-reply-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = event.currentTarget.elements.content.value.trim();
    if (!content || !state.currentTicket) return;
    try {
      await api(`/api/tickets/${state.currentTicket.id}/messages`, { method: "POST", body: { content } });
      event.currentTarget.reset();
      await openTicket(state.currentTicket.id);
    } catch (error) { toast(error.message, "error"); }
  });

  document.getElementById("close-ticket")?.addEventListener("click", async () => {
    if (!state.currentTicket || !confirm("Dieses Ticket wirklich schließen?")) return;
    try {
      await api(`/api/tickets/${state.currentTicket.id}/status`, { method: "POST", body: { status: "closed", reason: "Im Dashboard geschlossen" } });
      toast("Ticket wurde geschlossen.");
      document.getElementById("ticket-detail-dialog").close();
      await Promise.all([loadMyTickets(), permissions.has("tickets.view") ? loadTickets() : Promise.resolve()]);
    } catch (error) { toast(error.message, "error"); }
  });

  function renderTicketTypeAdmin() {
    const target = document.getElementById("ticket-type-admin-list");
    if (!target) return;
    target.innerHTML = state.ticketTypes.map((item) =>
      `<div class="list-item"><span class="list-symbol">${escapeHtml(item.emoji)}</span><div class="list-body"><strong>${escapeHtml(item.name)}</strong><small>${item.enabled ? "Aktiv" : "Deaktiviert"} · ${item.form_fields.length} Felder</small></div><div class="list-actions"><button class="mini-button" data-edit-type="${item.id}">Bearbeiten</button>${permissions.has("tickets.delete") ? `<button class="mini-button delete" data-delete-type="${item.id}">×</button>` : ""}</div></div>`
    ).join("");
    target.querySelectorAll("[data-edit-type]").forEach((button) => button.addEventListener("click", () => {
      const item = state.ticketTypes.find((entry) => entry.id === Number(button.dataset.editType));
      state.editingType = item;
      state.editingFields = structuredClone(item.form_fields || []);
      fillForm(document.getElementById("ticket-type-form"), item);
      renderTicketFields();
    }));
    target.querySelectorAll("[data-delete-type]").forEach((button) => button.addEventListener("click", async () => {
      if (!confirm("Diese Ticket-Art löschen? Bereits verwendete Arten werden sicher deaktiviert.")) return;
      try {
        const data = await api(`/api/ticket-types/${button.dataset.deleteType}`, { method: "DELETE" });
        toast(`Ticket-Art wurde ${data.result}.`);
        state.ticketTypes = [];
        await loadTicketTypes(true);
      } catch (error) { toast(error.message, "error"); }
    }));
  }

  document.getElementById("ticket-type-form")?.addEventListener("reset", () => {
    window.setTimeout(() => {
      state.editingType = null;
      state.editingFields = [{
        id: "request", label: "Beschreibe deine Anfrage", type: "long",
        required: true, placeholder: "Worum geht es?", min_length: 10, max_length: 1000,
      }];
      renderTicketFields();
      state.selectors.filter((item) => document.getElementById("ticket-type-form").contains(item.root)).forEach((item) => item.set([]));
    });
  });

  function renderTicketFields() {
    const target = document.getElementById("ticket-field-list");
    if (!target) return;
    target.innerHTML = state.editingFields.length ? state.editingFields.map((field, index) =>
      `<div class="ticket-field-row" data-field-index="${index}">
        <input class="input" data-key="label" maxlength="80" value="${escapeHtml(field.label || "")}" placeholder="Bezeichnung">
        <select class="input" data-key="type"><option value="short" ${field.type !== "long" ? "selected" : ""}>Kurzer Text</option><option value="long" ${field.type === "long" ? "selected" : ""}>Langer Text</option></select>
        <input class="input" data-key="placeholder" maxlength="100" value="${escapeHtml(field.placeholder || "")}" placeholder="Platzhalter">
        <label class="ticket-field-check"><input type="checkbox" data-key="required" ${field.required ? "checked" : ""}> Pflicht</label>
        <input class="input compact-number" data-key="min_length" type="number" min="0" max="4000" value="${Number(field.min_length || 0)}" title="Mindestlänge">
        <input class="input compact-number" data-key="max_length" type="number" min="1" max="4000" value="${Number(field.max_length || 1000)}" title="Maximallänge">
        <button class="mini-button delete" type="button" data-remove-field="${index}" aria-label="Feld entfernen">×</button>
      </div>`
    ).join("") : '<div class="resource-empty">Noch keine Formularfelder. Ohne Felder wird eine allgemeine Beschreibung abgefragt.</div>';
    target.querySelectorAll(".ticket-field-row").forEach((row) => {
      row.querySelectorAll("[data-key]").forEach((input) => input.addEventListener("input", () => {
        const index = Number(row.dataset.fieldIndex);
        const key = input.dataset.key;
        state.editingFields[index][key] = input.type === "checkbox"
          ? input.checked
          : (input.type === "number" ? Number(input.value) : input.value);
        if (key === "label" && input.value.trim()) {
          state.editingFields[index].id = input.value.trim().toLocaleLowerCase("de")
            .normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
            .replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) || `field_${index + 1}`;
        }
      }));
    });
    target.querySelectorAll("[data-remove-field]").forEach((button) => button.addEventListener("click", () => {
      state.editingFields.splice(Number(button.dataset.removeField), 1);
      renderTicketFields();
    }));
  }

  document.getElementById("add-ticket-field")?.addEventListener("click", () => {
    if (state.editingFields.length >= 20) return toast("Maximal 20 Formularfelder sind möglich.", "error");
    const number = state.editingFields.length + 1;
    state.editingFields.push({
      id: `field_${number}`, label: `Neue Frage ${number}`, type: "short",
      required: false, placeholder: "", min_length: 0, max_length: 1000,
    });
    renderTicketFields();
  });
  renderTicketFields();

  document.getElementById("ticket-type-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = { ...(state.editingType || {}), ...gatherForm(form) };
    payload.form_fields = state.editingFields;
    const id = Number(form.elements.id.value || 0);
    try {
      await api(id ? `/api/ticket-types/${id}` : "/api/ticket-types", { method: id ? "PUT" : "POST", body: payload });
      toast("Ticket-Art wurde gespeichert.");
      form.reset();
      state.editingType = null;
      state.ticketTypes = [];
      await loadTicketTypes(true);
    } catch (error) { toast(error.message, "error"); }
  });

  async function loadSettings(module) {
    if (module === "security") module = "security";
    const form = document.querySelector(`[data-settings-module="${module}"]`);
    if (!form) return;
    const data = await api(`/api/settings/${module}`);
    fillForm(form, data.settings);
    if (module === "welcome") updateWelcomePreview();
  }

  document.querySelectorAll("[data-settings-module]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const module = form.dataset.settingsModule;
      try {
        const data = await api(`/api/settings/${module}`, { method: "PUT", body: gatherForm(form) });
        fillForm(form, data.settings);
        toast("Änderungen wurden gespeichert.");
      } catch (error) { toast(error.message, "error"); }
    });
    form.querySelector("[data-reset-form]")?.addEventListener("click", () => {
      if (form.dataset.initial) fillForm(form, JSON.parse(form.dataset.initial));
    });
  });

  function updateWelcomePreview() {
    const form = document.getElementById("welcome-form");
    const preview = document.getElementById("welcome-preview");
    if (!form || !preview) return;
    const title = form.elements.title.value || "Willkommen!";
    const description = form.elements.description.value || "Deine Nachricht erscheint hier.";
    preview.querySelector("h3").textContent = title.replaceAll("{server}", "Dein Server");
    preview.querySelector(".discord-embed p").textContent = description
      .replaceAll("{mention}", "@Neues Mitglied")
      .replaceAll("{server}", "Dein Server")
      .replaceAll("{member_count}", "1.249")
      .replaceAll("{display_name}", "Neues Mitglied");
    preview.querySelector(".discord-embed > i").style.background = form.elements.color.value;
  }
  document.getElementById("welcome-form")?.addEventListener("input", updateWelcomePreview);

  document.querySelectorAll("[data-publish-panel]").forEach((button) => button.addEventListener("click", async () => {
    const form = button.closest("form");
    const channelId = selector(form, "publish_channel")?.value();
    if (!channelId) return toast("Bitte wähle zuerst einen Panel-Kanal.", "error");
    try {
      if (form.dataset.settingsModule) {
        const saved = await api(`/api/settings/${form.dataset.settingsModule}`, {
          method: "PUT", body: gatherForm(form),
        });
        fillForm(form, saved.settings);
      }
      await api(`/api/panels/${button.dataset.publishPanel}/publish`, { method: "POST", body: { channel_id: channelId } });
      toast("Panel wurde in Discord veröffentlicht.");
    } catch (error) { toast(error.message, "error"); }
  }));

  async function loadWordFilters() {
    const data = await api("/api/word-filters");
    const target = document.getElementById("word-filter-list");
    target.innerHTML = data.items.length ? data.items.map((item) =>
      `<div class="list-item"><span class="list-symbol">◇</span><div class="list-body"><strong>${escapeHtml(item.phrase)}</strong><small>${escapeHtml(item.mode)} · ${escapeHtml(item.action)}${item.action === "timeout" ? ` · ${item.timeout_minutes} Min.` : ""}</small></div><button class="mini-button delete" data-delete-filter="${item.id}">Löschen</button></div>`
    ).join("") : '<div class="empty-state compact">Noch keine Wortfilter eingerichtet.</div>';
    target.querySelectorAll("[data-delete-filter]").forEach((button) => button.addEventListener("click", async () => {
      if (!confirm("Diesen Filter löschen?")) return;
      try { await api(`/api/word-filters/${button.dataset.deleteFilter}`, { method: "DELETE" }); await loadWordFilters(); toast("Filter gelöscht."); }
      catch (error) { toast(error.message, "error"); }
    }));
  }

  document.getElementById("word-filter-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/word-filters", { method: "POST", body: gatherForm(event.currentTarget) });
      event.currentTarget.reset();
      toast("Wortfilter wurde aktiviert.");
      await loadWordFilters();
    } catch (error) { toast(error.message, "error"); }
  });

  async function loadCases() {
    const data = await api("/api/moderation");
    state.cases = data.items;
    renderCases();
  }
  function renderCases() {
    const target = document.getElementById("case-list");
    if (!target) return;
    const term = document.getElementById("case-search")?.value.toLocaleLowerCase("de") || "";
    const rows = state.cases.filter((item) => `${item.id} ${item.user_name} ${item.reason} ${item.action}`.toLocaleLowerCase("de").includes(term));
    target.innerHTML = rows.length ? rows.map((item) =>
      `<tr><td><strong>#${item.id}</strong></td><td>${escapeHtml(item.user_name)}<br><small>${escapeHtml(item.user_id)}</small></td><td>${escapeHtml(item.action)}</td><td>${escapeHtml(item.moderator_name)}</td><td><span class="status ${item.status === "active" ? "claimed" : "closed"}">${escapeHtml(item.status)}</span></td><td>${formatDate(item.created_at)}</td></tr>`
    ).join("") : '<tr><td colspan="6">Keine Fälle gefunden.</td></tr>';
  }
  document.getElementById("case-search")?.addEventListener("input", renderCases);
  document.getElementById("moderation-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!confirm("Diese Moderationsaktion jetzt auf Discord ausführen?")) return;
    try {
      const data = await api("/api/moderation", { method: "POST", body: gatherForm(event.currentTarget) });
      event.currentTarget.closest("dialog").close();
      event.currentTarget.reset();
      toast(`Fall #${data.case.id} wurde ausgeführt.`);
      await loadCases();
    } catch (error) { toast(error.message, "error"); }
  });

  function updateEmbedPreview() {
    const form = document.getElementById("designer-form");
    const preview = document.getElementById("embed-preview");
    if (!form || !preview) return;
    preview.querySelector(".preview-content").textContent = form.elements.content.value;
    preview.querySelector("h3").textContent = form.elements.title.value || "Dein Embed-Titel";
    preview.querySelector(".discord-embed p").textContent = form.elements.description.value || "Die Beschreibung wird während der Eingabe live aktualisiert.";
    preview.querySelector(".discord-embed > i").style.background = form.elements.color.value;
    preview.querySelector(".discord-embed small").textContent = form.elements.footer.value || "";
  }
  document.getElementById("designer-form")?.addEventListener("input", updateEmbedPreview);
  document.getElementById("designer-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/messages/send", { method: "POST", body: gatherForm(event.currentTarget) });
      toast("Nachricht wurde in Discord veröffentlicht.");
    } catch (error) { toast(error.message, "error"); }
  });

  async function loadAnnouncements() {
    const data = await api("/api/announcements");
    const target = document.getElementById("announcement-list");
    target.innerHTML = data.items.length ? data.items.map((item) =>
      `<div class="list-item"><span class="list-symbol">↗</span><div class="list-body"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.priority)} · ${item.confirmations} Bestätigungen · ${formatDate(item.created_at)}</small></div></div>`
    ).join("") : '<div class="empty-state compact">Noch keine Team-Ankündigungen.</div>';
  }
  document.getElementById("announcement-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/announcements", { method: "POST", body: gatherForm(event.currentTarget) });
      event.currentTarget.reset();
      state.selectors.filter((item) => event.currentTarget.contains(item.root)).forEach((item) => item.set([]));
      toast("Team-Ankündigung wurde veröffentlicht.");
      await loadAnnouncements();
    } catch (error) { toast(error.message, "error"); }
  });

  const permissionNames = {
    "dashboard.open": "Dashboard öffnen", "tickets.view": "Tickets ansehen",
    "tickets.edit": "Tickets bearbeiten", "tickets.delete": "Tickets löschen",
    "applications.edit": "Bewerbungen bearbeiten", "moderation.execute": "Moderationen ausführen",
    "security.edit": "Sicherheitsregeln bearbeiten", "messages.send": "Nachrichten senden",
    "server.edit": "Server-Tools bearbeiten", "team.manage": "Team verwalten",
    "roles.manage": "Dashboard-Rollen verwalten", "audit.view": "Audit-Logs ansehen",
    admin: "Vollständige Administration",
  };
  async function loadPermissions() {
    const data = await api("/api/permissions");
    document.getElementById("permission-options").innerHTML = data.available.map((item) =>
      `<label class="permission-option"><input type="checkbox" name="permissions" value="${escapeHtml(item)}"><span>${escapeHtml(permissionNames[item] || item)}</span></label>`
    ).join("");
    const target = document.getElementById("permission-list");
    target.innerHTML = data.items.length ? data.items.map((item) =>
      `<div class="list-item"><span class="list-symbol">@</span><div class="list-body"><strong>@${escapeHtml(item.role_name)}</strong><small>${item.permissions.length} Berechtigungen</small></div><button class="mini-button delete" data-delete-permission="${item.id}">Entfernen</button></div>`
    ).join("") : '<div class="empty-state compact">Noch keine Discord-Rollen zugeordnet.</div>';
    target.querySelectorAll("[data-delete-permission]").forEach((button) => button.addEventListener("click", async () => {
      if (!confirm("Diese Dashboard-Zuordnung entfernen?")) return;
      try { await api(`/api/permissions/${button.dataset.deletePermission}`, { method: "DELETE" }); await loadPermissions(); toast("Zuordnung entfernt."); }
      catch (error) { toast(error.message, "error"); }
    }));
  }
  document.getElementById("permission-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = gatherForm(event.currentTarget);
    payload.permissions = [...event.currentTarget.querySelectorAll('input[name="permissions"]:checked')].map((item) => item.value);
    try {
      await api("/api/permissions", { method: "POST", body: payload });
      toast("Dashboard-Berechtigungen wurden gespeichert.");
      await loadPermissions();
    } catch (error) { toast(error.message, "error"); }
  });

  async function loadAudit() {
    const data = await api("/api/audit");
    state.audit = data.items;
    renderAudit();
  }
  function renderAudit() {
    const target = document.getElementById("audit-list");
    if (!target) return;
    const term = document.getElementById("audit-search")?.value.toLocaleLowerCase("de") || "";
    const rows = state.audit.filter((item) => `${item.user} ${item.action} ${item.area} ${item.target || ""}`.toLocaleLowerCase("de").includes(term));
    target.innerHTML = rows.length ? rows.map((item) =>
      `<tr><td>#${item.id}</td><td><strong>${escapeHtml(item.user)}</strong><br><small>${escapeHtml(item.user_id)}</small></td><td>${escapeHtml(item.action)}</td><td>${escapeHtml(item.area)}</td><td>${escapeHtml(item.target || "–")}</td><td>${formatDate(item.created_at)}</td></tr>`
    ).join("") : '<tr><td colspan="6">Keine Audit-Einträge gefunden.</td></tr>';
  }
  document.getElementById("audit-search")?.addEventListener("input", renderAudit);

  document.getElementById("refresh-page")?.addEventListener("click", async () => {
    const current = document.querySelector(".page-section.active")?.dataset.pageSection || "overview";
    try {
      if (permissions.has("dashboard.open")) await loadResources(true);
      await loadSection(current);
      toast("Ansicht wurde aktualisiert.");
    } catch (error) { toast(error.message, "error"); }
  });

  function statusLabel(status) {
    return ({ open: "Offen", claimed: "Übernommen", waiting: "Wartend", closed: "Geschlossen", archived: "Archiviert" })[status] || status;
  }
  function formatDate(value) {
    if (!value) return "–";
    return new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
  }
  function relativeDate(value) {
    const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000);
    const formatter = new Intl.RelativeTimeFormat("de", { numeric: "auto" });
    if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
    if (Math.abs(seconds) < 3600) return formatter.format(Math.round(seconds / 60), "minute");
    if (Math.abs(seconds) < 86400) return formatter.format(Math.round(seconds / 3600), "hour");
    return formatter.format(Math.round(seconds / 86400), "day");
  }

  const initial = location.hash.slice(1);
  navigate(document.querySelector(`[data-page-section="${initial}"]`) ? initial : "overview", false);
}
