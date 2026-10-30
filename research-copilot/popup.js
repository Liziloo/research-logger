const topicInput = document.getElementById("topicInput");
const toggleBtn = document.getElementById("toggleBtn");
const statusText = document.getElementById("statusText");
const serverUrlInput = document.getElementById("serverUrlInput");
const tokenInput = document.getElementById("tokenInput");
const saveSettingsBtn = document.getElementById("saveSettingsBtn");

async function init() {
  const config = await chrome.storage.sync.get({
    serverUrl: "http://192.168.5.159:8766",
    apiToken: "change-this-to-a-secure-random-token",
    sessionActive: false,
    sessionTopic: ""
  });

  serverUrlInput.value = config.serverUrl;
  tokenInput.value = config.apiToken;
  topicInput.value = config.sessionTopic || "";

  renderState(config.sessionActive, config.sessionTopic);
}

function renderState(active, topic) {
  if (active) {
    toggleBtn.textContent = "Stop Session";
    toggleBtn.className = "btn-stop";
    statusText.textContent = `Logging to session: "${topic || "Family Research"}"`;
    topicInput.disabled = true;
  } else {
    toggleBtn.textContent = "Start Session";
    toggleBtn.className = "btn-start";
    statusText.textContent = "No active session.";
    topicInput.disabled = false;
  }
}

toggleBtn.addEventListener("click", async () => {
  const config = await chrome.storage.sync.get(["sessionActive", "serverUrl", "apiToken"]);
  const nextState = !config.sessionActive;
  const topic = topicInput.value.trim() || "Family Research";

  const endpoint = nextState ? "/session/start" : "/session/stop";
  const body = nextState ? JSON.stringify({ topic }) : null;

  try {
    const res = await fetch(`${config.serverUrl}${endpoint}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${config.apiToken}`
      },
      body: body
    });

    if (!res.ok) throw new Error("HTTP " + res.status);

    await chrome.storage.sync.set({
      sessionActive: nextState,
      sessionTopic: nextState ? topic : ""
    });

    renderState(nextState, topic);
  } catch (err) {
    statusText.textContent = "Error: Cannot reach logger server!";
    console.error(err);
  }
});

saveSettingsBtn.addEventListener("click", async () => {
  await chrome.storage.sync.set({
    serverUrl: serverUrlInput.value.trim(),
    apiToken: tokenInput.value.trim()
  });
  alert("Settings saved!");
});

init();
