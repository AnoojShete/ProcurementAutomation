// System architecture page: the two-slide carousel and the clickable diagram.
// Diagrams come from docs/assets/make_architecture_carousel.py; every box is a
// .node with data-links (the ids it connects to). Clicking one dims everything
// it does not connect to and puts its role in the slide's caption.

function wireDiagram(svg, caption) {
  const hint = caption.innerHTML;
  let selected = "";
  function clear() {
    selected = "";
    svg.classList.remove("focus");
    svg.querySelectorAll(".on").forEach((el) => el.classList.remove("on"));
    caption.innerHTML = hint;
  }
  function pick(node) {
    const id = node.dataset.id;
    if (selected === id) return clear();
    selected = id;
    svg.classList.add("focus");
    svg.querySelectorAll("[data-links]").forEach((el) => {
      const on = el.dataset.id === id || el.dataset.links.split(" ").includes(id);
      el.classList.toggle("on", on);
    });
    caption.innerHTML = "";
    const b = document.createElement("b");
    b.textContent = node.dataset.name + ": ";
    caption.append(b, node.dataset.info);
  }
  svg.addEventListener("click", (e) => {
    const node = e.target.closest(".node");
    node ? pick(node) : clear();
  });
  svg.addEventListener("keydown", (e) => {
    const node = e.target.closest(".node");
    if (node && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); pick(node); }
    if (e.key === "Escape") clear();
  });
}

function wireCarousel(root) {
  const track = root.querySelector(".arch-track");
  const slides = [...root.querySelectorAll(".arch-slide")];
  const dots = [...root.querySelectorAll(".arch-dots button")];
  const step = root.querySelector(".arch-step");
  const title = root.querySelector(".arch-title");
  let index = 0;
  function show(i, smooth = true) {
    index = Math.max(0, Math.min(slides.length - 1, i));
    track.scrollTo({ left: slides[index].offsetLeft - track.offsetLeft, behavior: smooth ? "smooth" : "auto" });
    mark();
  }
  function mark() {
    dots.forEach((d, n) => d.setAttribute("aria-current", n === index ? "true" : "false"));
    step.textContent = index + 1 + " of " + slides.length;
    title.textContent = slides[index].dataset.title;
    root.querySelector("[data-go='-1']").disabled = index === 0;
    root.querySelector("[data-go='1']").disabled = index === slides.length - 1;
  }
  root.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => show(index + Number(b.dataset.go))));
  dots.forEach((d, n) => d.addEventListener("click", () => show(n)));
  track.addEventListener("scroll", () => {
    const i = Math.round(track.scrollLeft / track.clientWidth);
    if (i !== index) { index = i; mark(); }
  }, { passive: true });
  root.addEventListener("keydown", (e) => {
    if (e.target.closest(".node")) return;
    if (e.key === "ArrowRight") { e.preventDefault(); show(index + 1); }
    if (e.key === "ArrowLeft") { e.preventDefault(); show(index - 1); }
  });
  const full = root.querySelector(".arch-full");
  if (full && root.requestFullscreen) {
    full.addEventListener("click", () => (document.fullscreenElement ? document.exitFullscreen() : root.requestFullscreen()));
    document.addEventListener("fullscreenchange", () => {
      full.setAttribute("aria-pressed", document.fullscreenElement === root ? "true" : "false");
      show(index, false);
    });
  } else if (full) {
    full.hidden = true;
  }
  window.addEventListener("resize", () => show(index, false));
  slides.forEach((s) => wireDiagram(s.querySelector("svg.arch"), s.querySelector(".arch-caption")));
  mark();
}

function initArchitecture() {
  document.querySelectorAll("[data-arch-carousel]").forEach((root) => {
    if (root.dataset.wired) return;
    root.dataset.wired = "1";
    wireCarousel(root);
  });
}

if (window.document$) window.document$.subscribe(initArchitecture);
else document.addEventListener("DOMContentLoaded", initArchitecture);
