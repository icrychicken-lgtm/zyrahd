(() => {
  "use strict";

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const page = document.body.dataset.page;
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function toast(message, type = "success") {
    const container = $("#toastContainer");
    if (!container) return;
    const item = document.createElement("div");
    item.className = `toast ${type}`;
    item.textContent = message;
    container.append(item);
    requestAnimationFrame(() => item.classList.add("visible"));
    setTimeout(() => item.remove(), 5000);
  }

  async function api(path, options = {}) {
    const headers = { Accept: "application/json", ...(options.headers || {}) };
    if (options.body && typeof options.body !== "string") {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    if (options.method && options.method !== "GET") headers["X-CSRFToken"] = csrf;
    const response = await fetch(path, { credentials: "same-origin", ...options, headers });
    const body = await response.json().catch(() => ({ error: "Ungültige Serverantwort." }));
    if (!response.ok) throw new Error(body.error || `Anfrage fehlgeschlagen (${response.status})`);
    return body;
  }

  async function pending(button, task) {
    if (!button) return task();
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span class="button-loader">◌</span> Bitte warten';
    try {
      return await task();
    } finally {
      button.disabled = false;
      button.innerHTML = original;
    }
  }

  function valueFromInput(input) {
    if (input.type === "checkbox") return input.checked;
    if (input.type === "number") return Number(input.value || 0);
    return input.value;
  }

  function formData(form) {
    const data = {};
    $$("input[name], textarea[name], select[name]", form).forEach((input) => {
      if (input.type === "radio" && !input.checked) return;
      if (input.type === "checkbox" && input.name === "permissions") {
        if (input.checked) (data.permissions ||= []).push(input.value);
        return;
      }
      data[input.name] = valueFromInput(input);
    });
    $$(".resource-picker", form).forEach((element) => {
      data[element.dataset.field] = element.picker?.getValue() ?? (element.dataset.multiple === "true" ? [] : "");
    });
    return data;
  }

  function fillForm(form, values) {
    Object.entries(values || {}).forEach(([name, value]) => {
      const input = form.elements?.[name];
      if (input) {
        if (input.type === "checkbox") input.checked = Boolean(value);
        else input.value = value ?? "";
      }
      const picker = $(`.resource-picker[data-field="${CSS.escape(name)}"]`, form);
      picker?.picker?.setValue(value);
    });
  }

  // Navigation and dialogs
  $("#mobileToggle")?.addEventListener("click", () => document.body.classList.toggle("menu-open"));
  $("#sidebarOverlay")?.addEventListener("click", () => document.body.classList.remove("menu-open"));
  $$("[data-open-dialog]").forEach((button) => {
    button.addEventListener("click", () => document.getElementById(button.dataset.openDialog)?.showModal());
  });
  $$("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog")?.close());
  });
  $$("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  // Searchable Discord resource dropdowns
  let resourcesPromise;
  function loadResources() {
    resourcesPromise ||= api("/api/resources").catch((error) => {
      toast(error.message, "error");
      return { roles: [], channels: [], members: [] };
    });
    return resourcesPromise;
  }

  class ResourcePicker {
    constructor(element) {
      this.element = element;
      this.kind = element.dataset.resource;
      this.multiple = element.dataset.multiple === "true";
      this.types = (element.dataset.types || "").split(",").filter(Boolean);
      this.selected = new Set();
      this.items = [];
      this.build();
      loadResources().then((resources) => {
        this.items = (resources[this.kind] || []).filter((item) => {
          if (this.kind === "roles" && item.usable === false) return false;
          return !this.types.length || this.types.includes(item.type);
        });
        this.renderControl();
        this.renderOptions();
      });
      element.picker = this;
    }

    build() {
      this.element.innerHTML = `
        <div class="picker-control" tabindex="0" role="combobox" aria-expanded="false"></div>
        <div class="picker-dropdown hidden">
          <div class="picker-search"><input type="search" placeholder="Suchen …" autocomplete="off"></div>
          <div class="picker-options"><div class="picker-empty">Wird geladen …</div></div>
          <div class="picker-footer"><span>Live vom Discord-Server</span><button type="button">Alle entfernen</button></div>
        </div>`;
      this.control = $(".picker-control", this.element);
      this.dropdown = $(".picker-dropdown", this.element);
      this.search = $(".picker-search input", this.element);
      this.options = $(".picker-options", this.element);
      this.control.addEventListener("click", () => this.toggle());
      this.control.addEventListener("keydown", (event) => {
        if (["Enter", " "].includes(event.key)) {
          event.preventDefault();
          this.toggle();
        }
      });
      this.search.addEventListener("input", () => this.renderOptions());
      $(".picker-footer button", this.element).addEventListener("click", () => {
        this.selected.clear();
        this.renderControl();
        this.renderOptions();
      });
      this.renderControl();
    }

    toggle(force) {
      const open = force ?? !this.element.classList.contains("open");
      $$(".resource-picker.open").forEach((other) => {
        if (other !== this.element) other.picker.toggle(false);
      });
      this.element.classList.toggle("open", open);
      this.dropdown.classList.toggle("hidden", !open);
      this.control.setAttribute("aria-expanded", String(open));
      if (open) setTimeout(() => this.search.focus(), 20);
    }

    label(item) {
      if (!item) return "Gelöschter Eintrag";
      return `${this.kind === "roles" ? "@" : this.kind === "channels" ? "#" : ""}${item.name}`;
    }

    renderControl() {
      const selectedItems = [...this.selected].map((id) => this.items.find((item) => item.id === id));
      if (!selectedItems.length) {
        this.control.innerHTML = `<span class="picker-placeholder">${
          this.kind === "roles" ? "Rolle auswählen …" : this.kind === "members" ? "Mitglied suchen …" : "Kanal auswählen …"
        }</span>`;
        return;
      }
      this.control.innerHTML = selectedItems
        .map((item, index) => `<span class="picker-tag"><b>${escapeHtml(this.label(item))}</b><button type="button" data-index="${index}" aria-label="Entfernen">×</button></span>`)
        .join("");
      $$("[data-index]", this.control).forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          const item = selectedItems[Number(button.dataset.index)];
          if (item) this.selected.delete(item.id);
          this.renderControl();
          this.renderOptions();
        });
      });
    }

    renderOptions() {
      const query = this.search?.value.trim().toLocaleLowerCase("de") || "";
      const items = this.items.filter((item) =>
        `${item.name} ${item.subtitle || ""}`.toLocaleLowerCase("de").includes(query)
      );
      if (!items.length) {
        this.options.innerHTML = '<div class="picker-empty">Kein Ergebnis gefunden.</div>';
        return;
      }
      this.options.innerHTML = items
        .map((item) => `
          <button type="button" class="picker-option ${this.selected.has(item.id) ? "selected" : ""}" data-id="${item.id}">
            ${item.avatar ? `<img class="picker-avatar" src="${escapeAttribute(item.avatar)}" alt="">` : '<span class="picker-check">✓</span>'}
            <span><b>${escapeHtml(this.label(item))}</b>${item.subtitle ? `<small>${escapeHtml(item.subtitle)}</small>` : ""}</span>
          </button>`)
        .join("");
      $$(".picker-option", this.options).forEach((option) => {
        option.addEventListener("click", () => {
          const id = option.dataset.id;
          if (!this.multiple) {
            this.selected.clear();
            this.selected.add(id);
            this.toggle(false);
          } else if (this.selected.has(id)) this.selected.delete(id);
          else this.selected.add(id);
          this.renderControl();
          this.renderOptions();
        });
      });
    }

    setValue(value) {
      const values = Array.isArray(value) ? value : value ? [value] : [];
      this.selected = new Set(values.map(String));
      this.renderControl();
      this.renderOptions();
    }

    getValue() {
      const values = [...this.selected];
      return this.multiple ? values : values[0] || "";
    }

    selectedItem() {
      return this.items.find((item) => item.id === this.getValue());
    }
  }

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = String(value ?? "");
    return node.innerHTML;
  }
  function escapeAttribute(value) {
    return escapeHtml(value).replaceAll('"', "&quot;");
  }

  const pickerElements = $$(".resource-picker");
  pickerElements.forEach((element) => new ResourcePicker(element));
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".resource-picker")) {
      $$(".resource-picker.open").forEach((element) => element.picker.toggle(false));
    }
  });

  // Generic persisted setting forms
  $$("form[data-section]").forEach(async (form) => {
    const section = form.dataset.section;
    try {
      const values = await api(`/api/settings/${section}`);
      fillForm(form, values);
    } catch (error) {
      toast(error.message, "error");
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const submit = event.submitter || $('button[type="submit"]', form);
      try {
        const result = await pending(submit, () =>
          api(`/api/settings/${section}`, { method: "PUT", body: formData(form) })
        );
        toast(result.message || "Einstellungen gespeichert.");
      } catch (error) {
        toast(error.message, "error");
      }
    });
  });

  $$("[data-settings-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      $$("[data-settings-tab]").forEach((item) => item.classList.toggle("active", item === button));
      $$(".settings-section").forEach((section) =>
        section.classList.toggle("active", section.dataset.section === button.dataset.settingsTab)
      );
    });
  });

  // Keep color swatches and text in sync
  $$('input[type="color"]').forEach((color) => {
    const text = color.parentElement?.querySelector("[data-color-text]");
    if (!text) return;
    color.addEventListener("input", () => (text.value = color.value));
    text.addEventListener("input", () => {
      if (/^#[0-9a-f]{6}$/i.test(text.value)) color.value = text.value;
    });
  });

  // Dashboard chart
  function drawChart(canvas) {
    if (!canvas) return;
    const labels = JSON.parse(canvas.dataset.labels || "[]");
    const values = JSON.parse(canvas.dataset.values || "[]");
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    const width = rect.width;
    const height = rect.height;
    const pad = { left: 31, right: 12, top: 15, bottom: 27 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const max = Math.max(4, ...values);
    ctx.font = "9px Inter, sans-serif";
    ctx.textAlign = "right";
    ctx.fillStyle = "#6f667e";
    ctx.strokeStyle = "rgba(255,255,255,.055)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (plotH / 4) * i;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(width - pad.right, y);
      ctx.stroke();
      ctx.fillText(String(Math.round(max - (max / 4) * i)), pad.left - 8, y + 3);
    }
    const points = values.map((value, index) => ({
      x: pad.left + (plotW / Math.max(1, values.length - 1)) * index,
      y: pad.top + plotH - (value / max) * plotH,
    }));
    const gradient = ctx.createLinearGradient(0, pad.top, 0, height - pad.bottom);
    gradient.addColorStop(0, "rgba(139,92,246,.28)");
    gradient.addColorStop(1, "rgba(139,92,246,0)");
    ctx.beginPath();
    ctx.moveTo(points[0]?.x || pad.left, height - pad.bottom);
    points.forEach((point) => ctx.lineTo(point.x, point.y));
    ctx.lineTo(points.at(-1)?.x || width - pad.right, height - pad.bottom);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
    ctx.beginPath();
    points.forEach((point, index) => (index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y)));
    ctx.strokeStyle = "#9d71f5";
    ctx.lineWidth = 2;
    ctx.shadowColor = "rgba(139,92,246,.5)";
    ctx.shadowBlur = 9;
    ctx.stroke();
    ctx.shadowBlur = 0;
    points.forEach((point, index) => {
      ctx.beginPath();
      ctx.arc(point.x, point.y, 3, 0, Math.PI * 2);
      ctx.fillStyle = "#b595fb";
      ctx.fill();
      ctx.textAlign = "center";
      ctx.fillStyle = "#756b82";
      ctx.fillText(labels[index] || "", point.x, height - 8);
    });
  }
  const chart = $("#ticketChart");
  if (chart) {
    drawChart(chart);
    let resizeTimer;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => drawChart(chart), 100);
    });
  }

  $$("[data-count]").forEach((element) => {
    const target = Number(element.dataset.count);
    if (!target || target > 100000) return;
    const start = performance.now();
    const animate = (time) => {
      const progress = Math.min(1, (time - start) / 650);
      element.textContent = Math.round(target * (1 - Math.pow(1 - progress, 3))).toLocaleString("de-DE");
      if (progress < 1) requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  });

  // New ticket flow
  if (page === "tickets") {
    const dialog = $("#newTicketDialog");
    const form = $("#ticketCreateForm");
    let selectedType = null;
    function showTypeStep() {
      $('[data-step="types"]', form).classList.add("active");
      $('[data-step="form"]', form).classList.remove("active");
      $("#ticketSubmit").classList.add("hidden");
      selectedType = null;
    }
    $$(".type-choice", form).forEach((button) => {
      button.addEventListener("click", () => {
        selectedType = button.dataset.ticketType;
        const template = document.getElementById(`ticketForm-${selectedType}`);
        $("#ticketDynamicFields").replaceChildren(template.content.cloneNode(true));
        $("#ticketFormTitle").textContent = button.dataset.ticketName;
        $('[data-step="types"]', form).classList.remove("active");
        $('[data-step="form"]', form).classList.add("active");
        $("#ticketSubmit").classList.remove("hidden");
      });
    });
    $("#ticketBack")?.addEventListener("click", showTypeStep);
    dialog?.addEventListener("close", showTypeStep);
    form?.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!selectedType || !form.reportValidity()) return;
      const fields = {};
      $$("[data-field-id]", $("#ticketDynamicFields")).forEach((input) => (fields[input.dataset.fieldId] = input.value));
      try {
        const result = await pending($("#ticketSubmit"), () =>
          api("/api/tickets", { method: "POST", body: { ticket_type_id: selectedType, form_data: fields } })
        );
        toast(`Ticket #${result.number} wurde erstellt.`);
        dialog.close();
        setTimeout(() => location.reload(), 700);
      } catch (error) {
        toast(error.message, "error");
      }
    });
  }

  // Ticket chat and status
  $("#ticketMessageForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.content;
    try {
      await pending(event.submitter, () =>
        api(`/api/tickets/${form.dataset.ticketId}/messages`, { method: "POST", body: { content: input.value } })
      );
      input.value = "";
      toast("Nachricht wurde an Discord gesendet.");
      setTimeout(() => location.reload(), 500);
    } catch (error) {
      toast(error.message, "error");
    }
  });
  $$("[data-ticket-status]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.dataset.ticketStatus === "closed" && !confirm("Ticket wirklich schließen?")) return;
      try {
        await pending(button, () =>
          api(`/api/tickets/${button.dataset.ticketId}/status`, {
            method: "PUT",
            body: { status: button.dataset.ticketStatus, reason: "Über Dashboard geändert" },
          })
        );
        toast("Ticket-Status aktualisiert.");
        setTimeout(() => location.reload(), 500);
      } catch (error) {
        toast(error.message, "error");
      }
    });
  });

  // Panel publishing
  async function publishPanel(kind, form, button) {
    try {
      const result = await pending(button, () =>
        api(`/api/publish/${kind}`, { method: "POST", body: formData(form) })
      );
      toast(result.message || "Panel wurde in Discord veröffentlicht.");
    } catch (error) {
      toast(error.message, "error");
    }
  }
  $("#publishVerify")?.addEventListener("click", (event) =>
    publishPanel("verify", event.currentTarget.closest("form"), event.currentTarget)
  );
  $("#publishTicketPanel")?.addEventListener("click", (event) =>
    publishPanel("ticket", event.currentTarget.closest("form"), event.currentTarget)
  );

  // Ticket type editor
  if (page === "ticket-settings") {
    const dialog = $("#ticketTypeDialog");
    const form = $("#ticketTypeForm");
    const fieldContainer = $("#ticketFields");
    let types = [];
    const refreshTypes = () => api("/api/ticket-types").then((items) => (types = items));
    refreshTypes().catch((error) => toast(error.message, "error"));

    function addTicketField(field = {}) {
      if ($$(".builder-row", fieldContainer).length >= 5) {
        toast("Discord erlaubt maximal fünf Formularfelder.", "error");
        return;
      }
      const row = document.createElement("div");
      row.className = "builder-row";
      row.innerHTML = `
        <input data-key="label" maxlength="45" required placeholder="Frage / Feldname" value="${escapeAttribute(field.label || "")}">
        <select data-key="field_type"><option value="long">Lang</option><option value="short">Kurz</option></select>
        <select data-key="required"><option value="true">Pflicht</option><option value="false">Optional</option></select>
        <button type="button" class="icon-button danger">×</button>
        <input data-key="placeholder" maxlength="100" placeholder="Platzhalter" value="${escapeAttribute(field.placeholder || "")}">
        <input data-key="min_length" type="number" min="0" max="4000" value="${Number(field.min_length || 0)}">
        <input data-key="max_length" type="number" min="1" max="4000" value="${Number(field.max_length || 1000)}">`;
      $('[data-key="field_type"]', row).value = field.field_type || "long";
      $('[data-key="required"]', row).value = String(field.required ?? true);
      $("button", row).addEventListener("click", () => row.remove());
      fieldContainer.append(row);
    }

    function openType(item) {
      form.reset();
      form.elements.id.value = item?.id || "";
      form.elements.name.value = item?.name || "";
      form.elements.description.value = item?.description || "";
      form.elements.emoji.value = item?.emoji || "🎫";
      form.elements.color.value = item?.color || "#8b5cf6";
      form.elements.max_open.value = item?.max_open || 1;
      form.elements.cooldown_minutes.value = item?.cooldown_minutes ?? 5;
      form.elements.welcome_message.value = item?.welcome_message || "Danke für deine Anfrage. Das Team meldet sich in Kürze.";
      form.elements.enabled.checked = item?.enabled ?? true;
      ["category_id", "support_role_ids", "log_channel_id", "transcript_channel_id"].forEach((key) =>
        $(`.resource-picker[data-field="${key}"]`, form)?.picker.setValue(item?.[key] || (key.endsWith("_ids") ? [] : ""))
      );
      fieldContainer.replaceChildren();
      (item?.fields?.length ? item.fields : [{}]).forEach(addTicketField);
      $("#ticketTypeHeading").textContent = item ? item.name : "Neue Ticket-Art";
      dialog.showModal();
    }

    $("#newTicketType")?.addEventListener("click", () => openType(null));
    $$(".edit-ticket-type").forEach((button) =>
      button.addEventListener("click", async () => {
        if (!types.length) await refreshTypes();
        openType(types.find((item) => item.id === Number(button.dataset.id)));
      })
    );
    $("#addTicketField")?.addEventListener("click", () => addTicketField());
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = formData(form);
      const id = data.id;
      delete data.id;
      data.fields = $$(".builder-row", fieldContainer).map((row) => {
        const result = {};
        $$("[data-key]", row).forEach((input) => {
          const key = input.dataset.key;
          result[key] = key === "required" ? input.value === "true" : ["min_length", "max_length"].includes(key) ? Number(input.value) : input.value;
        });
        return result;
      });
      try {
        const result = await pending(event.submitter, () =>
          api(id ? `/api/ticket-types/${id}` : "/api/ticket-types", { method: id ? "PUT" : "POST", body: data })
        );
        toast(result.message);
        dialog.close();
        setTimeout(() => location.reload(), 550);
      } catch (error) {
        toast(error.message, "error");
      }
    });
    $$(".delete-ticket-type").forEach((button) =>
      button.addEventListener("click", async () => {
        if (!confirm("Diese Ticket-Art löschen? Bestehende Tickets bleiben erhalten.")) return;
        try {
          const result = await api(`/api/ticket-types/${button.dataset.id}`, { method: "DELETE" });
          toast(result.message);
          setTimeout(() => location.reload(), 500);
        } catch (error) {
          toast(error.message, "error");
        }
      })
    );
  }

  // Security
  $("#wordFilterForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await pending(event.submitter, () =>
        api("/api/word-filters", { method: "POST", body: formData(event.currentTarget) })
      );
      toast(result.message);
      setTimeout(() => location.reload(), 450);
    } catch (error) {
      toast(error.message, "error");
    }
  });
  $$(".delete-word-filter").forEach((button) =>
    button.addEventListener("click", async () => {
      try {
        const result = await api(`/api/word-filters/${button.dataset.id}`, { method: "DELETE" });
        toast(result.message);
        button.closest(".table-row").remove();
      } catch (error) {
        toast(error.message, "error");
      }
    })
  );

  // Moderation
  $("#moderationForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = formData(form);
    const picker = $('.resource-picker[data-field="user_id"]', form)?.picker;
    if (!data.user_id) return toast("Bitte wähle ein Mitglied.", "error");
    data.user_name = picker.selectedItem()?.name || data.user_id;
    if (!confirm(`${data.action.toUpperCase()} für ${data.user_name} wirklich ausführen?`)) return;
    try {
      const result = await pending(event.submitter, () => api("/api/moderate", { method: "POST", body: data }));
      toast(`Aktion ausgeführt · Fall #${result.case_number}`);
      form.closest("dialog").close();
      setTimeout(() => location.reload(), 600);
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // Embed designer
  if (page === "embed-designer") {
    const form = $("#embedForm");
    const fields = $("#embedFields");
    function updatePreview() {
      const data = formData(form);
      $("#previewTitle").textContent = data.title || "Dein Embed-Titel";
      $("#previewDescription").textContent = data.description || "Beginne links zu schreiben. Deine Nachricht erscheint sofort in dieser Vorschau.";
      $("#previewFooter").textContent = data.footer || "zyrahd.net";
      $("#embedPreview").style.setProperty("--embed-color", data.color || "#8b5cf6");
      $("#previewContent").textContent = data.content || "";
      $("#previewContent").classList.toggle("hidden", !data.content);
      [["previewThumbnail", data.thumbnail], ["previewImage", data.image]].forEach(([id, url]) => {
        const image = document.getElementById(id);
        image.classList.toggle("hidden", !/^https?:\/\//.test(url || ""));
        if (url) image.src = url;
      });
      const target = $("#previewFields");
      target.innerHTML = $$(".builder-row", fields)
        .map((row) => {
          const name = $('[data-key="name"]', row).value;
          const value = $('[data-key="value"]', row).value;
          return name && value ? `<div class="preview-field"><strong>${escapeHtml(name)}</strong><p>${escapeHtml(value)}</p></div>` : "";
        })
        .join("");
    }
    function addEmbedField() {
      if ($$(".builder-row", fields).length >= 25) return toast("Maximal 25 Embed-Felder.", "error");
      const row = document.createElement("div");
      row.className = "builder-row";
      row.innerHTML = '<input data-key="name" maxlength="256" placeholder="Feldname"><input data-key="value" maxlength="1024" placeholder="Inhalt"><select data-key="inline"><option value="true">Nebeneinander</option><option value="false">Volle Breite</option></select><button type="button" class="icon-button danger">×</button>';
      $$("input,select", row).forEach((input) => input.addEventListener("input", updatePreview));
      $("button", row).addEventListener("click", () => { row.remove(); updatePreview(); });
      fields.append(row);
    }
    $("#addEmbedField")?.addEventListener("click", addEmbedField);
    $$("input,textarea,select", form).forEach((input) => input.addEventListener("input", updatePreview));
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = formData(form);
      data.fields = $$(".builder-row", fields).map((row) => ({
        name: $('[data-key="name"]', row).value,
        value: $('[data-key="value"]', row).value,
        inline: $('[data-key="inline"]', row).value === "true",
      }));
      try {
        await pending(event.submitter, () => api("/api/embeds", { method: "POST", body: data }));
        toast("Embed wurde erfolgreich in Discord gesendet.");
      } catch (error) {
        toast(error.message, "error");
      }
    });
    updatePreview();
  }

  // Team announcements
  $("#announcementForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await pending(event.submitter, () =>
        api("/api/team-announcements", { method: "POST", body: formData(event.currentTarget) })
      );
      toast(result.message);
      event.currentTarget.closest("dialog").close();
      setTimeout(() => location.reload(), 500);
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // Dashboard role mappings
  $("#rolePermissionForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = formData(event.currentTarget);
    const picker = $('.resource-picker[data-field="role_id"]', event.currentTarget)?.picker;
    if (!data.role_id) return toast("Bitte wähle eine Discord-Rolle.", "error");
    data.role_name = picker.selectedItem()?.name || "Discord-Rolle";
    try {
      const result = await pending(event.submitter, () =>
        api(`/api/dashboard-roles/${data.role_id}`, { method: "PUT", body: data })
      );
      toast(result.message);
      setTimeout(() => location.reload(), 500);
    } catch (error) {
      toast(error.message, "error");
    }
  });
  $$(".delete-role-mapping").forEach((button) =>
    button.addEventListener("click", async () => {
      if (!confirm("Diese Rollenzuordnung entfernen?")) return;
      try {
        const result = await api(`/api/dashboard-roles/${button.dataset.roleId}`, { method: "DELETE" });
        toast(result.message);
        button.closest(".mapping-row").remove();
      } catch (error) {
        toast(error.message, "error");
      }
    })
  );

  // Table search and audit details
  $$("[data-table-search]").forEach((input) => {
    const table = $("[data-search-table]", input.closest(".panel") || document);
    input.addEventListener("input", () => {
      const query = input.value.toLocaleLowerCase("de").trim();
      $$("[data-search-text]", table).forEach((row) =>
        row.classList.toggle("hidden", !row.dataset.searchText.toLocaleLowerCase("de").includes(query))
      );
    });
  });
  $$(".audit-details").forEach((button) => {
    button.addEventListener("click", () => {
      const pretty = (value) => {
        try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value || "—"; }
      };
      $("#auditOld").textContent = pretty(button.dataset.old);
      $("#auditNew").textContent = pretty(button.dataset.new);
      $("#auditDialog").showModal();
    });
  });

  // Scroll chat to newest message
  const messageList = $("#messageList");
  if (messageList) messageList.scrollTop = messageList.scrollHeight;
})();
