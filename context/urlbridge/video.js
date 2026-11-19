let lastVideo;
let lastTime = 0;
let advancedAt = 0;

function visibleArea(video) {
    if (!video.videoWidth || !video.videoHeight) return 0;
    const box = video.getBoundingClientRect();
    if (box.width < 160 || box.height < 90) return 0;
    const width = Math.max(0, Math.min(box.right, innerWidth) - Math.max(box.left, 0));
    const height = Math.max(0, Math.min(box.bottom, innerHeight) - Math.max(box.top, 0));
    return width * height;
}

function reportPlayback() {
    if (document.hidden) return;
    let video, area = 0;
    for (const candidate of document.querySelectorAll("video")) {
        const size = visibleArea(candidate);
        if (size > area) {
            video = candidate;
            area = size;
        }
    }

    let activity = "";
    if (video) {
        const now = performance.now();
        if (video !== lastVideo) {
            lastVideo = video;
            lastTime = video.currentTime;
            advancedAt = 0;
        } else if (video.currentTime !== lastTime) {
            lastTime = video.currentTime;
            advancedAt = now;
        }
        if (video.ended) activity = "ended";
        else if (video.paused) activity = "paused";
        else if (video.readyState >= 3 && advancedAt && now - advancedAt < 1000) activity = "playing";
        else activity = "buffering";
    } else {
        lastVideo = null;
    }
    chrome.runtime.sendMessage({ type: "video-playback", activity }).catch(() => {});
}

document.addEventListener("visibilitychange", reportPlayback);
for (const event of ["play", "playing", "pause", "ended", "waiting", "seeked"]) {
    document.addEventListener(event, reportPlayback, true);
}
setInterval(reportPlayback, 500);
reportPlayback();
