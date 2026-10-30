// Bộ lọc nhanh theo nhãn, mục, nguồn. Không có JavaScript thì mọi tin vẫn hiện.
(function () {
  var state = { label: "all", cat: "all", src: "all" };
  function update() {
    var stories = document.querySelectorAll(".story[data-label]");
    var shown = 0;
    stories.forEach(function (el) {
      var ok = (state.label === "all" || el.dataset.label === state.label) &&
               (state.cat === "all" || el.dataset.cat === state.cat) &&
               (state.src === "all" || (" " + el.dataset.srcs + " ").indexOf(" " + state.src + " ") >= 0);
      el.hidden = !ok; if (ok) shown++;
    });
    document.querySelectorAll("section[data-group]").forEach(function (sec) {
      sec.hidden = !sec.querySelector(".story:not([hidden])");
    });
    var c = document.getElementById("filter-count");
    if (c) c.textContent = "Đang hiện " + shown + "/" + stories.length + " tin";
  }
  document.addEventListener("DOMContentLoaded", function () {
    var bar = document.getElementById("filters");
    if (!bar) return;
    bar.hidden = false;
    bar.querySelectorAll("[data-label-btn]").forEach(function (b) {
      b.addEventListener("click", function () {
        state.label = b.dataset.labelBtn;
        bar.querySelectorAll("[data-label-btn]").forEach(function (x) {
          x.setAttribute("aria-pressed", x === b ? "true" : "false");
        });
        update();
      });
    });
    document.getElementById("f-cat").addEventListener("change", function (e) { state.cat = e.target.value; update(); });
    document.getElementById("f-src").addEventListener("change", function (e) { state.src = e.target.value; update(); });
    update();
  });
})();
