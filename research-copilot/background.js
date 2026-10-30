const BLOCKLIST = [
  "accounts.google.com",
  "mail.google.com",
  "chase.com",
  "paypal.com",
  "bankofamerica.com",
  "wellsfargo.com",
  "login.",
  "signin."
];

// 12-second dwell timer to skip fast redirects and glancing tabs
const DWELL_TIME_MS = 12000;
let pendingTimers = {};

async function getConfig() {
  return await chrome.storage.sync.get({
    serverUrl: "http://192.168.5.159:8766",
    apiToken: "change-this-to-a-secure-random-token",
    sessionActive: false,
    sessionTopic: ""
  });
}

function updateBadge(active) {
  if (active) {
    chrome.action.setBadgeText({ text: "REC" });
    chrome.action.setBadgeBackgroundColor({ color: "#22c55e" });
  } else {
    chrome.action.setBadgeText({ text: "" });
  }
}

// Manage captured URLs persistently in storage so worker idle reloads don't duplicate captures
async function hasBeenCaptured(url) {
  const store = await chrome.storage.local.get({ capturedUrls: [] });
  return store.capturedUrls.includes(url);
}

async function markCaptured(url) {
  const store = await chrome.storage.local.get({ capturedUrls: [] });
  store.capturedUrls.push(url);
  // Cap at 1000 items to avoid storage bloat
  if (store.capturedUrls.length > 1000) store.capturedUrls.shift();
  await chrome.storage.local.set({ capturedUrls: store.capturedUrls });
}

async function queueOfflineCapture(payload) {
  const store = await chrome.storage.local.get({ offlineQueue: [] });
  store.offlineQueue.push(payload);
  await chrome.storage.local.set({ offlineQueue: store.offlineQueue });
}

async function flushOfflineQueue() {
  const config = await getConfig();
  const store = await chrome.storage.local.get({ offlineQueue: [] });
  if (!store.offlineQueue || store.offlineQueue.length === 0) return;

  const queue = [...store.offlineQueue];
  const remaining = [];

  for (const item of queue) {
    try {
      const resp = await fetch(`${config.serverUrl}/capture`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${config.apiToken}`
        },
        body: JSON.stringify(item)
      });
      if (!resp.ok) remaining.push(item);
    } catch (err) {
      remaining.push(item);
    }
  }
  await chrome.storage.local.set({ offlineQueue: remaining });
}

// MV3 Alarm for reliable background retry
chrome.alarms.create("flushQueueAlarm", { periodInMinutes: 1.0 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "flushQueueAlarm") {
    flushOfflineQueue();
  }
});

// React instantly to session toggles
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "sync" && changes.sessionActive) {
    updateBadge(changes.sessionActive.newValue);
    if (changes.sessionActive.newValue === true) {
      // Clear captured list on new session
      chrome.storage.local.set({ capturedUrls: [] });
    }
  }
});

async function captureTab(tabId) {
  const config = await getConfig();
  if (!config.sessionActive) return;

  let tab;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch (e) {
    return;
  }

  if (!tab || !tab.url || tab.incognito) return;
  if (!tab.url.startsWith("http://") && !tab.url.startsWith("https://")) return;

  const urlObj = new URL(tab.url);
  if (BLOCKLIST.some((domain) => urlObj.hostname.includes(domain))) return;
  if (await hasBeenCaptured(tab.url)) return;

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content.js"]
    });

    if (!results || !results[0] || !results[0].result) return;
    const extracted = results[0].result;

    await markCaptured(tab.url);

    const payload = {
      url: tab.url,
      title: tab.title || "Untitled",
      isImageRecord: extracted.isImageRecord,
      recordData: extracted.recordData,
      transcription: extracted.transcription,
      selection: extracted.selection,
      rawFallback: extracted.rawFallback,
      timestamp: new Date().toISOString()
    };

    fetch(`${config.serverUrl}/capture`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${config.apiToken}`
      },
      body: JSON.stringify(payload)
    }).catch((err) => {
      console.warn("[Copilot] Server unreachable, queued offline:", err);
      queueOfflineCapture(payload);
    });
  } catch (err) {
    // Restricted tab or closed before execution
  }
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete") {
    if (pendingTimers[tabId]) clearTimeout(pendingTimers[tabId]);
    pendingTimers[tabId] = setTimeout(() => {
      captureTab(tabId);
      delete pendingTimers[tabId];
    }, DWELL_TIME_MS);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (pendingTimers[tabId]) {
    clearTimeout(pendingTimers[tabId]);
    delete pendingTimers[tabId];
  }
});

getConfig().then((cfg) => updateBadge(cfg.sessionActive));
