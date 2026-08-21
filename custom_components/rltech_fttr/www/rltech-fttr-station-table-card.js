class RltechFttrStationTableCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._rows = [];
    this._search = "";
    this._filters = { ssid: "", ap: "", vlan: "", band: "", online: "" };
    this._sortKey = "mac";
    this._sortDir = 1;
    this._page = 0;
    this._pageSize = 25;
    this._mobilePageSize = 10;
    this._totalRows = 0;
    this._filteredCount = 0;
    this._pageCount = 1;
    this._filterOptions = {};
    this._columns = [];
    this._mobileColumns = [];
    this._error = "";
    this._lastFetch = 0;
    this._fetchTimer = null;
    this._fetchInFlight = false;
    this._fetchQueued = false;
    this._refreshTimer = null;
    this._shellRendered = false;
    this._isMobile = false;
    this._mediaQuery = null;
    this._entryResolving = null;
    this._resolvedEntryId = "";
    this._preferencesLoadedKey = "";
    this._activeDialog = null;
  }

  setConfig(config) {
    this._config = {
      page_size: 25,
      mobile_page_size: 10,
      page_size_options: [25, 50, 100],
      remember_preferences: true,
      refresh_interval_ms: 60000,
      search_debounce_ms: 150,
      columns: this._defaultColumns(),
      mobile_columns: this._defaultMobileColumns(),
      ...config,
    };
    this._pageSize = Number(this._config.page_size) || 25;
    this._mobilePageSize = Number(this._config.mobile_page_size) || 10;
    this._columns = this._validColumns(this._config.columns, this._defaultColumns());
    this._mobileColumns = this._validColumns(this._config.mobile_columns, this._defaultMobileColumns());
    this._setupMediaQuery();
    this._loadPreferences(true);
    this._renderShell();
    this._refreshTable();
  }

  set hass(hass) {
    const firstUpdate = !this._hass;
    this._hass = hass;
    if (firstUpdate || Date.now() - this._lastFetch >= this._autoRefreshMs()) {
      this._scheduleFetch(firstUpdate);
    }
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return {
      columns: "full",
      min_columns: 4,
    };
  }

  disconnectedCallback() {
    this._closeDialog();
    if (this._fetchTimer) {
      window.clearTimeout(this._fetchTimer);
      this._fetchTimer = null;
    }
    if (this._refreshTimer) {
      window.clearTimeout(this._refreshTimer);
      this._refreshTimer = null;
    }
  }

  static getStubConfig() {
    return {
      type: "custom:rltech-fttr-station-table-card",
    };
  }

  _columnDefs() {
    return [
      ["details", "More", (_row, index) => this._detailsButton(index), () => ""],
      ["mac", "MAC"],
      ["ip", "IP"],
      ["hostname", "Hostname"],
      ["ssid", "SSID"],
      ["ap_alias", "AP", (row) => this._escape(row.ap_alias || row.ap_mac), (row) => row.ap_alias || row.ap_mac],
      ["reported_online", "State", (row) => (row.reported_online ? "Active" : "Inactive"), (row) => (row.reported_online ? "active" : "inactive")],
      ["rssi", "RSSI dBm"],
      ["band", "Band"],
      ["channel", "Ch"],
      ["bandwidth", "Width"],
      ["vlan", "VLAN"],
      ["rx_rate", "RX Mbps"],
      ["tx_rate", "TX Mbps"],
      ["rx_nego_rate", "RX link"],
      ["tx_nego_rate", "TX link"],
      ["uptime", "Uptime", (row) => this._escape(this._formatDuration(row.uptime)), (row) => row.uptime],
      ["last_seen", "Last seen", (row) => this._escape(this._formatLastSeen(row.last_seen)), (row) => row.last_seen],
      ["alias", "Alias"],
      ["ap_mac", "AP MAC"],
      ["total_count", "Total"],
    ].map(([key, label, render, sort]) => ({
      key,
      label,
      render: render || ((row) => this._escape(row[key])),
      sort: sort || ((row) => row[key]),
    }));
  }

  _defaultColumns() {
    return ["hostname", "ip", "ssid", "ap_alias", "reported_online", "rssi", "details"];
  }

  _defaultMobileColumns() {
    return ["hostname", "ip", "ssid", "ap_alias", "reported_online", "rssi", "details"];
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

  _activePageSize() {
    return this._isMobile ? this._mobilePageSize : this._pageSize;
  }

  _setActivePageSize(value) {
    if (this._isMobile) {
      this._mobilePageSize = value;
    } else {
      this._pageSize = value;
    }
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
        this._refreshPageSize();
        this._refreshMobileSortControls();
        this._scheduleFetch(true);
      }
    };
    if (this._mediaQuery.addEventListener) {
      this._mediaQuery.addEventListener("change", listener);
    } else {
      this._mediaQuery.addListener(listener);
    }
  }

  _storageKey() {
    const key = this._config.storage_key || this._config.entry_id || this._resolvedEntryId || "auto";
    return `rltech_fttr.station_table.${key}`;
  }

  _legacyStorageKeys() {
    if (this._config.storage_key || this._config.entry_id || !this._resolvedEntryId) {
      return [];
    }
    return ["rltech_fttr.station_table.auto"];
  }

  _loadPreferences(force = false) {
    const storageKey = this._storageKey();
    if (
      !this._config.remember_preferences ||
      (!force && this._preferencesLoadedKey === storageKey)
    ) {
      return;
    }
    this._preferencesLoadedKey = storageKey;
    try {
      let raw = window.localStorage.getItem(storageKey);
      let sourceKey = storageKey;
      if (!raw) {
        for (const key of this._legacyStorageKeys()) {
          raw = window.localStorage.getItem(key);
          if (raw) {
            sourceKey = key;
            break;
          }
        }
      }
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
      if (Number.isFinite(Number(prefs.mobile_page_size))) {
        this._mobilePageSize = Number(prefs.mobile_page_size);
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
      if (sourceKey !== storageKey) {
        this._savePreferences();
      }
    } catch (_) {
      window.localStorage.removeItem(storageKey);
    }
  }

  _savePreferences() {
    if (!this._config.remember_preferences) {
      return;
    }
    try {
      window.localStorage.setItem(
        this._storageKey(),
        JSON.stringify({
          columns: this._columns,
          mobile_columns: this._mobileColumns,
          page_size: this._pageSize,
          mobile_page_size: this._mobilePageSize,
          sort_key: this._sortKey,
          sort_dir: this._sortDir,
          filters: this._filters,
        })
      );
    } catch (_) {
      // Browser storage can be unavailable in restricted web views.
    }
  }

  _resetPreferences() {
    try {
      window.localStorage.removeItem(this._storageKey());
      for (const key of this._legacyStorageKeys()) {
        window.localStorage.removeItem(key);
      }
    } catch (_) {
      // Browser storage can be unavailable in restricted web views.
    }
    this._columns = this._validColumns(this._config.columns, this._defaultColumns());
    this._mobileColumns = this._validColumns(this._config.mobile_columns, this._defaultMobileColumns());
    this._pageSize = Number(this._config.page_size) || 25;
    this._mobilePageSize = Number(this._config.mobile_page_size) || 10;
    this._sortKey = "mac";
    this._sortDir = 1;
    this._filters = { ssid: "", ap: "", vlan: "", band: "", online: "" };
    this._search = "";
    this._page = 0;
    this.shadowRoot.getElementById("search").value = "";
    this._closeOptions();
    this._refreshFilterOptions();
    this._refreshColumnPicker();
    this._refreshPageSize();
    this._renderHeaders();
    this._refreshMobileSortControls();
    this._scheduleFetch(true);
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

  _scheduleFetch(immediate = false) {
    if (!this._hass) {
      return;
    }
    if (this._fetchInFlight) {
      if (immediate) {
        this._fetchQueued = true;
      }
      return;
    }
    const wait = immediate ? 0 : Math.max(0, 5000 - (Date.now() - this._lastFetch));
    if (this._fetchTimer) {
      if (immediate) {
        window.clearTimeout(this._fetchTimer);
        this._fetchTimer = null;
      } else {
        return;
      }
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
    if (this._fetchInFlight) {
      this._fetchQueued = true;
      return;
    }
    this._fetchInFlight = true;
    try {
      const entryId = await this._entryId();
      if (!entryId) {
        return;
      }
      const result = await this._hass.callWS({
        type: "rltech_fttr/get_stations",
        entry_id: entryId,
        page: this._page,
        page_size: this._activePageSize(),
        search: this._search,
        sort_key: this._sortKey,
        sort_dir: this._sortDir,
        filters: this._filters,
      });
      this._rows = result.stations || [];
      this._page = Number(result.page || 0);
      this._totalRows = Number(result.total || 0);
      this._filteredCount = Number(result.filtered || 0);
      this._pageCount = Number(result.page_count || 1);
      this._filterOptions = result.filter_options || {};
      this._error = "";
      this._refreshFilterOptions();
      this._refreshPageSize();
    } catch (err) {
      this._error = err.message || String(err);
    } finally {
      this._lastFetch = Date.now();
      this._fetchInFlight = false;
      this._refreshTable();
      if (this._fetchQueued) {
        this._fetchQueued = false;
        this._scheduleFetch(true);
      }
    }
  }

  _autoRefreshMs() {
    const configured = Number(this._config?.refresh_interval_ms);
    return Number.isFinite(configured) && configured >= 10000 ? configured : 60000;
  }

  async _entryId() {
    if (this._config.entry_id) {
      this._loadPreferences();
      if (this._shellRendered) {
        this._refreshPageSize();
      }
      return this._config.entry_id;
    }
    if (!this._entryResolving) {
      this._entryResolving = this._hass.callWS({ type: "rltech_fttr/get_entries" });
    }
    try {
      const result = await this._entryResolving;
      const entries = result.entries || [];
      if (entries.length === 1) {
        this._resolvedEntryId = entries[0].entry_id;
        this._loadPreferences(true);
        this._refreshColumnPicker();
        this._renderHeaders();
        this._refreshPageSize();
        return this._resolvedEntryId;
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
        if (this._filters.ssid && row.ssid !== this._filters.ssid) {
          return false;
        }
        if (this._filters.ap && (row.ap_alias || row.ap_mac || "") !== this._filters.ap) {
          return false;
        }
        if (this._filters.vlan && String(row.vlan ?? "") !== this._filters.vlan) {
          return false;
        }
        if (this._filters.band && row.band !== this._filters.band) {
          return false;
        }
        if (this._filters.online) {
          const state = row.reported_online ? "active" : "inactive";
          if (state !== this._filters.online) {
            return false;
          }
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
    const pageSize = this._activePageSize();
    if (pageSize === 0) {
      return rows;
    }
    const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
    this._page = Math.min(this._page, pageCount - 1);
    const start = this._page * pageSize;
    return rows.slice(start, start + pageSize);
  }

  _renderShell() {
    if (!this.shadowRoot || this._shellRendered) {
      return;
    }
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="wrap">
          <div class="toolbar">
            <input id="search" type="search" placeholder="Search stations" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
            <select id="ssid"></select>
            <select id="ap"></select>
            <select id="vlan"></select>
            <select id="band"></select>
            <select id="online">
              <option value="">State</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
            <button id="clear-filters" type="button" hidden>Clear</button>
            <select id="page-size" title="Rows per page"></select>
            <select id="mobile-sort" class="mobile-sort" title="Sort field" aria-label="Sort field"></select>
            <button id="mobile-sort-dir" class="mobile-sort mobile-sort-dir" type="button" title="Sort direction" aria-label="Sort direction"></button>
            <div class="options">
              <button id="options" class="options-button" type="button" title="Table options" aria-label="Table options">
                <span></span><span></span><span></span>
              </button>
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
        ha-card, .wrap, table, th, td, button, .mobile-list, .details {
          -webkit-user-select: text;
          user-select: text;
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
          flex: 0 1 132px;
          min-width: 92px;
        }
        .mobile-sort { display: none; }
        .mobile-sort-dir {
          flex: 0 0 42px;
          min-width: 42px;
          padding: 0;
        }
        input:not([type="checkbox"]), select, button {
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
        .table-wrap {
          overflow-x: auto;
          overflow-y: visible;
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
        .mobile-field {
          min-width: 0;
        }
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
        @media (max-width: 760px) {
          .wrap { padding: 10px; }
          .toolbar input,
          .toolbar select {
            flex: 1 1 calc(50% - 8px);
            min-width: 0;
          }
          .mobile-sort { display: block; }
          .mobile-sort-dir {
            align-items: center;
            display: inline-flex;
            justify-content: center;
          }
          .options { position: static; }
          .table-wrap { display: none; }
          .mobile-list { display: block; }
        }
      </style>
    `;

    this.shadowRoot.getElementById("search").addEventListener("input", (event) => {
      this._search = event.target.value;
      this._page = 0;
      this._debouncedFetch();
    });
    for (const key of ["ssid", "ap", "vlan", "band", "online"]) {
      this.shadowRoot.getElementById(key).addEventListener("change", (event) => {
        this._filters[key] = event.target.value;
        this._page = 0;
        this._savePreferences();
        this._scheduleFetch(true);
      });
    }
    this.shadowRoot.getElementById("clear-filters").addEventListener("click", () => this._clearFilters());
    this.shadowRoot.getElementById("options").addEventListener("click", (event) => {
      event.stopPropagation();
      this._toggleOptions();
    });
    this.shadowRoot.getElementById("page-size").addEventListener("change", (event) => {
      this._setActivePageSize(Number(event.target.value));
      this._page = 0;
      this._savePreferences();
      this._scheduleFetch(true);
    });
    this.shadowRoot.getElementById("mobile-sort").addEventListener("change", (event) => {
      this._sortKey = event.target.value;
      this._page = 0;
      this._savePreferences();
      this._renderHeaders();
      this._refreshMobileSortControls();
      this._scheduleFetch(true);
    });
    this.shadowRoot.getElementById("mobile-sort-dir").addEventListener("click", () => {
      this._sortDir *= -1;
      this._page = 0;
      this._savePreferences();
      this._renderHeaders();
      this._refreshMobileSortControls();
      this._scheduleFetch(true);
    });
    this.shadowRoot.getElementById("prev").addEventListener("click", () => {
      this._page = Math.max(0, this._page - 1);
      this._scheduleFetch(true);
    });
    this.shadowRoot.getElementById("next").addEventListener("click", () => {
      this._page += 1;
      this._scheduleFetch(true);
    });
    this._refreshPageSize();
    this._renderHeaders();
    this._refreshMobileSortControls();
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

  _refreshMobileSortControls() {
    const select = this.shadowRoot.getElementById("mobile-sort");
    const button = this.shadowRoot.getElementById("mobile-sort-dir");
    if (!select || !button) {
      return;
    }
    const columns = this._columnDefs().filter((col) => col.key !== "details");
    select.innerHTML = columns
      .map((col) => `<option value="${this._escape(col.key)}">${this._escape(col.label)}</option>`)
      .join("");
    if (!columns.some((col) => col.key === this._sortKey)) {
      this._sortKey = columns[0]?.key || "";
    }
    select.value = this._sortKey;
    button.textContent = this._sortDir === 1 ? "^" : "v";
  }

  _refreshColumnPicker() {
    const panel = this._activeDialog?.querySelector("[data-column-panel]");
    if (!panel) {
      return;
    }
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
    const pageSize = this._activePageSize();
    const options = [...new Set([...(this._config.page_size_options || []), pageSize, 0])];
    select.innerHTML = options
      .filter((value) => Number.isFinite(Number(value)))
      .map((value) => `<option value="${Number(value)}">${Number(value) === 0 ? "All" : `${Number(value)} rows`}</option>`)
      .join("");
    select.value = String(pageSize);
  }

  _refreshTable() {
    this._renderShell();
    const rows = this._rows;
    const pageSize = this._activePageSize();
    const start = this._filteredCount === 0 ? 0 : pageSize === 0 ? 1 : this._page * pageSize + 1;
    const end = pageSize === 0 ? this._filteredCount : Math.min(this._filteredCount, start + rows.length - 1);
    this.shadowRoot.getElementById("meta").textContent =
      `${this._filteredCount} matched of ${this._totalRows}${this._error ? ` - ${this._error}` : ""}`;
    this.shadowRoot.getElementById("page-info").textContent =
      pageSize === 0 ? `All ${this._filteredCount}` : `${start}-${end} of ${this._filteredCount}`;
    this.shadowRoot.getElementById("prev").disabled = this._page <= 0 || pageSize === 0;
    this.shadowRoot.getElementById("next").disabled = pageSize === 0 || this._page >= this._pageCount - 1;
    this.shadowRoot.getElementById("clear-filters").hidden = !this._hasActiveFilters();
    const defs = new Map(this._columnDefs().map((col) => [col.key, col]));
    const columns = this._activeColumns();
    this.shadowRoot.getElementById("rows").innerHTML = rows.length
      ? rows.map((row, index) => `<tr>${columns.map((key) => `<td>${defs.get(key).render(row, index)}</td>`).join("")}</tr>`).join("")
      : `<tr><td class="empty" colspan="${columns.length || 1}">No matching stations</td></tr>`;
    this.shadowRoot.getElementById("mobile-rows").innerHTML = rows.length
      ? rows.map((row, index) => this._mobileRow(row, index, defs, columns)).join("")
      : `<div class="empty">No matching stations</div>`;
    for (const button of this.shadowRoot.querySelectorAll("button[data-details]")) {
      button.addEventListener("click", () => this._showDetails(rows[Number(button.dataset.details)]));
    }
  }

  _mobileRow(row, index, defs, columns) {
    const main = row.hostname || row.ip || row.mac || "Station";
    const fields = columns.filter((key) => key !== "details").slice(0, 6);
    return `
      <div class="mobile-row">
        <div class="mobile-main">
          <strong>${this._escape(main)}</strong>
          ${this._detailsButton(index)}
        </div>
        <div class="mobile-fields">
          ${fields.map((key) => `<div class="mobile-field"><span class="mobile-label">${this._escape(defs.get(key).label)}</span><span class="mobile-value">${defs.get(key).render(row, index)}</span></div>`).join("")}
        </div>
      </div>`;
  }

  _refreshFilterOptions() {
    if (!this.shadowRoot || !this._shellRendered) {
      return;
    }
    this._setOptions("ssid", "SSID");
    this._setOptions("ap", "AP");
    this._setOptions("vlan", "VLAN");
    this._setOptions("band", "Band");
    this.shadowRoot.getElementById("online").value = this._filters.online;
  }

  _setOptions(id, label) {
    const element = this.shadowRoot.getElementById(id);
    const current = this._filters[id];
    const values = (this._filterOptions[id] || []).map((value) => String(value));
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
    this._refreshMobileSortControls();
    this._scheduleFetch(true);
  }

  _showDetails(row) {
    if (!row) {
      return;
    }
    const body = this._columnDefs()
      .filter((col) => col.key !== "details")
      .map((col) => `<div>${this._escape(col.label)}</div><div>${col.render(row)}</div>`)
      .join("");
    this._showDialog(row.mac || "Station details", `<div class="details">${body}</div>`);
  }

  _clearFilters() {
    this._filters = { ssid: "", ap: "", vlan: "", band: "", online: "" };
    this._search = "";
    this._page = 0;
    this.shadowRoot.getElementById("search").value = "";
    this._refreshFilterOptions();
    this._savePreferences();
    this._scheduleFetch(true);
  }

  _hasActiveFilters() {
    return Boolean(this._search.trim() || Object.values(this._filters).some((value) => value));
  }

  _toggleOptions() {
    this._showDialog(
      "Table options",
      `
        <div class="menu-title">Columns</div>
        <div data-column-panel class="column-panel"></div>
        <div class="menu-title">View</div>
        <div class="dialog-actions">
          <button data-reset class="menu-button" type="button">Reset view</button>
        </div>`,
      { kind: "options", maxWidth: 420 },
    );
    this._activeDialog.querySelector("[data-reset]").addEventListener("click", () => this._resetPreferences());
    this._refreshColumnPicker();
  }

  _closeOptions() {
    if (this._activeDialog?.dataset.kind === "options") {
      this._closeDialog();
    }
  }

  _showDialog(title, body, options = {}) {
    this._closeDialog();
    const overlay = document.createElement("div");
    overlay.className = "rltech-fttr-dialog";
    overlay.dataset.kind = options.kind || "details";
    overlay.innerHTML = `
      <style>
        .rltech-fttr-dialog {
          align-items: flex-start;
          background: rgba(0, 0, 0, 0.35);
          box-sizing: border-box;
          display: flex;
          inset: 0;
          justify-content: center;
          padding: 8vh 10px 16px;
          position: fixed;
          z-index: 2147483647;
        }
        .rltech-fttr-dialog-card {
          background: var(--card-background-color, #fff);
          border-radius: 8px;
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
          box-sizing: border-box;
          color: var(--primary-text-color, #111);
          max-height: 80vh;
          max-width: ${Number(options.maxWidth) || 720}px;
          overflow: auto;
          padding: 16px;
          width: min(100%, ${Number(options.maxWidth) || 720}px);
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
        .details div:nth-child(odd),
        .menu-title {
          color: var(--secondary-text-color, #666);
        }
        .menu-title {
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
          gap: 8px;
          line-height: 1.3;
          min-height: 28px;
          white-space: nowrap;
        }
        .column-panel input[type="checkbox"] {
          flex: 0 0 auto;
          height: 16px;
          margin: 0;
          width: 16px;
        }
        .dialog-actions {
          margin-top: 10px;
        }
        .menu-button {
          width: 100%;
        }
        @media (max-width: 760px) {
          .rltech-fttr-dialog {
            padding-top: 4vh;
          }
          .rltech-fttr-dialog-card {
            max-height: 88vh;
            max-width: none;
            width: calc(100vw - 20px);
          }
          .details {
            grid-template-columns: 1fr;
          }
          .column-panel {
            gap: 10px;
          }
          .column-panel label {
            font-size: 15px;
          }
          .column-panel input[type="checkbox"] {
            height: 20px;
            width: 20px;
          }
        }
      </style>
      <div class="rltech-fttr-dialog-card" role="dialog" aria-modal="true">
        <div class="dialog-head">
          <strong>${this._escape(title)}</strong>
          <button data-close type="button">Close</button>
        </div>
        ${body}
      </div>`;
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) {
        this._closeDialog();
      }
    });
    overlay.querySelector("[data-close]").addEventListener("click", () => this._closeDialog());
    document.body.appendChild(overlay);
    this._activeDialog = overlay;
  }

  _closeDialog() {
    if (this._activeDialog) {
      this._activeDialog.remove();
      this._activeDialog = null;
    }
  }

  _debouncedFetch() {
    if (this._refreshTimer) {
      window.clearTimeout(this._refreshTimer);
    }
    this._refreshTimer = window.setTimeout(() => {
      this._refreshTimer = null;
      this._scheduleFetch(true);
    }, this._config.search_debounce_ms);
  }

  _detailsButton(index) {
    return `<button class="icon-button" type="button" data-details="${index}" title="More">More</button>`;
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

  _formatDuration(seconds) {
    const total = Number(seconds);
    if (!Number.isFinite(total) || total < 0) {
      return "";
    }
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = Math.floor(total % 60);
    if (days > 0) {
      return `${days}d ${hours}h`;
    }
    if (hours > 0) {
      return `${hours}h ${minutes}m`;
    }
    if (minutes > 0) {
      return `${minutes}m ${secs}s`;
    }
    return `${secs}s`;
  }

  _formatLastSeen(value) {
    if (!value) {
      return "";
    }
    const timestamp = Date.parse(value);
    if (!Number.isFinite(timestamp)) {
      return value;
    }
    const ageSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
    return `${this._formatDuration(ageSeconds)} ago`;
  }
}

customElements.define("rltech-fttr-station-table-card", RltechFttrStationTableCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "rltech-fttr-station-table-card",
  name: "RLTech FTTR Station Table",
  description: "Searchable RLTech FTTR Wi-Fi station inventory",
});
