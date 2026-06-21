function centerCurrentTimeline() {
  const timelineTrack = document.querySelector("[data-run-timeline-track]");
  if (!timelineTrack) {
    return;
  }

  if (!window.matchMedia("(max-width: 860px)").matches) {
    return;
  }

  const currentCard = timelineTrack.querySelector("[data-timeline-current='true']");
  if (!currentCard) {
    return;
  }

  const targetScrollLeft = currentCard.offsetLeft - ((timelineTrack.clientWidth - currentCard.clientWidth) / 2);
  timelineTrack.scrollTo({
    left: Math.max(0, targetScrollLeft),
    behavior: "auto",
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".input-card").forEach((card) => {
    const buttons = Array.from(card.querySelectorAll("[data-editor-tab]"));
    const panels = Array.from(card.querySelectorAll("[data-editor-panel]"));
    const modeTarget = card.querySelector("[data-editor-mode-target]");
    if (buttons.length && panels.length && modeTarget) {
      const activate = (mode) => {
        buttons.forEach((button) => {
          button.classList.toggle("active", button.dataset.editorTab === mode);
        });
        panels.forEach((panel) => {
          panel.hidden = panel.dataset.editorPanel !== mode;
        });
        modeTarget.value = mode;
      };
      activate(modeTarget.value || "structured");
      buttons.forEach((button) => {
        button.addEventListener("click", () => activate(button.dataset.editorTab || "structured"));
      });
    }
  });

  document.querySelectorAll("[data-dirty-form]").forEach((form) => {
    const indicator = form.querySelector(".dirty-indicator");
    if (!indicator) {
      return;
    }
    const markDirty = () => {
      indicator.hidden = false;
    };
    form.querySelectorAll("input, textarea, select").forEach((field) => {
      field.addEventListener("input", markDirty, { passive: true });
      field.addEventListener("change", markDirty, { passive: true });
    });
    form.addEventListener("submit", () => {
      indicator.hidden = true;
    });
  });

  let resizeFrame = 0;
  const queueTimelineCentering = () => {
    if (resizeFrame) {
      window.cancelAnimationFrame(resizeFrame);
    }
    resizeFrame = window.requestAnimationFrame(() => {
      resizeFrame = 0;
      centerCurrentTimeline();
    });
  };

  window.requestAnimationFrame(() => {
    window.requestAnimationFrame(centerCurrentTimeline);
  });
  window.addEventListener("resize", queueTimelineCentering, { passive: true });

  const runPanel = document.querySelector("[data-run-stream-url]");
  if (!runPanel) {
    return;
  }

  const streamUrl = runPanel.dataset.runStreamUrl;
  if (!streamUrl) {
    return;
  }

  const eventSource = new EventSource(streamUrl);
  eventSource.addEventListener("snapshot", (event) => {
    try {
      const payload = JSON.parse(event.data);
      const knownUpdate = runPanel.dataset.lastUpdated || "";
      const nextUpdate = payload.updated_at || payload.finished_at || "";
      if (nextUpdate && nextUpdate !== knownUpdate) {
        window.location.reload();
      }
    } catch (_error) {
      window.location.reload();
    }
  });
});
