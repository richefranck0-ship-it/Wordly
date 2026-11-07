document.getElementById("wipe-local")?.addEventListener("click", () => {
  ["wl_tr_hist", "wl_city", "wl_push_dismiss"].forEach(k => window.WL.store.del(k));
  document.getElementById("wipe-msg").textContent = window.WL.t.saved;
});
