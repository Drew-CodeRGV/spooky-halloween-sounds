// Tap a section's title to fold it up. Each device remembers which sections are closed.
(function () {
  const KEY = "spooky-collapsed:" + location.pathname;
  let closed = [];
  try { closed = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { closed = []; }
  const remember = () => {
    try { localStorage.setItem(KEY, JSON.stringify(closed)); } catch { /* private mode: just don't remember */ }
  };

  document.querySelectorAll("section.panel").forEach((panel) => {
    const title = panel.querySelector(":scope > h2, :scope > .r-head > h2");
    if (!title) return;
    const head = title.parentElement === panel ? title : title.parentElement;
    const name = title.textContent.trim();

    // Everything after the heading goes into a body we can hide
    const body = document.createElement("div");
    body.className = "panel-body";
    while (head.nextSibling) body.appendChild(head.nextSibling);
    panel.appendChild(body);

    // Keep a dropdown in the heading row (e.g. the remote's soundboard target) visible but usable
    const toggleEl = document.createElement("button");
    toggleEl.type = "button";
    toggleEl.className = "collapse-toggle";
    toggleEl.setAttribute("aria-label", `Show or hide ${name}`);
    title.classList.add("collapsible");
    title.prepend(toggleEl);

    const set = (isClosed) => {
      panel.classList.toggle("collapsed", isClosed);
      toggleEl.setAttribute("aria-expanded", String(!isClosed));
    };
    set(closed.includes(name));
    title.addEventListener("click", () => {
      const isClosed = !panel.classList.contains("collapsed");
      set(isClosed);
      closed = isClosed ? [...new Set([...closed, name])] : closed.filter((n) => n !== name);
      remember();
    });
  });
})();
