const browser = /\bEdg\//.test(navigator.userAgent) ? "msedge.exe" : "chrome.exe";
const lastVideo = new Map();
let lastUrl = "";
let revision = 0;
let deliveries = Promise.resolve();

function post(port, path, body) {
    return fetch(`http://127.0.0.1:${port}/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(1500),
    }).catch(() => {});
}

async function sendActiveTab() {
    const version = ++revision;
    let window;
    try {
        window = await chrome.windows.getLastFocused({ populate: true });
    } catch {
        return;
    }
    const active = window.focused ? window.tabs?.find(tab => tab.active) : null;
    if (version !== revision) return;

    const report = { browser, tab: active?.id ?? -1, title: (active?.title || "").slice(0, 1024), activity: "" };
    if (active?.url) {
        if (active.url !== lastUrl) {
            lastUrl = active.url;
            post(8765, "url", { url: active.url });
        }
        const path = new URL(active.url).pathname;
        const video = lastVideo.get(active.id);
        if (active.status === "complete" && /\.pdf$/i.test(path)) {
            report.activity = "pdf";
        } else if (video && video.url === active.url && Date.now() - video.at < 2500) {
            report.activity = video.activity;
        }
    }
    deliveries = deliveries.then(() => {
        if (version === revision) return post(8766, "activity", report);
    });
}

chrome.runtime.onMessage.addListener((message, sender) => {
    if (message?.type !== "video-playback" || sender.frameId !== 0 || !sender.tab?.id
        || !["", "playing", "paused", "buffering", "ended"].includes(message.activity)) return;
    lastVideo.set(sender.tab.id, { url: sender.url, activity: message.activity, at: Date.now() });
    if (sender.tab.active) sendActiveTab();
});
chrome.tabs.onActivated.addListener(sendActiveTab);
chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
    if (change.url) lastVideo.delete(tabId);
    if (tab.active && (change.url || change.title || change.status)) sendActiveTab();
});
chrome.tabs.onRemoved.addListener(tabId => {
    lastVideo.delete(tabId);
    sendActiveTab();
});
chrome.windows.onFocusChanged.addListener(sendActiveTab);
chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === "foreground-tab") sendActiveTab();
});

async function start() {
    if (!(await chrome.alarms.get("foreground-tab"))) {
        await chrome.alarms.create("foreground-tab", { periodInMinutes: 0.5 });
    }
    sendActiveTab();
}
chrome.runtime.onInstalled.addListener(start);
chrome.runtime.onStartup.addListener(start);
start();
