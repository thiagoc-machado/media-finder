(function () {
  "use strict";

  function query(selector) {
    return document.querySelector(selector);
  }

  var toggle = query("[data-nav-toggle]");
  var navigation = query("[data-main-nav]");

  if (toggle && navigation) {
    toggle.addEventListener("click", function () {
      var expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      navigation.classList.toggle("is-open", !expanded);
    });
  }

  var path = window.location.pathname;
  document.querySelectorAll("[data-nav-link]").forEach(function (link) {
    var target = link.getAttribute("href");
    var active = target === "/" ? path === "/" : path.startsWith(target);
    link.classList.toggle("is-active", active);
  });

  function updateSeasonFields() {
    var mediaType = query("[data-media-type]");
    var fields = query("[data-season-fields]");
    if (!mediaType || !fields) return;
    var visible = mediaType.value === "series" || mediaType.value === "anime";
    fields.classList.toggle("is-hidden", !visible);
    fields.querySelectorAll("input").forEach(function (input) {
      input.disabled = !visible;
      if (!visible) input.value = "";
    });
  }

  var mediaType = query("[data-media-type]");
  if (mediaType) {
    mediaType.addEventListener("change", updateSeasonFields);
    updateSeasonFields();
  }

  var selectAll = query("[data-select-all-providers]");
  if (selectAll) {
    selectAll.addEventListener("click", function () {
      document.querySelectorAll("input[name='providers']").forEach(function (input) { input.checked = true; });
    });
  }

  var clearProviders = query("[data-clear-providers]");
  if (clearProviders) {
    clearProviders.addEventListener("click", function () {
      document.querySelectorAll("input[name='providers']").forEach(function (input) { input.checked = false; });
    });
  }

  var clearFilters = query("[data-clear-filters]");
  if (clearFilters) {
    clearFilters.addEventListener("click", function () {
      document.querySelectorAll("[data-clearable-filter]").forEach(function (input) {
        if (input.type === "checkbox") input.checked = false;
        else input.value = "";
      });
    });
  }

  function setSearching(searching) {
    var submit = query("[data-search-submit]");
    var loading = query("#search-loading");
    if (submit) submit.disabled = searching;
    if (loading) loading.classList.toggle("is-visible", searching);
  }

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    if (event.detail && event.detail.target && event.detail.target.id === "search-results") setSearching(true);
  });
  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (event.detail && event.detail.target && event.detail.target.id === "search-results") setSearching(false);
  });
  document.body.addEventListener("htmx:sendError", function () {
    setSearching(false);
    var error = query("#search-form-errors");
    if (error) { error.textContent = "Não foi possível conectar ao servidor. Tente novamente."; error.classList.remove("is-hidden"); }
  });
  document.body.addEventListener("htmx:responseError", function (event) {
    setSearching(false);
    var error = query("#search-form-errors");
    if (error) { error.textContent = "A busca não pôde ser concluída. Verifique os filtros."; error.classList.remove("is-hidden"); }
  });

  function setDownloadReason(control, message, enabled) {
    var button = control.querySelector("[data-download-button]");
    var reason = control.querySelector("[data-download-reason]");
    if (button) {
      button.disabled = !enabled;
      button.classList.toggle("button-disabled", !enabled);
      button.title = message || "Adicionar ao qBittorrent";
    }
    if (reason) {
      reason.textContent = message || "Ready to send";
      reason.classList.toggle("is-hidden", enabled);
    }
  }

  function refreshDownloadCapabilities() {
    var controls = Array.prototype.slice.call(document.querySelectorAll("[data-download-control]"));
    if (!controls.length) return;
    Promise.all([
      fetch("/qbittorrent/health", { headers: { "Accept": "application/json" } }).then(function (response) { return response.json(); }),
      fetch("/qbittorrent/categories", { headers: { "Accept": "application/json" } }).then(function (response) { return response.ok ? response.json() : null; })
    ]).then(function (responses) {
      var health = responses[0];
      var categories = responses[1];
      controls.forEach(function (control) {
        var mediaType = control.getAttribute("data-media-type");
        var category = control.getAttribute("data-category");
        if (control.getAttribute("data-has-valid-magnet") !== "true") {
          setDownloadReason(control, "Invalid magnet", false);
        } else if (!category || mediaType === "anime" || mediaType === "other") {
          setDownloadReason(control, "Category not configured", false);
        } else if (!health || health.available !== true) {
          setDownloadReason(control, "qBittorrent unavailable", false);
        } else if (!categories || categories.valid_categories.indexOf(category) === -1) {
          setDownloadReason(control, "Category not found in qBittorrent", false);
        } else {
          setDownloadReason(control, "", true);
        }
      });
    }).catch(function () {
      controls.forEach(function (control) { setDownloadReason(control, "qBittorrent unavailable", false); });
    });
  }

  refreshDownloadCapabilities();
  document.body.addEventListener("htmx:afterSwap", function () { refreshDownloadCapabilities(); });
  document.body.addEventListener("htmx:afterRequest", function (event) {
    if (!event.detail || !event.detail.elt || !event.detail.elt.matches(".download-form")) return;
    var response = event.detail.xhr && event.detail.xhr.responseText ? event.detail.xhr.responseText : "";
    if (response.indexOf("download-feedback-queued") !== -1 || response.indexOf("download-feedback-duplicate") !== -1) {
      var button = event.detail.elt.querySelector("[data-download-button]");
      if (button) button.disabled = true;
    }
  });
})();
