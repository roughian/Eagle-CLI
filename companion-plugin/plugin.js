(() => {
  const req = window.require || require;
  const fs = req("fs");
  const os = req("os");
  const path = req("path");

  const stateRoot = path.join(os.homedir(), ".config", "cli-anything-eagle", "bridge");
  const requestsDir = path.join(stateRoot, "requests");
  const responsesDir = path.join(stateRoot, "responses");
  const processedDir = path.join(stateRoot, "processed");
  const statusPath = path.join(stateRoot, "status.json");
  const logPath = path.join(stateRoot, "plugin.log");
  const pluginId = "2f40db08-5ce8-4d72-9fb7-a8fdcb5c1f6b";
  const pluginName = "CLI-Anything Eagle Bridge";
  const pluginVersion = "0.16.0";
  const STATUS_HEARTBEAT_MS = 15000;
  const REQUEST_POLL_MS = 1000;
  const LIBRARY_SUMMARY_TTL_MS = 60000;

  const statusNode = document.getElementById("status");
  const statePathNode = document.getElementById("state-path");
  const logNode = document.getElementById("log");
  const logLines = [];

  let isProcessing = false;
  let processedRequests = 0;
  let cachedLibrary = null;
  let cachedLibraryExpiresAt = 0;
  let librarySummaryPromise = null;

  function log(message) {
    const line = `${new Date().toISOString()} ${message}`;
    logLines.unshift(line);
    while (logLines.length > 20) {
      logLines.pop();
    }
    if (logNode) {
      logNode.textContent = logLines.join("\n");
    }
    try {
      fs.appendFileSync(logPath, `${line}\n`, "utf8");
    } catch (_error) {
      // Avoid recursive logging failures before the state directory exists.
    }
    console.log(`[CLI-Anything Bridge] ${message}`);
  }

  function ensureDirs() {
    for (const dir of [stateRoot, requestsDir, responsesDir, processedDir]) {
      fs.mkdirSync(dir, { recursive: true });
    }
    if (statePathNode) {
      statePathNode.textContent = stateRoot;
    }
  }

  function writeJson(targetPath, payload) {
    const tempPath = `${targetPath}.${process.pid}.${Date.now()}.tmp`;
    fs.writeFileSync(tempPath, JSON.stringify(payload, null, 2), "utf8");
    fs.renameSync(tempPath, targetPath);
  }

  async function getLibrarySummary(options = {}) {
    const forceRefresh = Boolean(options.forceRefresh);
    const now = Date.now();
    if (!forceRefresh && cachedLibrary && now < cachedLibraryExpiresAt) {
      return cachedLibrary;
    }
    if (librarySummaryPromise) {
      return librarySummaryPromise;
    }

    librarySummaryPromise = (async () => {
      try {
        if (eagle && eagle.library && typeof eagle.library.info === "function") {
          cachedLibrary = summarizeLibraryInfo(await eagle.library.info());
          cachedLibraryExpiresAt = Date.now() + LIBRARY_SUMMARY_TTL_MS;
        }
      } catch (error) {
        log(`library.info failed: ${error.message}`);
      } finally {
        librarySummaryPromise = null;
      }

      return cachedLibrary;
    })();

    return librarySummaryPromise;
  }

  async function collectStatus(options = {}) {
    const includeLibrary = Boolean(options.includeLibrary);
    const forceLibraryRefresh = Boolean(options.forceLibraryRefresh);
    let library = cachedLibrary;
    if (includeLibrary) {
      library = await getLibrarySummary({ forceRefresh: forceLibraryRefresh });
    }
    return {
      kind: "eagle-cli-bridge-status",
      pluginId,
      pluginName,
      pluginVersion,
      updatedAt: new Date().toISOString(),
      processedRequests,
      requestCount: safeCount(requestsDir),
      responseCount: safeCount(responsesDir),
      library,
    };
  }

  async function writeStatus() {
    try {
      const payload = await collectStatus();
      writeJson(statusPath, payload);
      if (statusNode) {
        statusNode.textContent = "ready";
      }
    } catch (error) {
      if (statusNode) {
        statusNode.textContent = "error";
      }
      log(`status write failed: ${error.message}`);
    }
  }

  function safeCount(dir) {
    try {
      return fs.readdirSync(dir).filter((name) => name.endsWith(".json")).length;
    } catch (_error) {
      return 0;
    }
  }

  function countTree(nodes) {
    let count = 0;
    const stack = Array.isArray(nodes) ? [...nodes] : [];
    while (stack.length > 0) {
      const node = stack.pop();
      if (!node || typeof node !== "object") {
        continue;
      }
      count += 1;
      const children = Array.isArray(node.children) ? node.children : [];
      for (const child of children) {
        stack.push(child);
      }
    }
    return count;
  }

  function summarizeLibraryInfo(library) {
    if (!library || typeof library !== "object") {
      return null;
    }
    return {
      applicationVersion: library.applicationVersion || null,
      name: library.name || null,
      path: library.path || null,
      modificationTime: library.modificationTime || null,
      quickAccessCount: Array.isArray(library.quickAccess) ? library.quickAccess.length : 0,
      folderCount: countTree(library.folders),
      smartFolderCount: countTree(library.smartFolders),
      tagGroupCount: countTree(library.tagsGroups),
    };
  }

  async function getItemsByIds(ids) {
    if (!Array.isArray(ids) || ids.length === 0) {
      return [];
    }
    if (!eagle || !eagle.item || typeof eagle.item.get !== "function") {
      throw new Error("eagle.item.get is not available in this plugin runtime.");
    }
    return await eagle.item.get({ ids });
  }

  function summarizeItem(item) {
    return {
      id: String(item.id || ""),
      name: String(item.name || ""),
      ext: String(item.ext || ""),
      url: String(item.url || ""),
      annotation: String(item.annotation || ""),
      isDeleted: Boolean(item.isDeleted),
      tags: Array.isArray(item.tags) ? item.tags.map(String) : [],
      folders: Array.isArray(item.folders) ? item.folders.map(String) : [],
    };
  }

  function summarizeFolder(folder) {
    return {
      id: String(folder.id || ""),
      name: String(folder.name || ""),
      description: String(folder.description || ""),
      parent: String(folder.parent || ""),
      childrenCount: Array.isArray(folder.children) ? folder.children.length : 0,
    };
  }

  function summarizeTag(tag) {
    return {
      name: String((tag && tag.name) || ""),
      count: Number.isFinite(tag && tag.count) ? tag.count : Number(tag && tag.count) || 0,
      color: String((tag && tag.color) || ""),
      groups: Array.isArray(tag && tag.groups) ? tag.groups.map(String) : [],
      pinyin: String((tag && tag.pinyin) || ""),
    };
  }

  async function getSelectedItems(limit) {
    if (!eagle || !eagle.item || typeof eagle.item.getSelected !== "function") {
      throw new Error("eagle.item.getSelected is not available in this plugin runtime.");
    }
    const items = await eagle.item.getSelected();
    const bounded = Number.isFinite(limit) ? Math.max(1, limit) : 20;
    return items.slice(0, bounded);
  }

  async function getSelectedFolders() {
    if (!eagle || !eagle.folder || typeof eagle.folder.getSelected !== "function") {
      throw new Error("eagle.folder.getSelected is not available in this plugin runtime.");
    }
    return await eagle.folder.getSelected();
  }

  async function getTagByName(tagName) {
    if (!eagle || !eagle.tag || typeof eagle.tag.get !== "function") {
      throw new Error("eagle.tag.get is not available in this plugin runtime.");
    }
    const matches = await eagle.tag.get({ name: tagName });
    return (matches || []).find((tag) => String(tag.name || "") === String(tagName)) || null;
  }

  async function handlePing(payload) {
    return {
      ok: true,
      echoed: payload || {},
      status: await collectStatus(),
    };
  }

  async function handleGetContext(payload) {
    const requestedLimit = Number(payload && payload.item_limit);
    const itemLimit = Number.isFinite(requestedLimit) ? Math.max(1, requestedLimit) : 20;
    const selectedItems = await getSelectedItems(itemLimit);
    const selectedFolders = await getSelectedFolders();
    const selectedItemCount =
      eagle && eagle.item && typeof eagle.item.countSelected === "function"
        ? await eagle.item.countSelected()
        : selectedItems.length;
    return {
      item_limit: itemLimit,
      selected_item_count: selectedItemCount,
      selected_folder_count: selectedFolders.length,
      truncated_items: selectedItemCount > selectedItems.length,
      selected_items: selectedItems.map(summarizeItem),
      selected_folders: selectedFolders.map(summarizeFolder),
      status: await collectStatus({ includeLibrary: true }),
    };
  }

  async function handleGetSelectedItemIds() {
    if (!eagle || !eagle.item || typeof eagle.item.getSelected !== "function") {
      throw new Error("eagle.item.getSelected is not available in this plugin runtime.");
    }
    const items = await eagle.item.getSelected();
    const itemIds = items.map((item) => String(item && item.id ? item.id : "")).filter(Boolean);
    return {
      selected: itemIds.length > 0,
      item_ids: itemIds,
      selected_count: itemIds.length,
      selected_item_count: itemIds.length,
      status: await collectStatus(),
    };
  }

  async function handleShowApp() {
    if (!eagle || !eagle.app || typeof eagle.app.show !== "function") {
      throw new Error("eagle.app.show is not available in this plugin runtime. Upgrade to Eagle 4.0 build18 or later.");
    }
    const shown = await eagle.app.show();
    return {
      shown: Boolean(shown),
      app_version: eagle.app && eagle.app.version ? String(eagle.app.version) : null,
      app_build: eagle.app && eagle.app.build !== undefined ? Number(eagle.app.build) : null,
      locale: eagle.app && eagle.app.locale ? String(eagle.app.locale) : null,
      status: await collectStatus({ includeLibrary: true }),
    };
  }

  async function handleGetRecentTags() {
    if (!eagle || !eagle.tag || typeof eagle.tag.getRecentTags !== "function") {
      throw new Error("eagle.tag.getRecentTags is not available in this plugin runtime.");
    }
    const tags = await eagle.tag.getRecentTags();
    return {
      count: Array.isArray(tags) ? tags.length : 0,
      rows: (tags || []).map(summarizeTag),
    };
  }

  async function handleGetStarredTags() {
    if (!eagle || !eagle.tag || typeof eagle.tag.getStarredTags !== "function") {
      throw new Error("eagle.tag.getStarredTags is not available in this plugin runtime. Upgrade to Eagle 4.0 build18 or later.");
    }
    const tags = await eagle.tag.getStarredTags();
    return {
      count: Array.isArray(tags) ? tags.length : 0,
      rows: (tags || []).map(summarizeTag),
    };
  }

  async function handleSelectItems(payload) {
    const itemIds = Array.isArray(payload && payload.item_ids)
      ? payload.item_ids.filter(Boolean).map(String)
      : [];
    if (itemIds.length === 0) {
      return { selected: false, selected_count: 0, item_ids: [] };
    }
    if (eagle && eagle.item && typeof eagle.item.select === "function") {
      const selected = await eagle.item.select(itemIds);
      return {
        selected: Boolean(selected),
        selected_count: itemIds.length,
        item_ids: itemIds,
        selection_method: "select",
      };
    }
    if (itemIds.length === 1 && eagle && eagle.item && typeof eagle.item.open === "function") {
      await eagle.item.open(itemIds[0]);
      const actualItemIds =
        eagle && eagle.item && typeof eagle.item.getSelected === "function"
          ? (await eagle.item.getSelected())
              .map((item) => String(item && item.id ? item.id : ""))
              .filter(Boolean)
          : [];
      const verified = actualItemIds.includes(itemIds[0]);
      return {
        selected: verified,
        selected_count: verified ? 1 : 0,
        item_ids: actualItemIds,
        requested_item_ids: itemIds,
        actual_selected_count: actualItemIds.length,
        actual_selected_item_ids: actualItemIds,
        selection_method: "open-fallback",
        compatibility_warning:
          "eagle.item.select is unavailable in this plugin runtime; single-item selection fell back to eagle.item.open(). Upgrade to Eagle 4.0 build12+ for programmatic multi-item selection.",
      };
    }
    throw new Error(
      "eagle.item.select is not available in this plugin runtime. Upgrade to Eagle 4.0 build12 or later for programmatic multi-item selection.",
    );
  }

  async function handleOpenFolder(payload) {
    const folderId = String((payload && payload.folder_id) || "").trim();
    if (!folderId) {
      throw new Error("open_folder requires a folder_id.");
    }
    if (!eagle || !eagle.folder || typeof eagle.folder.open !== "function") {
      throw new Error("eagle.folder.open is not available in this plugin runtime.");
    }
    await eagle.folder.open(folderId);
    return { opened: true, folder_id: folderId };
  }

  async function handleOpenItems(payload) {
    const itemIds = Array.isArray(payload && payload.item_ids)
      ? payload.item_ids.filter(Boolean).map(String)
      : [];
    const windowMode = Boolean(payload && payload.window);
    if (itemIds.length === 0) {
      return { opened: false, opened_count: 0, item_ids: [] };
    }
    if (!eagle || !eagle.item || typeof eagle.item.open !== "function") {
      throw new Error("eagle.item.open is not available in this plugin runtime.");
    }
    const results = [];
    for (const itemId of itemIds) {
      await eagle.item.open(itemId, { window: windowMode });
      results.push({ item_id: itemId, status: "opened", window: windowMode });
    }
    return {
      opened: true,
      opened_count: results.length,
      results,
    };
  }

  async function handleRenameTag(payload) {
    const source = String((payload && payload.source) || "").trim();
    const target = String((payload && payload.target) || "").trim();
    if (!source || !target) {
      throw new Error("rename_tag requires both source and target.");
    }
    if (source === target) {
      return { renamed: false, skipped: true, source, target };
    }
    const tag = await getTagByName(source);
    if (!tag) {
      throw new Error(`Could not find tag: ${source}`);
    }
    tag.name = target;
    const saved = await tag.save();
    return {
      renamed: Boolean(saved),
      source,
      target,
    };
  }

  async function handleMergeTags(payload) {
    const source = String((payload && payload.source) || "").trim();
    const target = String((payload && payload.target) || "").trim();
    if (!source || !target) {
      throw new Error("merge_tags requires both source and target.");
    }
    if (!eagle || !eagle.tag || typeof eagle.tag.merge !== "function") {
      throw new Error("eagle.tag.merge is not available in this plugin runtime.");
    }
    const result = await eagle.tag.merge({ source, target });
    return {
      source,
      target,
      ...result,
    };
  }

  async function handleRenameItems(payload) {
    const operations = Array.isArray(payload.operations) ? payload.operations : [];
    const ids = operations.map((operation) => operation.item_id).filter(Boolean);
    const items = await getItemsByIds(ids);
    const itemMap = new Map(items.map((item) => [item.id, item]));
    const results = [];

    for (const operation of operations) {
      const item = itemMap.get(operation.item_id);
      if (!item) {
        results.push({ item_id: operation.item_id, status: "missing" });
        continue;
      }
      const nextName = String(operation.new_name || "").trim();
      if (!nextName || item.name === nextName) {
        results.push({ item_id: item.id, name: item.name, status: "skipped" });
        continue;
      }
      item.name = nextName;
      await item.save();
      results.push({ item_id: item.id, name: nextName, status: "updated" });
    }

    return { count: results.length, results };
  }

  async function handleMoveItems(payload) {
    const operations = Array.isArray(payload.operations) ? payload.operations : [];
    const ids = operations.map((operation) => operation.item_id).filter(Boolean);
    const items = await getItemsByIds(ids);
    const itemMap = new Map(items.map((item) => [item.id, item]));
    const results = [];

    for (const operation of operations) {
      const item = itemMap.get(operation.item_id);
      if (!item) {
        results.push({ item_id: operation.item_id, status: "missing" });
        continue;
      }
      const folderIds = Array.isArray(operation.folder_ids)
        ? operation.folder_ids.filter(Boolean).map(String)
        : [];
      const currentFolders = Array.isArray(item.folders) ? item.folders.map(String) : [];
      if (JSON.stringify(currentFolders) === JSON.stringify(folderIds)) {
        results.push({ item_id: item.id, folders: currentFolders, status: "skipped" });
        continue;
      }
      item.folders = folderIds;
      await item.save();
      results.push({ item_id: item.id, folders: folderIds, status: "updated" });
    }

    return { count: results.length, results };
  }

  async function processRequestFile(filename) {
    const requestPath = path.join(requestsDir, filename);
    const raw = fs.readFileSync(requestPath, "utf8");
    const request = JSON.parse(raw);
    const response = {
      kind: "eagle-cli-bridge-response",
      version: 1,
      id: request.id,
      action: request.action,
      processedAt: new Date().toISOString(),
      status: "success",
      data: null,
    };

    try {
      if (request.action === "ping") {
        response.data = await handlePing(request.payload || {});
      } else if (request.action === "show_app") {
        response.data = await handleShowApp();
      } else if (request.action === "get_context") {
        response.data = await handleGetContext(request.payload || {});
      } else if (request.action === "get_selected_item_ids") {
        response.data = await handleGetSelectedItemIds();
      } else if (request.action === "get_recent_tags") {
        response.data = await handleGetRecentTags();
      } else if (request.action === "get_starred_tags") {
        response.data = await handleGetStarredTags();
      } else if (request.action === "select_items") {
        response.data = await handleSelectItems(request.payload || {});
      } else if (request.action === "open_folder") {
        response.data = await handleOpenFolder(request.payload || {});
      } else if (request.action === "open_items") {
        response.data = await handleOpenItems(request.payload || {});
      } else if (request.action === "rename_tag") {
        response.data = await handleRenameTag(request.payload || {});
      } else if (request.action === "merge_tags") {
        response.data = await handleMergeTags(request.payload || {});
      } else if (request.action === "rename_items") {
        response.data = await handleRenameItems(request.payload || {});
      } else if (request.action === "move_items") {
        response.data = await handleMoveItems(request.payload || {});
      } else {
        throw new Error(`Unsupported bridge action: ${request.action}`);
      }
      log(`processed ${request.action} (${request.id})`);
    } catch (error) {
      response.status = "error";
      response.error = error.message;
      log(`failed ${request.action} (${request.id}): ${error.message}`);
    }

    const responsePath = path.join(responsesDir, `${request.id}.json`);
    writeJson(responsePath, response);
    fs.renameSync(requestPath, path.join(processedDir, filename));
    processedRequests += 1;
  }

  async function pollRequests() {
    if (isProcessing) {
      return;
    }
    isProcessing = true;
    try {
      const filenames = fs.readdirSync(requestsDir).filter((name) => name.endsWith(".json")).sort();
      for (const filename of filenames) {
        await processRequestFile(filename);
      }
    } catch (error) {
      log(`poll failed: ${error.message}`);
    } finally {
      isProcessing = false;
    }
  }

  async function bootstrap() {
    ensureDirs();
    log(`bridge bootstrap version=${pluginVersion} pid=${process.pid}`);
    await writeStatus();
    setInterval(writeStatus, STATUS_HEARTBEAT_MS);
    setInterval(pollRequests, REQUEST_POLL_MS);
    setTimeout(pollRequests, 250);
  }

  window.addEventListener("error", (event) => {
    const detail = event && event.error && event.error.stack ? event.error.stack : event.message;
    log(`window error: ${detail}`);
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event && event.reason && event.reason.stack ? event.reason.stack : String(event.reason);
    log(`unhandled rejection: ${reason}`);
  });

  if (window.eagle && typeof window.eagle.onPluginCreate === "function") {
    window.eagle.onPluginCreate(async () => {
      await bootstrap();
    });
  } else {
    bootstrap().catch((error) => {
      log(`bootstrap error: ${error.message}`);
    });
  }
})();
