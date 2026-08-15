(() => {
  let preference = "system";
  try {
    preference = localStorage.getItem("cygnus-theme") || "system";
  } catch {
    // Storage can be unavailable in privacy-restricted contexts; system wins.
  }
  const dark =
    preference === "dark" ||
    (preference === "system" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
})();
