let lastUrl = "";
const endpoint = "http://127.0.0.1:8765/url";

function sendUrlToLocalhost(url) {
    fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
    }).catch(() => {
        // Ignore errors when the local server is not running.
    });
}

function sendActiveTabUrl() {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (!tabs || !tabs.length) {
            return;
        }

        const url = tabs[0].url || "";
        if (!url || url === lastUrl) {
            return;
        }

        lastUrl = url;
        sendUrlToLocalhost(url);
    });
}

chrome.tabs.onActivated.addListener(sendActiveTabUrl);
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.url) {
        sendActiveTabUrl();
    }
});

chrome.windows.onFocusChanged.addListener(() => {
    sendActiveTabUrl();
});

chrome.runtime.onInstalled.addListener(() => {
    sendActiveTabUrl();
});
