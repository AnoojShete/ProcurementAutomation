// Applies the saved theme before the first paint, so a dark-mode user never
// sees a white flash. A separate file because the CSP allows no inline
// scripts. The account's saved preference (auth /me) takes over once
// signed in; see src/hooks/useTheme.tsx, which uses the same storage key.
(function () {
  var pref = "system";
  try {
    pref = localStorage.getItem("procurement.theme") || "system";
  } catch (e) {}
  var dark = pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
})();
