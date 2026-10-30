// Chế độ sáng/tối: Tự động -> Sáng -> Tối; nhớ lựa chọn trên trình duyệt (nếu được phép)
(function () {
  var KEY = "digest-theme";
  var LABEL = { auto: "Giao diện: tự động", light: "Giao diện: sáng", dark: "Giao diện: tối" };
  var root = document.documentElement;
  function load() { try { return localStorage.getItem(KEY) || "auto"; } catch (e) { return "auto"; } }
  function save(v) { try { localStorage.setItem(KEY, v); } catch (e) {} }
  function apply(v) {
    if (v === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", v);
    var b = document.getElementById("theme-btn"); if (b) b.textContent = LABEL[v];
  }
  var current = load(); apply(current);
  document.addEventListener("DOMContentLoaded", function () {
    apply(current);
    var b = document.getElementById("theme-btn");
    if (!b) return;
    b.addEventListener("click", function () {
      current = current === "auto" ? "light" : current === "light" ? "dark" : "auto";
      save(current); apply(current);
    });
  });
})();
