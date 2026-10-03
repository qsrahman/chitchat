// A classic script, run before the page paints so a saved theme doesn't flash the other one first.
// The button that changes it is in appearance.js.
try {
  const theme = localStorage.getItem("theme");
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
} catch { /* storage blocked: follow the system */ }
