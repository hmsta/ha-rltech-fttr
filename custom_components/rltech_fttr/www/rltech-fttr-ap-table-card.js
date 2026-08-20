class RltechFttrApTableCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._rows = [];
    this._search = "";
    this._filters = { state: "", profile: "", model: "", uplink: "" };
    this._sortKey = "alias";
    this._sortDir = 1;
    this._page = 0;
    this._pageSize = 25;
    this._columns = [];
    this._mobileColumns = [];
    this._error = "";
    this._lastFetch = 0;
    this._fetchTimer = null;
    this._refreshTimer = null;
    this._shellRendered = false;
    this._isMobile = false;
    this._mediaQuery = null;
    this._entryResolving = null;
    this._preferencesLoaded = false;
  }

  setConfig(config) {
    this._config = {
      page_size: 25,
      page_size_options: [25, 50, 100],
      remember_preferences: true,
      search_debounce_ms: 150,
      columns: this._defaultColumns(),
      mobile_columns: this._defaultMobileColumns(),
      ...config,
    };
    this._pageSize = Number(this._config.page_size) || 25;
    this._columns = this._validColumns(this._config.columns, this._defaultColumns());
    this._mobileColumns = this._validColumns(this._config.mobile_columns, this._defaultMobileColumns());
    this._setupMediaQuery();
    if (this._config.entry_id) {
      this._loadPreferences();
    }
    this._renderShell();
    this._refreshTable();
  }

  set hass(hass) {
    this._hass = hass;
    this._scheduleFetch();
  }

  getCardSize() {
    return 6;
  }

  static getStubConfig() {
    return {
      type: "custom:rltech-fttr-ap-table-card",
    };
  }

  _columnDefs() {
    return [
      ["details", "More", (_row, index) => this._detailsButton(index), () => ""],
      ["alias", "Alias", (row) => this._escape(row.alias || row.mac), (row) => row.alias || row.mac, "alias"],
      ["mac", "MAC"],
      ["ip", "IP"],
      ["online", "State", (row) => this._stateCell(row), (row) => (row.online ? "online" : "offline"), "online"],
      ["model", "Model"],
      ["version", "Version"],
      ["profile", "Profile", null, null, "profile"],
      ["profile_idx", "Profile ID"],
      ["assoc_count", "Assoc", null, null, "assoc_count"],
      ["channel_24", "2.4 Ch"],
      ["channel_5", "5 Ch"],
      ["bssid_24", "2.4 BSSID"],
      ["bssid_5", "5 BSSID"],
      ["uplink_label", "Uplink", (row) => this._escape(this._uplinkLabel(row)), (row) => this._uplinkLabel(row)],
      ["uplink", "Uplink raw"],
      ["uplink_port", "Uplink port"],
      ["sn", "SN"],
      ["dev_sn", "Dev SN"],
      ["upgrade_flag", "Upgrade"],
      ["optical_rx_power", "Rx dBm", null, null, "optical_rx_power"],
      ["optical_tx_power", "Tx dBm", null, null, "optical_tx_power"],
      ["downstream_optical_rx_power", "Down RX dBm", null, null, "downstream_optical_rx_power"],
      ["optical_temperature", "Optical temp", null, null, "optical_temperature"],
      ["optical_voltage", "Optical voltage", null, null, "optical_voltage"],
      ["optical_current", "Optical current", null, null, "optical_current"],
      ["ont_distance", "ONT distance"],
      ["last_down_cause", "Last down cause"],
      ["last_up_time", "Last up"],
      ["last_down_time", "Last down"],
      ["last_dying_gasp_time", "Last dying gasp"],
      ["detail_last_update", "Detail update"],
      ["cpu_usage", "CPU usage"],
      ["cpu_temperature", "CPU temp"],
      ["memory_usage", "Memory usage"],
      ["flash_usage", "Flash usage"],
      ["sys_duration", "Sys duration"],
    ].map(([key, label, render, sort, entityKey]) => ({
      key,
      label,
      render: render || ((row) => this._escape(row[key])),
      sort: sort || ((row) => row[key]),
      entityKey,
    }));
  }

  _defaultColumns() {
    return ["alias", "ip", "online", "assoc_count", "profile", "details"];
  }

  _defaultMobileColumns() {
    return ["alias", "ip", "online", "assoc_count", "channel_24", "channel_5", "details"];
  }

  _activeColumns() {
    return this._isMobile ? this._mobileColumns : this._columns;
  }

  _setActiveColumns(columns) {
    if (this._isMobile) {
      this._mobileColumns = columns;
    } else {
      this._columns = columns;
    }
  }

  _activeDefaultColumns() {
    return this._isMobile ? this._defaultMobileColumns() : this._defaultColumns();
  }

  _setupMediaQuery() {
    if (this._mediaQuery || !window.matchMedia) {
      this._isMobile = window.innerWidth <= 760;
      return;
    }
    this._mediaQuery = window.matchMedia("(max-width: 760px)");
    this._isMobile = this._mediaQuery.matches;
    const listener = (event) => {
      this._isMobile = event.matches;
      this._page = 0;
      if (this._shellRendered) {
        this._refreshColumnPicker();
        this._renderHeaders();
        this._refreshTable();
      }
    };
    if (this._mediaQuery.addEventListener) {
      this._mediaQuery.addEventListener("change", listener);
    } else {
      this._mediaQuery.addListener(listener);
    }
  }

  _storageKey() {
    const key = this._config.storage_key || this._config.entry_id || "auto";
    return `rltech_fttr.ap_table.${key}`;
  }

  _loadPreferences() {
    if (this._preferencesLoaded || !this._config.remember_preferences) {
      return;
    }
    this._preferencesLoaded = true;
    try {
      const raw = window.localStorage.getItem(this._storageKey());
      if (!raw) {
        return;
      }
      const prefs = JSON.parse(raw);
      if (Array.isArray(prefs.columns)) {
        this._columns = this._validColumns(prefs.columns, this._defaultColumns());
      }
      if (Array.isArray(prefs.mobile_columns)) {
        this._mobileColumns = this._validColumns(prefs.mobile_columns, this._defaultMobileColumns());
      }
      if (Number.isFinite(Number(prefs.page_size))) {
        this._pageSize = Number(prefs.page_size);
      }
      if (typeof prefs.sort_key === "string") {
        this._sortKey = prefs.sort_key;
      }
      if (prefs.sort_dir === 1 || prefs.sort_dir === -1) {
        this._sortDir = prefs.sort_dir;
      }
      if (prefs.filters && typeof prefs.filters === "object") {
        this._filters = { ...this._filters, ...prefs.filters };
      }
    } catch (_) {
      window.localStorage.removeItem(this._storageKey());
    }
  }

  _savePreferences() {
    if (!this._config.remember_preferences) {
      return;
    }
    window.localStorage.setItem(
      this._storageKey(),
      JSON.stringify({
        columns: this._columns,
        mobile_columns: this._mobileColumns,
        page_size: this._pageSize,
        sort_key: this._sortKey,
        sort_dir: this._sortDir,
        filters: this._filters,
      })
    );
  }

  _resetPreferences() {
    window.localStorage.removeItem(this._storageKey());
    this._columns = this._validColumns(this._config.columns, this._defaultColumns());
    this._mobileColumns = this._validColumns(this._config.mobile_columns, this._defaultMobileColumns());
    this._pageSize = Number(this._config.page_size) || 25;
    this._sortKey = "alias";
    this._sortDir = 1;
    this._filters = { state: "", profile: "", model: "", uplink: "" };
    this._search = "";
    this._page = 0;
    this.shadowRoot.getElementById("search").value = "";
    this._closeOptions();
    this._refreshFilterOptions();
    this._refreshColumnPicker();
    this._refreshPageSize();
    this._renderHeaders();
    this._refreshTable();
  }

  _validColumns(columns, fallback) {
    const valid = new Set(this._columnDefs().map((col) => col.key));
    const selected = (Array.isArray(columns) ? columns : fallback).filter((key) => valid.has(key));
    const normalized = selected.filter((key) => key !== "details");
    if (selected.includes("details")) {
      normalized.push("details");
    }
    return normalized.length ? normalized : fallback;
  }

  _scheduleFetch() {
    if (!this._hass) {
      return;
    }
    const wait = Math.max(0, 5000 - (Date.now() - this._lastFetch));
    if (this._fetchTimer) {
      return;
    }
    this._fetchTimer = window.setTimeout(() => {
      this._fetchTimer = null;
      this._fetch();
    }, wait);
  }

  async _fetch() {
    if (!this._hass) {
      return;
    }
    this._lastFetch = Date.now();
    try {
      const entryId = await this._entryId();
      if (!entryId) {
        this._refreshTable();
        return;
      }
      const result = await this._hass.callWS({
        type: "rltech_fttr/get_access_points",
        entry_id: entryId,
      });
      this._rows = result.access_points || [];
      this._error = "";
      this._refreshFilterOptions();
    } catch (err) {
      this._error = err.message || String(err);
    }
    this._refreshTable();
  }

  async _entryId() {
    if (this._config.entry_id) {
      this._loadPreferences();
      return this._config.entry_id;
    }
    if (!this._entryResolving) {
      this._entryResolving = this._hass.callWS({ type: "rltech_fttr/get_entries" });
    }
    try {
      const result = await this._entryResolving;
      const entries = result.entries || [];
      if (entries.length === 1) {
        this._config.entry_id = entries[0].entry_id;
        this._loadPreferences();
        this._refreshColumnPicker();
        this._renderHeaders();
        return this._config.entry_id;
      }
      this._error = entries.length
        ? `Multiple RLTech FTTR integrations found. Set entry_id to one of: ${entries.map((entry) => `${entry.title} (${entry.entry_id})`).join(", ")}`
        : "No loaded RLTech FTTR integration found.";
      return "";
    } catch (err) {
      this._error = err.message || String(err);
      return "";
    }
  }

  _filteredRows() {
    const search = this._search.trim().toLowerCase();
    const defs = new Map(this._columnDefs().map((col) => [col.key, col]));
    return this._rows
      .filter((row) => {
        const haystack = Object.values(row).filter((value) => value !== null && value !== undefined).join(" ").toLowerCase();
        if (search && !haystack.includes(search)) {
          return false;
        }
        if (this._filters.state) {
          const state = row.online ? "online" : "offline";
          if (state !== this._filters.state) {
            return false;
          }
        }
        if (this._filters.profile && row.profile !== this._filters.profile) {
          return false;
        }
        if (this._filters.model && row.model !== this._filters.model) {
          return false;
        }
        if (this._filters.uplink && this._uplinkLabel(row) !== this._filters.uplink) {
          return false;
        }
        return true;
      })
      .sort((left, right) => {
        const col = defs.get(this._sortKey);
        const a = col ? col.sort(left) : left[this._sortKey];
        const b = col ? col.sort(right) : right[this._sortKey];
        return this._compare(a, b) * this._sortDir;
      });
  }

  _pageRows(rows) {
    if (this._pageSize === 0) {
      return rows;
    }
    const pageCount = Math.max(1, Math.ceil(rows.length / this._pageSize));
    this._page = Math.min(this._page, pageCount - 1);
    const start = this._page * this._pageSize;
    return rows.slice(start, start + this._pageSize);
  }

  _renderShell() {
    if (!this.shadowRoot || this._shellRendered) {
      return;
    }
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="wrap">
          <div class="toolbar">
            <input id="search" type="search" placeholder="Search access points" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
            <select id="state">
              <option value="">State</option>
              <option value="online">Online</option>
              <option value="offline">Offline</option>
            </select>
            <select id="profile"></select>
            <select id="model"></select>
            <select id="uplink"></select>
            <button id="clear-filters" type="button" hidden>Clear</button>
            <select id="page-size" title="Rows per page"></select>
            <div class="options">
              <button id="options" class="options-button" type="button" title="Table options" aria-label="Table options">
                <span></span><span></span><span></span>
              </button>
              <div id="options-menu" class="options-menu" hidden>
                <div class="menu-title">Columns</div>
                <div id="column-panel" class="column-panel"></div>
                <div class="menu-title">View</div>
                <button id="reset" class="menu-button" type="button">Reset view</button>
              </div>
            </div>
          </div>
          <div id="meta" class="meta"></div>
          <div class="table-wrap">
            <table>
              <thead><tr id="headers"></tr></thead>
              <tbody id="rows"></tbody>
            </table>
          </div>
          <div class="mobile-list" id="mobile-rows"></div>
          <div class="pager">
            <button id="prev" type="button">Prev</button>
            <span id="page-info"></span>
            <button id="next" type="button">Next</button>
          </div>
        </div>
        <div id="dialog" class="dialog" hidden>
          <div class="dialog-card">
            <div class="dialog-head">
              <strong id="dialog-title"></strong>
              <button id="dialog-close" type="button">Close</button>
            </div>
            <div id="dialog-body" class="details"></div>
          </div>
        </div>
      </ha-card>
      <style>
        :host {
          display: block;
          min-width: 0;
          width: 100%;
        }
        ha-card {
          display: block;
          max-width: 100%;
          overflow: hidden;
          width: 100%;
        }
        .wrap {
          box-sizing: border-box;
          min-width: 0;
          padding: 12px;
          width: 100%;
        }
        .toolbar {
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 8px;
          position: relative;
        }
        .toolbar input {
          flex: 1 1 220px;
          min-width: 160px;
        }
        .toolbar select {
          flex: 0 1 140px;
          min-width: 96px;
        }
        input, select, button {
          background: var(--card-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          color: var(--primary-text-color);
          min-height: 32px;
          padding: 0 8px;
        }
        button { cursor: pointer; }
        .meta, #page-info {
          color: var(--secondary-text-color);
          font-size: 12px;
        }
        .options { position: relative; }
        .options-button {
          align-items: center;
          display: inline-flex;
          flex-direction: column;
          gap: 3px;
          justify-content: center;
          min-width: 34px;
          padding: 0;
        }
        .options-button span {
          background: var(--primary-text-color);
          border-radius: 999px;
          display: block;
          height: 2px;
          width: 16px;
        }
        .options-menu {
          background: var(--card-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          box-shadow: 0 8px 22px rgba(0, 0, 0, 0.22);
          max-height: 70vh;
          min-width: 230px;
          overflow: auto;
          padding: 10px;
          position: absolute;
          right: 0;
          top: 38px;
          z-index: 5;
        }
        .menu-title {
          color: var(--secondary-text-color);
          font-size: 12px;
          font-weight: 650;
          margin: 4px 0 6px;
          text-transform: uppercase;
        }
        .column-panel {
          display: grid;
          gap: 6px;
        }
        .column-panel label {
          align-items: center;
          display: flex;
          font-size: 13px;
          gap: 6px;
        }
        .menu-button { width: 100%; }
        .table-wrap {
          max-height: 620px;
          overflow: auto;
          width: 100%;
        }
        table {
          border-collapse: collapse;
          min-width: max-content;
          width: 100%;
        }
        th, td {
          border-bottom: 1px solid var(--divider-color);
          font-size: 13px;
          padding: 6px 8px;
          text-align: left;
          white-space: nowrap;
        }
        th {
          background: var(--card-background-color);
          position: sticky;
          top: 0;
          z-index: 1;
        }
        th button, .icon-button {
          background: transparent;
          border: 0;
          min-height: 0;
          padding: 0;
        }
        .entity-cell {
          background: transparent;
          border: 0;
          color: var(--primary-color, #1f6feb);
          font: inherit;
          min-height: 0;
          padding: 0;
          text-align: left;
        }
        .state {
          border-radius: 999px;
          display: inline-block;
          font-size: 12px;
          line-height: 1;
          padding: 4px 8px;
        }
        .online {
          background: rgba(36, 161, 72, 0.14);
          color: #1a7f37;
        }
        .offline {
          background: rgba(207, 34, 46, 0.12);
          color: #cf222e;
        }
        .empty {
          color: var(--secondary-text-color);
          padding: 18px 8px;
          text-align: center;
        }
        .mobile-list { display: none; }
        .mobile-row {
          border-bottom: 1px solid var(--divider-color);
          display: grid;
          gap: 5px;
          padding: 10px 0;
        }
        .mobile-main {
          align-items: center;
          display: flex;
          gap: 8px;
          justify-content: space-between;
        }
        .mobile-fields {
          display: grid;
          gap: 4px 10px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .mobile-field { min-width: 0; }
        .mobile-label {
          color: var(--secondary-text-color);
          display: block;
          font-size: 11px;
        }
        .mobile-value {
          display: block;
          font-size: 13px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .pager {
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 8px;
        }
        .dialog {
          background: rgba(0, 0, 0, 0.35);
          inset: 0;
          position: fixed;
          z-index: 10;
        }
        .dialog-card {
          background: var(--card-background-color);
          border-radius: 8px;
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
          margin: 8vh auto;
          max-height: 80vh;
          max-width: 720px;
          overflow: auto;
          padding: 16px;
        }
        .dialog-head {
          align-items: center;
          display: flex;
          gap: 12px;
          justify-content: space-between;
          margin-bottom: 12px;
        }
        .details {
          display: grid;
          gap: 6px 14px;
          grid-template-columns: minmax(120px, max-content) 1fr;
        }
        .details div:nth-child(odd) {
          color: var(--secondary-text-color);
        }
        @media (max-width: 760px) {
          .wrap { padding: 10px; }
          .toolbar input,
          .toolbar select {
            flex: 1 1 calc(50% - 8px);
            min-width: 0;
          }
          .table-wrap { display: none; }
          .mobile-list { display: block; }
          .details { grid-template-columns: 1fr; }
        }
      </style>
    `;

    this.shadowRoot.getElementById("search").addEventListener("input", (event) => {
      this._search = event.target.value;
      this._page = 0;
      this._debouncedRefreshTable();
    });
    for (const key of ["state", "profile", "model", "uplink"]) {
      this.shadowRoot.getElementById(key).addEventListener("change", (event) => {
        this._filters[key] = event.target.value;
        this._page = 0;
        this._savePreferences();
        this._refreshTable();
      });
    }
    this.shadowRoot.getElementById("clear-filters").addEventListener("click", () => this._clearFilters());
    this.shadowRoot.getElementById("options").addEventListener("click", (event) => {
      event.stopPropagation();
      this._toggleOptions();
    });
    this.shadowRoot.getElementById("options-menu").addEventListener("click", (event) => event.stopPropagation());
    this.shadowRoot.addEventListener("click", () => this._closeOptions());
    this.shadowRoot.getElementById("reset").addEventListener("click", () => this._resetPreferences());
    this.shadowRoot.getElementById("page-size").addEventListener("change", (event) => {
      this._pageSize = Number(event.target.value);
      this._page = 0;
      this._savePreferences();
      this._refreshTable();
    });
    this.shadowRoot.getElementById("prev").addEventListener("click", () => {
      this._page = Math.max(0, this._page - 1);
      this._refreshTable();
    });
    this.shadowRoot.getElementById("next").addEventListener("click", () => {
      this._page += 1;
      this._refreshTable();
    });
    this.shadowRoot.getElementById("dialog-close").addEventListener("click", () => {
      this.shadowRoot.getElementById("dialog").hidden = true;
    });
    this._refreshPageSize();
    this._renderHeaders();
    this._refreshColumnPicker();
    this._refreshFilterOptions();
    this._shellRendered = true;
  }

  _renderHeaders() {
    const defs = new Map(this._columnDefs().map((col) => [col.key, col]));
    this.shadowRoot.getElementById("headers").innerHTML = this._activeColumns()
      .map((key) => defs.get(key))
      .filter(Boolean)
      .map((col) => this._header(col.key, col.label))
      .join("");
    for (const button of this.shadowRoot.querySelectorAll("th button[data-key]")) {
      button.addEventListener("click", () => this._sort(button.dataset.key));
    }
  }

  _refreshColumnPicker() {
    const panel = this.shadowRoot.getElementById("column-panel");
    const selected = this._activeColumns();
    panel.innerHTML = this._columnDefs()
      .map((col) => `
        <label>
          <input type="checkbox" value="${this._escape(col.key)}" ${selected.includes(col.key) ? "checked" : ""}>
          ${this._escape(col.label)}
        </label>`)
      .join("");
    for (const input of panel.querySelectorAll("input")) {
      input.addEventListener("change", () => {
        const checked = Array.from(panel.querySelectorAll("input:checked")).map((item) => item.value);
        this._setActiveColumns(this._validColumns(checked, this._activeDefaultColumns()));
        this._savePreferences();
        this._refreshColumnPicker();
        this._renderHeaders();
        this._refreshTable();
      });
    }
  }

  _refreshPageSize() {
    const select = this.shadowRoot.getElementById("page-size");
    const options = [...new Set([...(this._config.page_size_options || []), this._pageSize, 0])];
    select.innerHTML = options
      .filter((value) => Number.isFinite(Number(value)))
      .map((value) => `<option value="${Number(value)}">${Number(value) === 0 ? "All" : `${Number(value)} rows`}</option>`)
      .join("");
    select.value = String(this._pageSize);
  }

  _refreshTable() {
    this._renderShell();
    const filtered = this._filteredRows();
    const rows = this._pageRows(filtered);
    const start = filtered.length === 0 ? 0 : this._pageSize === 0 ? 1 : this._page * this._pageSize + 1;
    const end = this._pageSize === 0 ? filtered.length : Math.min(filtered.length, start + rows.length - 1);
    this.shadowRoot.getElementById("meta").textContent =
      `${filtered.length} matched of ${this._rows.length}${this._error ? ` - ${this._error}` : ""}`;
    this.shadowRoot.getElementById("page-info").textContent =
      this._pageSize === 0 ? `All ${filtered.length}` : `${start}-${end} of ${filtered.length}`;
    this.shadowRoot.getElementById("prev").disabled = this._page <= 0 || this._pageSize === 0;
    this.shadowRoot.getElementById("next").disabled = this._pageSize === 0 || (this._page + 1) * this._pageSize >= filtered.length;
    this.shadowRoot.getElementById("clear-filters").hidden = !this._hasActiveFilters();
    const defs = new Map(this._columnDefs().map((col) => [col.key, col]));
    const columns = this._activeColumns();
    this.shadowRoot.getElementById("rows").innerHTML = rows.length
      ? rows.map((row, index) => `<tr>${columns.map((key) => `<td>${this._renderCell(row, defs.get(key), index)}</td>`).join("")}</tr>`).join("")
      : `<tr><td class="empty" colspan="${columns.length || 1}">No matching access points</td></tr>`;
    this.shadowRoot.getElementById("mobile-rows").innerHTML = rows.length
      ? rows.map((row, index) => this._mobileRow(row, index, defs, columns)).join("")
      : `<div class="empty">No matching access points</div>`;
    for (const button of this.shadowRoot.querySelectorAll("button[data-details]")) {
      button.addEventListener("click", () => this._showDetails(rows[Number(button.dataset.details)]));
    }
    for (const button of this.shadowRoot.querySelectorAll("button[data-entity]")) {
      button.addEventListener("click", () => this._openMoreInfo(button.dataset.entity));
    }
  }

  _mobileRow(row, index, defs, columns) {
    const main = row.alias || row.ip || row.mac || "Access point";
    const fields = columns.filter((key) => key !== "details").slice(0, 6);
    return `
      <div class="mobile-row">
        <div class="mobile-main">
          <strong>${this._escape(main)}</strong>
          ${this._detailsButton(index)}
        </div>
        <div class="mobile-fields">
          ${fields.map((key) => `<div class="mobile-field"><span class="mobile-label">${this._escape(defs.get(key).label)}</span><span class="mobile-value">${this._renderCell(row, defs.get(key), index)}</span></div>`).join("")}
        </div>
      </div>`;
  }

  _renderCell(row, col, index) {
    if (col.key === "details") {
      return col.render(row, index);
    }
    const value = col.render(row, index);
    const entityId = col.entityKey && row.entities ? row.entities[col.entityKey] : null;
    if (!entityId) {
      return value;
    }
    return `<button class="entity-cell" type="button" data-entity="${this._escape(entityId)}" title="Open history">${value}</button>`;
  }

  _refreshFilterOptions() {
    if (!this.shadowRoot || !this._shellRendered) {
      return;
    }
    this._setOptions("profile", "Profile", (row) => row.profile);
    this._setOptions("model", "Model", (row) => row.model);
    this._setOptions("uplink", "Uplink", (row) => this._uplinkLabel(row));
    this.shadowRoot.getElementById("state").value = this._filters.state;
  }

  _setOptions(id, label, valueFn) {
    const element = this.shadowRoot.getElementById(id);
    const current = this._filters[id];
    const values = Array.from(new Set(this._rows.map(valueFn).filter((value) => value !== null && value !== undefined && value !== ""))).sort();
    element.innerHTML = [`<option value="">${label}</option>`, ...values.map((value) => `<option value="${this._escape(value)}">${this._escape(value)}</option>`)].join("");
    element.value = values.includes(current) ? current : "";
    this._filters[id] = element.value;
  }

  _sort(key) {
    if (key === "details") {
      return;
    }
    if (this._sortKey === key) {
      this._sortDir *= -1;
    } else {
      this._sortKey = key;
      this._sortDir = 1;
    }
    this._page = 0;
    this._savePreferences();
    this._renderHeaders();
    this._refreshTable();
  }

  _showDetails(row) {
    if (!row) {
      return;
    }
    this.shadowRoot.getElementById("dialog-title").textContent = row.alias || row.mac || "AP details";
    this.shadowRoot.getElementById("dialog-body").innerHTML = this._columnDefs()
      .filter((col) => col.key !== "details")
      .map((col) => `<div>${this._escape(col.label)}</div><div>${col.render(row)}</div>`)
      .join("");
    this.shadowRoot.getElementById("dialog").hidden = false;
  }

  _openMoreInfo(entityId) {
    if (!entityId) {
      return;
    }
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      bubbles: true,
      composed: true,
      detail: { entityId },
    }));
  }

  _clearFilters() {
    this._filters = { state: "", profile: "", model: "", uplink: "" };
    this._search = "";
    this._page = 0;
    this.shadowRoot.getElementById("search").value = "";
    this._refreshFilterOptions();
    this._savePreferences();
    this._refreshTable();
  }

  _hasActiveFilters() {
    return Boolean(this._search.trim() || Object.values(this._filters).some((value) => value));
  }

  _toggleOptions() {
    const menu = this.shadowRoot.getElementById("options-menu");
    menu.hidden = !menu.hidden;
  }

  _closeOptions() {
    this.shadowRoot.getElementById("options-menu").hidden = true;
  }

  _debouncedRefreshTable() {
    if (this._refreshTimer) {
      window.clearTimeout(this._refreshTimer);
    }
    this._refreshTimer = window.setTimeout(() => {
      this._refreshTimer = null;
      this._refreshTable();
    }, this._config.search_debounce_ms);
  }

  _detailsButton(index) {
    return `<button class="icon-button" type="button" data-details="${index}" title="More">More</button>`;
  }

  _stateCell(row) {
    const online = row.online === true;
    const label = online ? "Online" : "Offline";
    const cls = online ? "online" : "offline";
    return `<span class="state ${cls}">${label}</span>`;
  }

  _uplinkLabel(row) {
    if (row.uplink === null || row.uplink === undefined) {
      return "";
    }
    const port = row.uplink_port === null || row.uplink_port === undefined ? "" : ` ${row.uplink_port}`;
    if (row.uplink === 0) {
      return `LAN${port}`;
    }
    if (row.uplink === 2) {
      return `LAN-PON${port}`;
    }
    return `Uplink ${row.uplink}${port}`;
  }

  _compare(a, b) {
    if (a === b) {
      return 0;
    }
    if (a === null || a === undefined || a === "") {
      return 1;
    }
    if (b === null || b === undefined || b === "") {
      return -1;
    }
    const na = Number(a);
    const nb = Number(b);
    if (Number.isFinite(na) && Number.isFinite(nb)) {
      return na - nb;
    }
    return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  _header(key, label) {
    const suffix = this._sortKey === key ? (this._sortDir === 1 ? " ^" : " v") : "";
    return `<th><button data-key="${key}">${label}${suffix}</button></th>`;
  }
}

customElements.define("rltech-fttr-ap-table-card", RltechFttrApTableCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "rltech-fttr-ap-table-card",
  name: "RLTech FTTR AP Table",
  description: "Searchable RLTech FTTR access point inventory",
});
