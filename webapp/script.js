/* PrimePatent - Dataiku Standard Webapp 프론트엔드 (의존 라이브러리 없음) */
(function () {
  "use strict";

  // ------------------------------------------------------------ 공통
  function apiUrl(path) {
    var clean = String(path || "").replace(/^\//, "");
    if (typeof getWebAppBackendUrl === "function") {
      return getWebAppBackendUrl(clean);           // Dataiku webapp
    }
    return "/" + clean;                            // 로컬 standalone
  }

  function request(path, options) {
    options = options || {};
    var init = { method: options.method || "GET", headers: {} };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    return fetch(apiUrl(path), init).then(function (response) {
      return response.json().catch(function () {
        throw new Error("서버 응답을 해석할 수 없습니다 (HTTP " + response.status + ")");
      }).then(function (data) {
        if (!response.ok || data.ok === false) {
          throw new Error(data.error || ("요청 실패 (HTTP " + response.status + ")"));
        }
        return data;
      });
    });
  }

  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  function esc(value) { return value === null || value === undefined ? "" : String(value); }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function num(value, digits) {
    if (value === null || value === undefined || value === "") return "-";
    var parsed = Number(value);
    return isNaN(parsed) ? esc(value) : parsed.toFixed(digits === undefined ? 1 : digits);
  }

  var toastTimer = null;
  function toast(message, kind) {
    var node = $("pp-toast");
    node.className = "pp-toast" + (kind ? " pp-toast-" + kind : "");
    node.textContent = message;
    node.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.hidden = true; }, kind === "err" ? 8000 : 4000);
  }

  // ------------------------------------------------------------ 상태
  var state = {
    health: null,
    fields: [],
    upload: null,
    mapping: {},
    mappingReport: null,
    jobId: null,
    runId: null,
    pollTimer: null,
    result: null,
    page: 0,
    pageSize: 100,
    sort: "rank",
    order: "asc",
    total: 0,
    source: null            // {type:'job'|'run', id:...}
  };

  // ------------------------------------------------------------ 탭
  function setTab(name) {
    Array.prototype.forEach.call(document.querySelectorAll(".pp-tab"), function (tab) {
      tab.classList.toggle("pp-tab-active", tab.dataset.tab === name);
    });
    Array.prototype.forEach.call(document.querySelectorAll(".pp-panel"), function (panel) {
      panel.classList.toggle("pp-panel-active", panel.dataset.panel === name);
    });
  }
  function enableTab(name, enabled) {
    var tab = document.querySelector('.pp-tab[data-tab="' + name + '"]');
    if (tab) tab.disabled = !enabled;
  }

  // ------------------------------------------------------------ 초기화
  function init() {
    document.querySelectorAll(".pp-tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        if (!tab.disabled) setTab(tab.dataset.tab);
      });
    });

    request("/api/health").then(function (data) {
      state.health = data;
      $("pp-storage-badge").textContent = "저장소: " +
        (data.storage === "dataiku" ? "Dataiku 관리 폴더" : "로컬 디렉터리");
      $("pp-storage-badge").className = "pp-badge " +
        (data.storage === "dataiku" ? "pp-badge-ok" : "pp-badge-warn");
      var select = $("cfg-llm-id");
      data.llmCandidates.forEach(function (candidate) {
        var option = el("option", null, candidate.label);
        option.value = candidate.id;
        select.appendChild(option);
      });
      select.value = data.defaultLlmId;
      buildWeightInputs(data.defaultConfig);
      applyConfig(data.defaultConfig);
      probeLlm(true);
    }).catch(function (error) { toast("초기화 실패: " + error.message, "err"); });

    request("/api/fields").then(function (data) { state.fields = data.fields; })
      .catch(function () { /* 매핑 화면에서 재시도 */ });

    bindUpload();
    bindMapping();
    bindConfig();
    bindResult();
    bindLibrary();
    loadRuns();
  }

  // ------------------------------------------------------------ 업로드
  function bindUpload() {
    var input = $("pp-file");
    $("pp-file-btn").addEventListener("click", function () { input.click(); });
    input.addEventListener("change", function () {
      if (input.files && input.files[0]) uploadFile(input.files[0]);
    });
    var zone = $("pp-dropzone");
    ["dragenter", "dragover"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault(); zone.classList.add("pp-dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault(); zone.classList.remove("pp-dragover");
      });
    });
    zone.addEventListener("drop", function (event) {
      var files = event.dataTransfer && event.dataTransfer.files;
      if (files && files[0]) uploadFile(files[0]);
    });
    $("pp-sheet").addEventListener("change", function () {
      if (!state.upload) return;
      request("/api/upload/" + state.upload.uploadId + "/sheet",
              { method: "POST", body: { sheet: $("pp-sheet").value } })
        .then(function (data) { applyUpload(data.upload); toast("시트를 다시 읽었습니다.", "ok"); })
        .catch(function (error) { toast(error.message, "err"); });
    });
  }

  function uploadFile(file) {
    $("pp-file-name").textContent = file.name + " (" + (file.size / 1024 / 1024).toFixed(2) + " MB)";
    var progress = $("pp-upload-progress");
    var bar = progress.querySelector(".pp-progress-bar");
    progress.hidden = false;
    bar.style.width = "0%";

    var form = new FormData();
    form.append("file", file);
    var xhr = new XMLHttpRequest();
    xhr.open("POST", apiUrl("/api/upload"));
    xhr.upload.onprogress = function (event) {
      if (event.lengthComputable) bar.style.width = (event.loaded / event.total * 100) + "%";
    };
    xhr.onload = function () {
      progress.hidden = true;
      var data;
      try { data = JSON.parse(xhr.responseText); }
      catch (error) { toast("업로드 응답을 해석할 수 없습니다.", "err"); return; }
      if (xhr.status >= 400 || data.ok === false) {
        toast(data.error || "업로드 실패", "err");
        return;
      }
      applyUpload(data.upload);
      toast("업로드 완료: " + data.upload.meta.rowCount + "행", "ok");
      setTab("mapping");
    };
    xhr.onerror = function () { progress.hidden = true; toast("업로드 중 네트워크 오류", "err"); };
    xhr.send(form);
  }

  function applyUpload(upload) {
    state.upload = upload;
    // 원본(자동매핑)을 그대로 참조하면 사용자가 수정할 때 함께 변경되어
    // '자동 매핑으로 되돌리기' 가 동작하지 않는다. 반드시 복사본을 사용한다.
    state.mapping = clone(upload.mapping || {});
    state.mappingReport = upload.mappingReport || null;

    var meta = upload.meta || {};
    var summary = $("pp-upload-summary");
    summary.innerHTML = "";
    [["파일", upload.fileName], ["시트", upload.sheet || "-"],
     ["행 수", meta.rowCount], ["컬럼 수", meta.columnCount],
     ["헤더 행", (meta.headerRow || 0) + 1],
     ["자동 매핑", (upload.mappingReport ? upload.mappingReport.mappedCount : 0) + " 항목"]
    ].forEach(function (pair) {
      var box = el("div", "pp-metric");
      box.appendChild(el("div", "pp-metric-label", pair[0]));
      box.appendChild(el("div", "pp-metric-value", esc(pair[1])));
      summary.appendChild(box);
    });
    summary.hidden = false;

    var sheetRow = $("pp-sheet-row");
    if (upload.sheets && upload.sheets.length > 1) {
      var select = $("pp-sheet");
      select.innerHTML = "";
      upload.sheets.forEach(function (name) {
        var option = el("option", null, name);
        option.value = name;
        select.appendChild(option);
      });
      select.value = upload.sheet;
      sheetRow.hidden = false;
    } else {
      sheetRow.hidden = true;
    }

    renderPreview(upload);
    renderMapping();
    enableTab("mapping", true);
    enableTab("config", true);
  }

  function renderPreview(upload) {
    var table = $("pp-preview");
    table.innerHTML = "";
    if (!upload.headers || !upload.headers.length) { $("pp-preview-wrap").hidden = true; return; }
    var head = el("thead"); var headRow = el("tr");
    upload.headers.forEach(function (header) { headRow.appendChild(el("th", null, header)); });
    head.appendChild(headRow); table.appendChild(head);
    var body = el("tbody");
    (upload.preview || []).forEach(function (row) {
      var tr = el("tr");
      upload.headers.forEach(function (header) {
        tr.appendChild(el("td", null, row[header] === null || row[header] === undefined ? "" : row[header]));
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    $("pp-preview-wrap").hidden = false;
  }

  // ------------------------------------------------------------ 매핑
  function bindMapping() {
    $("pp-map-search").addEventListener("input", renderMapping);
    $("pp-map-only-unmapped").addEventListener("change", renderMapping);
    $("pp-map-only-important").addEventListener("change", renderMapping);
    $("pp-map-reset").addEventListener("click", function () {
      if (!state.upload) return;
      state.mapping = clone(state.upload.mapping || {});
      validateMapping();
    });
    $("pp-map-next").addEventListener("click", function () { setTab("config"); });
  }

  function renderMapping() {
    var tbody = document.querySelector("#pp-map-table tbody");
    tbody.innerHTML = "";
    if (!state.upload) return;
    if (!state.fields.length) {
      request("/api/fields").then(function (data) { state.fields = data.fields; renderMapping(); });
      return;
    }

    var keyword = ($("pp-map-search").value || "").trim().toLowerCase();
    var onlyUnmapped = $("pp-map-only-unmapped").checked;
    var importantFirst = $("pp-map-only-important").checked;
    var fields = state.fields.slice();
    if (importantFirst) {
      fields.sort(function (a, b) {
        var rank = function (f) { return (f.required ? 0 : (f.important ? 1 : 2)); };
        return rank(a) - rank(b);
      });
    }

    fields.forEach(function (field) {
      var info = state.mapping[field.key];
      if (onlyUnmapped && info) return;
      if (keyword) {
        var blob = (field.label + " " + field.key + " " + (field.aliases || []).join(" ")).toLowerCase();
        if (blob.indexOf(keyword) < 0) return;
      }
      var tr = el("tr");
      var kind = field.required ? "필수" : (field.important ? "주요" : "선택");
      var kindCell = el("td");
      var badge = el("span", "pp-badge " + (field.required ? "pp-badge-err" :
                    (field.important ? "pp-badge-warn" : "pp-badge-muted")), kind);
      kindCell.appendChild(badge);
      tr.appendChild(kindCell);
      tr.appendChild(el("td", null, field.label));

      var selectCell = el("td");
      var select = el("select", "pp-input");
      var none = el("option", null, "(미사용)");
      none.value = "__none__";
      select.appendChild(none);
      (state.upload.headers || []).forEach(function (header) {
        var option = el("option", null, header);
        option.value = header;
        select.appendChild(option);
      });
      select.value = info ? info.column : "__none__";
      select.addEventListener("change", function () {
        if (select.value === "__none__") delete state.mapping[field.key];
        else state.mapping[field.key] = { column: select.value, method: "manual", confidence: 1 };
        validateMapping();
      });
      selectCell.appendChild(select);
      tr.appendChild(selectCell);

      var methodCell = el("td");
      if (info) {
        var method = info.method === "manual" ? "수동" :
                     (info.method === "exact" ? "정확일치" :
                     (info.method === "alias" ? "별칭" :
                     (info.method === "loose" ? "유사일치" : "추정")));
        var cls = info.confidence >= 0.95 ? "pp-badge-ok" :
                  (info.confidence >= 0.9 ? "pp-badge-muted" : "pp-badge-warn");
        methodCell.appendChild(el("span", "pp-badge " + cls,
          method + " " + Math.round((info.confidence || 0) * 100) + "%"));
      } else {
        methodCell.appendChild(el("span", "pp-badge pp-badge-muted", "미매핑"));
      }
      tr.appendChild(methodCell);
      tr.appendChild(el("td", "pp-help", field.note || ""));
      tbody.appendChild(tr);
    });

    renderMappingStatus();
  }

  function renderMappingStatus() {
    var report = state.mappingReport;
    var node = $("pp-map-status");
    if (!report) { node.textContent = ""; return; }
    var kind = report.missingRequired.length ? "err" :
               (report.missingImportant.length ? "warn" : "ok");
    node.className = "pp-status pp-status-" + kind;
    var lines = [report.mappedCount + " / " + report.columnCount + " 컬럼 매핑됨"];
    if (report.missingRequiredLabels && report.missingRequiredLabels.length) {
      lines.push("필수 미매핑: " + report.missingRequiredLabels.join(", "));
    }
    if (report.missingImportantLabels && report.missingImportantLabels.length) {
      lines.push("주요 미매핑(관련 점수 0점 처리): " + report.missingImportantLabels.join(", "));
    }
    node.textContent = lines.join(" · ");

    var list = $("pp-unmapped-list");
    list.innerHTML = "";
    (report.unmappedColumns || []).forEach(function (column) {
      list.appendChild(el("span", "pp-chip", column));
    });
    $("pp-unmapped-count").textContent = "(" + (report.unmappedColumns || []).length + ")";
    $("pp-map-next").disabled = report.missingRequired.length > 0;
  }

  /* 화면에서 '(미사용)' 으로 바꾼 필드는 __none__ 으로 명시해 서버 자동매핑이
     되살리지 않도록 한다. 즉 매핑 표에 보이는 상태가 그대로 실행된다. */
  function mappingPayload() {
    var payload = {};
    Object.keys(state.mapping).forEach(function (key) { payload[key] = state.mapping[key]; });
    state.fields.forEach(function (field) {
      if (!payload[field.key]) payload[field.key] = "__none__";
    });
    return payload;
  }

  function validateMapping() {
    if (!state.upload) return Promise.resolve();
    return request("/api/upload/" + state.upload.uploadId + "/mapping",
                   { method: "POST", body: { mapping: mappingPayload() } })
      .then(function (data) {
        state.mapping = data.mapping;
        state.mappingReport = data.mappingReport;
        renderMapping();
      })
      .catch(function (error) { toast(error.message, "err"); });
  }

  // ------------------------------------------------------------ 설정
  function buildWeightInputs(config) {
    var areaLabels = { rights: "권리(30)", tech: "기술(30)", market: "시장(20)", impact: "영향력(20)" };
    var areaBox = $("cfg-area-weights");
    areaBox.innerHTML = "";
    Object.keys(config.area_weights).forEach(function (key) {
      areaBox.appendChild(weightField("area-" + key, areaLabels[key] || key,
                                      config.area_weights[key], 0, 3, 0.1));
    });
    var globalBox = $("cfg-global-weights");
    globalBox.innerHTML = "";
    Object.keys(config.global_country_weights).forEach(function (key) {
      globalBox.appendChild(weightField("gw-" + key, key, config.global_country_weights[key], 0, 5, 0.1));
    });
    var marketBox = $("cfg-market-weights");
    marketBox.innerHTML = "";
    Object.keys(config.market_country_weights).forEach(function (key) {
      marketBox.appendChild(weightField("mw-" + key, key, config.market_country_weights[key], 0, 8, 0.1));
    });
  }

  function weightField(id, label, value, min, max, step) {
    var wrap = el("label", "pp-field");
    wrap.appendChild(el("span", null, label));
    var input = el("input", "pp-input");
    input.type = "number"; input.id = "cfg-" + id;
    input.min = min; input.max = max; input.step = step; input.value = value;
    wrap.appendChild(input);
    return wrap;
  }

  function applyConfig(config) {
    $("cfg-topic-name").value = config.topic_name || "";
    $("cfg-topic-desc").value = config.topic_description || "";
    $("cfg-topic-keywords").value = (config.topic_keywords || []).join(", ");
    $("cfg-as-of").value = config.as_of_date || "";
    $("cfg-llm-enabled").checked = config.llm_enabled !== false;
    $("cfg-llm-workers").value = config.llm_max_workers;
    $("cfg-llm-retries").value = config.llm_max_retries;
    $("cfg-llm-chars").value = config.llm_text_char_limit;
    $("cfg-llm-max-docs").value = config.llm_max_documents;
    $("cfg-gate").value = config.gate_topic_fit_min;
    $("cfg-fit-mode").value = config.topic_fit_mode;
    $("cfg-peer-min").value = config.peer_min_size;
    $("cfg-peer-window").value = config.peer_year_window;
    $("cfg-family-source").value = config.family_id_source;
    $("cfg-country-priority").value = (config.representative_country_priority || []).join(", ");
    $("cfg-dedupe").checked = config.dedupe_by_family !== false;
    $("cfg-rescale").checked = !!config.rescale_missing_commercial;
  }

  function collectConfig() {
    var config = {
      topic_name: $("cfg-topic-name").value.trim(),
      topic_description: $("cfg-topic-desc").value.trim(),
      topic_keywords: $("cfg-topic-keywords").value,
      as_of_date: $("cfg-as-of").value,
      llm_enabled: $("cfg-llm-enabled").checked,
      llm_id: $("cfg-llm-id").value,
      llm_max_workers: $("cfg-llm-workers").value,
      llm_max_retries: $("cfg-llm-retries").value,
      llm_text_char_limit: $("cfg-llm-chars").value,
      llm_max_documents: $("cfg-llm-max-docs").value,
      gate_topic_fit_min: $("cfg-gate").value,
      topic_fit_mode: $("cfg-fit-mode").value,
      peer_min_size: $("cfg-peer-min").value,
      peer_year_window: $("cfg-peer-window").value,
      family_id_source: $("cfg-family-source").value,
      representative_country_priority: $("cfg-country-priority").value,
      dedupe_by_family: $("cfg-dedupe").checked,
      rescale_missing_commercial: $("cfg-rescale").checked,
      area_weights: {}, global_country_weights: {}, market_country_weights: {}
    };
    var defaults = state.health.defaultConfig;
    Object.keys(defaults.area_weights).forEach(function (key) {
      config.area_weights[key] = Number($("cfg-area-" + key).value);
    });
    Object.keys(defaults.global_country_weights).forEach(function (key) {
      config.global_country_weights[key] = Number($("cfg-gw-" + key).value);
    });
    Object.keys(defaults.market_country_weights).forEach(function (key) {
      config.market_country_weights[key] = Number($("cfg-mw-" + key).value);
    });
    return config;
  }

  function probeLlm(silent) {
    var llmId = $("cfg-llm-id").value || (state.health && state.health.defaultLlmId);
    if (!llmId) return;
    $("pp-llm-badge").textContent = "LLM 확인 중…";
    $("pp-llm-badge").className = "pp-badge pp-badge-muted";
    request("/api/llm/probe?llmId=" + encodeURIComponent(llmId)).then(function (data) {
      var probe = data.probe;
      $("pp-llm-badge").textContent = probe.ok ? "LLM 연결됨" :
        (probe.provider === "heuristic" ? "LLM 미연결(휴리스틱 대체)" : "LLM 오류");
      $("pp-llm-badge").className = "pp-badge " +
        (probe.ok ? "pp-badge-ok" : (probe.provider === "heuristic" ? "pp-badge-warn" : "pp-badge-err"));
      $("pp-llm-test-result").textContent = probe.message || "";
      if (!silent) toast(probe.message || "확인 완료", probe.ok ? "ok" : "err");
    }).catch(function (error) {
      $("pp-llm-badge").textContent = "LLM 확인 실패";
      $("pp-llm-badge").className = "pp-badge pp-badge-err";
      if (!silent) toast(error.message, "err");
    });
  }

  function bindConfig() {
    $("pp-llm-test").addEventListener("click", function () { probeLlm(false); });
    $("cfg-llm-id").addEventListener("change", function () { probeLlm(true); });
    $("pp-run").addEventListener("click", runAnalysis);
    $("pp-cancel").addEventListener("click", function () {
      if (!state.jobId) return;
      request("/api/jobs/" + state.jobId + "/cancel", { method: "POST" })
        .then(function () { toast("취소를 요청했습니다.", "ok"); })
        .catch(function (error) { toast(error.message, "err"); });
    });
  }

  // ------------------------------------------------------------ 실행
  function runAnalysis() {
    if (!state.upload) { toast("먼저 파일을 업로드하십시오.", "err"); return; }
    if (state.mappingReport && state.mappingReport.missingRequired.length) {
      toast("필수 항목 매핑을 완료하십시오.", "err"); setTab("mapping"); return;
    }
    var config = collectConfig();
    if (!config.topic_name) { toast("분석 주제명을 입력하십시오.", "err"); return; }

    $("pp-run").disabled = true;
    $("pp-cancel").hidden = false;
    $("pp-run-progress").hidden = false;
    setProgress(0, "분석 요청 중");

    request("/api/analyze", { method: "POST", body: {
      uploadId: state.upload.uploadId, mapping: mappingPayload(), config: config } })
      .then(function (data) {
        state.jobId = data.job.id;
        pollJob();
      })
      .catch(function (error) {
        finishRun();
        toast(error.message, "err");
      });
  }

  function setProgress(ratio, message) {
    $("pp-run-progress").querySelector(".pp-progress-bar").style.width =
      Math.round((ratio || 0) * 100) + "%";
    $("pp-run-message").textContent = message || "";
  }

  function pollJob() {
    if (state.pollTimer) clearTimeout(state.pollTimer);
    request("/api/jobs/" + state.jobId).then(function (data) {
      var job = data.job;
      setProgress(job.progress, job.message + " (" + job.elapsedSec + "초)");
      if (job.status === "done") {
        finishRun();
        state.source = { type: "job", id: state.jobId };
        state.runId = null;
        loadResult(true);
        toast("분석이 완료되었습니다.", "ok");
      } else if (job.status === "error") {
        finishRun();
        toast("분석 실패: " + job.error, "err");
      } else if (job.status === "cancelled") {
        finishRun();
        toast("분석이 취소되었습니다.");
      } else {
        state.pollTimer = setTimeout(pollJob, 900);
      }
    }).catch(function (error) {
      finishRun();
      toast(error.message, "err");
    });
  }

  function finishRun() {
    $("pp-run").disabled = false;
    $("pp-cancel").hidden = true;
  }

  // ------------------------------------------------------------ 결과
  function bindResult() {
    ["pp-q", "pp-filter-grade", "pp-filter-gate", "pp-filter-route"].forEach(function (id) {
      $(id).addEventListener("change", function () { state.page = 0; loadResult(false); });
    });
    $("pp-q").addEventListener("input", debounce(function () {
      state.page = 0; loadResult(false);
    }, 350));
    $("pp-page-size").addEventListener("change", function () {
      state.pageSize = Number($("pp-page-size").value); state.page = 0; loadResult(false);
    });
    $("pp-prev").addEventListener("click", function () {
      if (state.page > 0) { state.page -= 1; loadResult(false); }
    });
    $("pp-next").addEventListener("click", function () {
      if ((state.page + 1) * state.pageSize < state.total) { state.page += 1; loadResult(false); }
    });
    document.querySelectorAll("#pp-result-table thead th[data-sort]").forEach(function (th) {
      th.addEventListener("click", function () {
        var key = th.dataset.sort;
        if (state.sort === key) state.order = state.order === "asc" ? "desc" : "asc";
        else { state.sort = key; state.order = "asc"; }
        state.page = 0;
        loadResult(false);
      });
    });
    $("pp-download-xlsx").addEventListener("click", function () { download("xlsx"); });
    $("pp-download-csv").addEventListener("click", function () { download("csv"); });
    $("pp-open-save").addEventListener("click", openSaveModal);
    $("pp-save-cancel").addEventListener("click", function () { $("pp-save-modal").hidden = true; });
    $("pp-save-confirm").addEventListener("click", saveResult);
    $("pp-detail-close").addEventListener("click", function () { $("pp-detail").hidden = true; });
  }

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(fn, wait);
    };
  }

  function resultBase() {
    if (!state.source) return null;
    return state.source.type === "job"
      ? "/api/jobs/" + state.source.id
      : "/api/runs/" + state.source.id;
  }

  function loadResult(resetView) {
    var base = resultBase();
    if (!base) return;
    if (resetView) { state.page = 0; state.sort = "rank"; state.order = "asc"; }
    var params = [
      "offset=" + state.page * state.pageSize,
      "limit=" + state.pageSize,
      "sort=" + encodeURIComponent(state.sort),
      "order=" + state.order,
      "q=" + encodeURIComponent($("pp-q").value || ""),
      "grade=" + encodeURIComponent($("pp-filter-grade").value || ""),
      "gate=" + encodeURIComponent($("pp-filter-gate").value || ""),
      "route=" + encodeURIComponent($("pp-filter-route").value || "")
    ].join("&");

    request(base + "/result?" + params).then(function (data) {
      state.result = data;
      state.total = data.total;
      enableTab("result", true);
      setTab("result");
      renderSummary(data);
      renderRows(data.rows);
      renderPager();
      if (resetView) renderRouteOptions(data);
    }).catch(function (error) { toast(error.message, "err"); });
  }

  function renderRouteOptions(data) {
    var select = $("pp-filter-route");
    var routes = Object.keys((data.summary && data.summary.routeDistribution) || {});
    select.innerHTML = '<option value="">검토 루트 전체</option>';
    routes.forEach(function (route) {
      var option = el("option", null, route);
      option.value = route;
      select.appendChild(option);
    });
  }

  function renderSummary(data) {
    var summary = data.summary || {};
    var meta = data.meta;
    $("pp-result-title").textContent = meta
      ? "저장된 결과 · " + esc(meta.project) + " (" + esc(meta.savedAtDisplay) + ")"
      : "분석 결과 · " + esc((data.config || {}).topic_name || "");

    var grid = $("pp-summary");
    grid.innerHTML = "";
    [["입력 문헌", summary.inputRecordCount], ["패밀리", summary.familyCount],
     ["채점 문헌", summary.scoredCount], ["Gate 통과", summary.gatePassedCount],
     ["LLM 분석", summary.llmAnalyzedCount], ["평균 총점", num(summary.scoreAverage, 1)],
     ["최고 총점", num(summary.scoreMax, 1)], ["기준일", summary.asOf]
    ].forEach(function (pair) {
      var box = el("div", "pp-metric");
      box.appendChild(el("div", "pp-metric-label", pair[0]));
      box.appendChild(el("div", "pp-metric-value", esc(pair[1] === undefined ? "-" : pair[1])));
      grid.appendChild(box);
    });

    renderBars("pp-dist-grade", summary.gradeDistribution);
    renderBars("pp-dist-route", summary.routeDistribution);
    renderBars("pp-dist-status", summary.statusDistribution);

    var warnings = data.warnings || [];
    var box = $("pp-result-warnings");
    box.innerHTML = "";
    if (warnings.length) {
      box.appendChild(el("strong", null, "확인이 필요한 사항"));
      var list = el("ul");
      warnings.forEach(function (warning) { list.appendChild(el("li", null, warning)); });
      box.appendChild(list);
      box.hidden = false;
    } else {
      box.hidden = true;
    }
  }

  function renderBars(containerId, distribution) {
    var container = $(containerId);
    container.innerHTML = "";
    var entries = Object.keys(distribution || {}).map(function (key) {
      return [key, distribution[key]];
    });
    if (!entries.length) { container.appendChild(el("div", "pp-help", "데이터 없음")); return; }
    var max = entries.reduce(function (acc, entry) { return Math.max(acc, entry[1]); }, 0) || 1;
    entries.sort(function (a, b) { return b[1] - a[1]; });
    entries.forEach(function (entry) {
      var row = el("div", "pp-bar-row");
      row.appendChild(el("span", null, entry[0]));
      var track = el("div", "pp-bar-track");
      var fill = el("div", "pp-bar-fill");
      fill.style.width = (entry[1] / max * 100) + "%";
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el("span", null, entry[1]));
      container.appendChild(row);
    });
  }

  function renderRows(rows) {
    var tbody = document.querySelector("#pp-result-table tbody");
    tbody.innerHTML = "";
    if (!rows || !rows.length) {
      var tr = el("tr");
      var td = el("td", "pp-empty", "조건에 맞는 문헌이 없습니다.");
      td.colSpan = 15;
      tr.appendChild(td); tbody.appendChild(tr);
      return;
    }
    rows.forEach(function (row) {
      var tr = el("tr");
      tr.appendChild(el("td", "pp-num", row.rank));
      tr.appendChild(el("td", null, row.docNumber));
      tr.appendChild(el("td", null, row.country));
      var title = el("td", "pp-title-cell", row.title);
      title.title = esc(row.title);
      tr.appendChild(title);
      tr.appendChild(el("td", null, row.applicant));
      tr.appendChild(el("td", null, row.statusLabel));
      tr.appendChild(el("td", "pp-num", num(row.totalScore, 1)));
      var grade = el("td");
      grade.appendChild(el("span", "pp-grade pp-grade-" + esc(row.grade), row.grade));
      tr.appendChild(grade);
      var areas = row.areaScores || {};
      ["rights", "tech", "market", "impact"].forEach(function (key) {
        tr.appendChild(el("td", "pp-num", num(areas[key], 1)));
      });
      tr.appendChild(el("td", "pp-num", esc(row.forwardCitations)));
      var gate = el("td");
      gate.appendChild(el("span", "pp-badge " + (row.gate && row.gate.passed ? "pp-badge-ok" : "pp-badge-muted"),
        (row.gate ? num(row.gate.topicFitPercent, 0) : "-") + "%"));
      tr.appendChild(gate);
      tr.appendChild(el("td", null, row.reviewRoute));
      tr.addEventListener("click", function () { openDetail(row.key); });
      tbody.appendChild(tr);
    });
  }

  function renderPager() {
    var start = state.total ? state.page * state.pageSize + 1 : 0;
    var end = Math.min(state.total, (state.page + 1) * state.pageSize);
    $("pp-page-info").textContent = start + " - " + end + " / 총 " + state.total + " 건";
    $("pp-prev").disabled = state.page === 0;
    $("pp-next").disabled = end >= state.total;
  }

  function openDetail(key) {
    var base = resultBase();
    if (!base) return;
    request(base + "/row/" + encodeURIComponent(key)).then(function (data) {
      var row = data.row;
      $("pp-detail-title").textContent = esc(row.docNumber) + " · " + num(row.totalScore, 1) + "점 (" + esc(row.grade) + ")";
      var body = $("pp-detail-body");
      body.innerHTML = "";

      body.appendChild(el("h3", null, "서지"));
      var info = el("div", "pp-help");
      info.textContent = [row.title, row.applicant, row.statusLabel,
                          "최초우선일 " + esc(row.priorityDate),
                          "패밀리 국가 " + (row.familyCountries || []).join(", ")]
        .filter(Boolean).join(" · ");
      body.appendChild(info);
      if (row.detailLink) {
        var link = el("a", "pp-help", "윈텔립스 상세보기 열기");
        link.href = row.detailLink; link.target = "_blank"; link.rel = "noopener";
        body.appendChild(link);
      }

      body.appendChild(el("h3", null, "점수 구성"));
      var totals = el("div", "pp-help",
        "총점 " + num(row.totalScore, 2) + " / " + num(row.totalMax, 0) +
        "  (정량 " + num(row.quantScore, 2) + "/" + num(row.quantMax, 0) +
        ", LLM " + num(row.llmScore, 2) + "/" + num(row.llmMax, 0) + ")");
      body.appendChild(totals);

      Object.keys(row.areas || {}).forEach(function (areaKey) {
        var area = row.areas[areaKey];
        body.appendChild(el("h3", null, area.label + "  " + num(area.weightedScore, 2) + " / " + num(area.weightedMax, 0)));
        area.components.forEach(function (component) {
          var box = el("div", "pp-comp");
          var head = el("div", "pp-comp-head");
          head.appendChild(el("span", null, component.label));
          head.appendChild(el("span", "pp-comp-score",
            num(component.score, 2) + " / " + num(component.max, 0)));
          box.appendChild(head);
          var track = el("div", "pp-bar-track");
          var fill = el("div", "pp-bar-fill");
          fill.style.width = (component.max ? (component.score / component.max * 100) : 0) + "%";
          track.appendChild(fill);
          box.appendChild(track);
          if (component.detail && Object.keys(component.detail).length) {
            box.appendChild(el("div", "pp-comp-detail", summarizeDetail(component.detail)));
          }
          (component.notes || []).forEach(function (note) {
            box.appendChild(el("div", "pp-comp-note", "※ " + note));
          });
          body.appendChild(box);
        });
      });

      if (row.llm) {
        body.appendChild(el("h3", null, "LLM 분석"));
        body.appendChild(el("div", "pp-help",
          "상태: " + esc(row.llm.status) + " · 제공자: " + esc(row.llm.provider || "-")));
        if (row.llm.rationale) body.appendChild(el("div", "pp-help", row.llm.rationale));
        if (row.llm.keyFeatures && row.llm.keyFeatures.length) {
          var chips = el("div", "pp-chip-list");
          row.llm.keyFeatures.forEach(function (feature) {
            chips.appendChild(el("span", "pp-chip", feature));
          });
          body.appendChild(chips);
        }
      }
      $("pp-detail").hidden = false;
    }).catch(function (error) { toast(error.message, "err"); });
  }

  function summarizeDetail(detail) {
    return Object.keys(detail).slice(0, 10).map(function (key) {
      var value = detail[key];
      if (value === null || value === undefined || value === "") return null;
      if (Array.isArray(value)) value = value.slice(0, 8).join(",");
      else if (typeof value === "object") value = JSON.stringify(value).slice(0, 120);
      return key + "=" + value;
    }).filter(Boolean).join(" · ");
  }

  function download(format) {
    var base = resultBase();
    if (!base) { toast("다운로드할 결과가 없습니다.", "err"); return; }
    window.open(apiUrl(base + "/download?format=" + format), "_blank");
  }

  // ------------------------------------------------------------ 저장
  function openSaveModal() {
    if (!state.source) { toast("저장할 결과가 없습니다.", "err"); return; }
    if (!$("save-project").value && state.result && state.result.config) {
      $("save-project").value = state.result.config.topic_name || "";
    }
    $("pp-save-modal").hidden = false;
  }

  function saveResult() {
    var body = {
      department: $("save-department").value.trim(),
      owner: $("save-owner").value.trim(),
      project: $("save-project").value.trim(),
      title: $("save-title").value.trim(),
      note: $("save-note").value.trim()
    };
    if (!body.department || !body.owner || !body.project) {
      toast("부서, 이름, 프로젝트명을 모두 입력하십시오.", "err");
      return;
    }
    if (state.source.type === "job") body.jobId = state.source.id;
    else body.runId = state.source.id;

    $("pp-save-confirm").disabled = true;
    request("/api/save", { method: "POST", body: body }).then(function (data) {
      $("pp-save-confirm").disabled = false;
      $("pp-save-modal").hidden = true;
      toast("저장되었습니다: " + data.meta.savedAtDisplay, "ok");
      loadRuns();
    }).catch(function (error) {
      $("pp-save-confirm").disabled = false;
      toast(error.message, "err");
    });
  }

  // ------------------------------------------------------------ 저장소
  function bindLibrary() {
    $("pp-refresh-runs").addEventListener("click", loadRuns);
    ["pp-runs-department", "pp-runs-owner", "pp-runs-project"].forEach(function (id) {
      $(id).addEventListener("change", loadRuns);
    });
    $("pp-runs-q").addEventListener("input", debounce(loadRuns, 350));
  }

  function loadRuns() {
    var params = [
      "department=" + encodeURIComponent($("pp-runs-department").value || ""),
      "owner=" + encodeURIComponent($("pp-runs-owner").value || ""),
      "project=" + encodeURIComponent($("pp-runs-project").value || ""),
      "q=" + encodeURIComponent($("pp-runs-q").value || "")
    ].join("&");
    request("/api/runs?" + params).then(function (data) {
      renderRuns(data.runs);
      fillFacets(data.facets);
    }).catch(function (error) { toast(error.message, "err"); });
  }

  function fillFacets(facets) {
    [["pp-runs-department", facets.departments, "부서 전체"],
     ["pp-runs-owner", facets.owners, "이름 전체"],
     ["pp-runs-project", facets.projects, "프로젝트 전체"]].forEach(function (entry) {
      var select = $(entry[0]);
      var current = select.value;
      select.innerHTML = "";
      var all = el("option", null, entry[2]); all.value = "";
      select.appendChild(all);
      (entry[1] || []).forEach(function (value) {
        var option = el("option", null, value);
        option.value = value;
        select.appendChild(option);
      });
      select.value = current;
    });
    ["pp-departments:departments", "pp-owners:owners", "pp-projects:projects"].forEach(function (pair) {
      var parts = pair.split(":");
      var list = $(parts[0]);
      list.innerHTML = "";
      (facets[parts[1]] || []).forEach(function (value) {
        var option = el("option");
        option.value = value;
        list.appendChild(option);
      });
    });
  }

  function renderRuns(runs) {
    var tbody = document.querySelector("#pp-runs-table tbody");
    tbody.innerHTML = "";
    if (!runs || !runs.length) {
      var tr = el("tr");
      var td = el("td", "pp-empty", "저장된 결과가 없습니다.");
      td.colSpan = 10;
      tr.appendChild(td); tbody.appendChild(tr);
      return;
    }
    runs.forEach(function (run) {
      var tr = el("tr");
      tr.appendChild(el("td", null, run.savedAtDisplay || run.savedAt));
      tr.appendChild(el("td", null, run.department));
      tr.appendChild(el("td", null, run.owner));
      tr.appendChild(el("td", null, run.project));
      tr.appendChild(el("td", null, run.topicName));
      tr.appendChild(el("td", "pp-num", run.recordCount));
      tr.appendChild(el("td", "pp-num", run.scoredCount));
      tr.appendChild(el("td", "pp-num", num(run.scoreAverage, 1)));
      tr.appendChild(el("td", null, run.llmProvider || "-"));

      var actions = el("td");
      var open = el("button", "pp-btn pp-btn-mini pp-btn-primary", "불러오기");
      open.addEventListener("click", function () {
        state.source = { type: "run", id: run.runId };
        state.runId = run.runId;
        loadResult(true);
      });
      var xlsx = el("button", "pp-btn pp-btn-mini", "엑셀");
      xlsx.addEventListener("click", function () {
        window.open(apiUrl("/api/runs/" + run.runId + "/download?format=xlsx"), "_blank");
      });
      var remove = el("button", "pp-btn pp-btn-mini", "삭제");
      remove.addEventListener("click", function () {
        if (!window.confirm("이 결과를 삭제하시겠습니까?\n" + run.project + " / " + run.savedAtDisplay)) return;
        request("/api/runs/" + run.runId, { method: "DELETE" }).then(function () {
          toast("삭제되었습니다.", "ok");
          if (state.source && state.source.id === run.runId) state.source = null;
          loadRuns();
        }).catch(function (error) { toast(error.message, "err"); });
      });
      actions.appendChild(open); actions.appendChild(xlsx); actions.appendChild(remove);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
