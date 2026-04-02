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
  const pluginId = "2f40db08-5ce8-4d72-9fb7-a8fdcb5c1f6b";
  const pluginName = "CLI-Anything Eagle Bridge";
  const pluginVersion = "0.7.0";

  const statusNode = document.getElementById("status");
  const statePathNode = document.getElementById("state-path");
  const logNode = document.getElementById("log");
  const logLines = [];

  let isProcessing = false;
  let processedRequests = 0;

  function log(message) {
    const line = `${new Date().toISOString()} ${message}`;
    logLines.unshift(line);
    while (logLines.length > 20) {
      logLines.pop();
    }
    if (logNode) {
      logNode.textContent = logLines.join("\n");
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

  async function collectStatus() {
    let library = null;
    try {
      if (eagle && eagle.library && typeof eagle.library.info === "function") {
        library = await eagle.library.info();
      }
    } catch (error) {
      log(`library.info failed: ${error.message}`);
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
      fs.writeFileSync(statusPath, JSON.stringify(payload, null, 2), "utf8");
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

  async function getItemsByIds(ids) {
    if (!Array.isArray(ids) || ids.length === 0) {
      return [];
    }
    if (!eagle || !eagle.item || typeof eagle.item.get !== "function") {
      throw new Error("eagle.item.get is not available in this plugin runtime.");
    }
    return await eagle.item.get({ ids });
  }

  async function handlePing(payload) {
    return {
      ok: true,
      echoed: payload || {},
      status: await collectStatus(),
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
    fs.writeFileSync(responsePath, JSON.stringify(response, null, 2), "utf8");
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
    log("bridge bootstrap");
    await writeStatus();
    setInterval(writeStatus, 2000);
    setInterval(pollRequests, 1000);
    setTimeout(pollRequests, 250);
  }

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
