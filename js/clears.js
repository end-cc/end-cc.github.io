
const THUMB_DIR = "../thumbs/";
const FULL_DIR  = "../full/";
const PHASE_NAMES = ["Day 1", "Week 1", "Week 2", "Week 2+"];
const PHASE_VARS  = ["--day1", "--week1", "--week2", "--week2p"];

const params = new URLSearchParams(location.search);
const season = params.get("s") || "beta";

const board = document.getElementById("board");
const opStrip = document.getElementById("opStrip");
const phaseFilter = document.getElementById("phaseFilter");
const titleEl = document.getElementById("pageTitle");
const countEl = document.getElementById("clearCount");
const lightbox = document.getElementById("lightbox");
const lbImg = lightbox.querySelector(".lightbox-img");
const lbMeta = lightbox.querySelector(".lightbox-meta");

let entries = [];
const activePhases = new Set([0, 1, 2, 3]);
const activeOps = new Set();

init();

async function init() {
	// title from seasons.json (best-effort)
	try {
		const seasons = await (await fetch("../data/seasons.json", { cache: "no-cache" })).json();
		const meta = seasons.find(s => s.id === season);
		document.title = (meta && meta.title) || "CC Clears";
		titleEl.textContent = (meta && meta.title) || "CC Clears";
	} catch (e) {}

	let raw;
	try {
		raw = await (await fetch(`../data/${season}/clears.json`, { cache: "no-cache" })).json();
	} catch (e) {
		board.innerHTML = `<p class="status">Could not load data/${season}/clears.json</p>`;
		return;
	}

	entries = Object.entries(raw).map(([key, v]) => ({
		key,
		risk: Number(v.risk),
		group: Number.isFinite(Number(v.group)) ? Number(v.group) : 0,
		squad: Array.isArray(v.squad) ? v.squad.map(o => o.name || o) : [],
		submitter: v.submitter || "Anon",
		date: v.date || "",
		thumb: v.thumb || THUMB_DIR + key,
		full: v.full || FULL_DIR + key,
	})).filter(e => Number.isFinite(e.risk));

	buildOpStrip();
	wirePhaseFilter();
	render();
}

function filtered() {
	return entries.filter(e =>
		activePhases.has(e.group) &&
		(activeOps.size === 0 || [...activeOps].every(op => e.squad.includes(op)))
	);
}

function buildOpStrip() {
	const all = [...new Set(entries.flatMap(e => e.squad))].sort();
	opStrip.innerHTML = "";
	for (const name of all) {
		const chip = document.createElement("span");
		const img = document.createElement("img");
		img.src = `../icons/ops/${encodeURIComponent(name)}.webp`;
		img.alt = "";
		img.addEventListener("error", () => img.remove());   // no icon yet -> name only
		const label = document.createElement("span");
		label.textContent = name;
		chip.append(img, label);
		chip.addEventListener("click", () => {
			chip.classList.toggle("active");
			if (activeOps.has(name)) activeOps.delete(name); else activeOps.add(name);
			render();
		});
		opStrip.appendChild(chip);
	}
	const hint = document.createElement("span");
	hint.className = "op-strip-hint";
	hint.textContent = "click operators to filter (shows clears using all selected)";
	opStrip.appendChild(hint);
}

function wirePhaseFilter() {
	phaseFilter.querySelectorAll(".phase").forEach(btn => {
		const g = Number(btn.dataset.group);
		btn.addEventListener("click", () => {
			btn.classList.toggle("active");
			if (activePhases.has(g)) activePhases.delete(g); else activePhases.add(g);
			render();
		});
	});
}

function render() {
	const list = filtered();
	countEl.textContent = list.length;

	const byRisk = new Map();
	for (const e of list) {
		if (!byRisk.has(e.risk)) byRisk.set(e.risk, []);
		byRisk.get(e.risk).push(e);
	}
	const risks = [...byRisk.keys()].sort((a, b) => b - a);

	board.innerHTML = "";
	if (!risks.length) { board.innerHTML = '<p class="status">No clears match the current filters.</p>'; return; }

	for (const r of risks) {
		const group = byRisk.get(r);
		const section = document.createElement("section");
		section.className = "risk-section";
		section.innerHTML = `<div class="risk-header">RISK ${r}<span class="rc">${group.length} clear${group.length === 1 ? "" : "s"}</span></div>`;
		const grid = document.createElement("div");
		grid.className = "grid";
		group.forEach(e => grid.appendChild(card(e)));
		section.appendChild(grid);
		board.appendChild(section);
	}
}

function card(e) {
	const el = document.createElement("article");
	el.className = "card";

	const thumb = document.createElement("div");
	thumb.className = "card-thumb";
	const img = document.createElement("img");
	img.loading = "lazy";
	img.alt = `Risk ${e.risk} clear by ${e.submitter}`;
	img.src = e.thumb;
	img.addEventListener("error", () => thumb.classList.add("broken"));
	thumb.appendChild(img);
	thumb.addEventListener("click", () => openLightbox(e));

	const body = document.createElement("div");
	body.className = "card-body";
	if (e.squad.length) {
		const ops = document.createElement("div");
		ops.className = "ops";
		e.squad.forEach(n => {
		const s = document.createElement("span");
		s.className = "op";
		const img = document.createElement("img");
		img.src = `../icons/ops/${encodeURIComponent(n)}.webp`;
		img.alt = "";
		img.addEventListener("error", () => img.remove());
		s.append(img, document.createTextNode(n));
		ops.appendChild(s);
	});
		body.appendChild(ops);
	}
	const foot = document.createElement("div");
	foot.className = "card-foot";
	const color = getComputedStyle(document.documentElement).getPropertyValue(PHASE_VARS[e.group] || "--muted");
	foot.innerHTML =
		`<span><span class="phase-dot" style="background:${color}"></span>${PHASE_NAMES[e.group] || ""}</span>` +
		`<span>${escapeHtml(e.submitter)}${e.date ? " · " + escapeHtml(e.date) : ""}</span>`;
	body.appendChild(foot);

	el.appendChild(thumb);
	el.appendChild(body);
	return el;
}

function openLightbox(e) {
	lbImg.src = e.full;
	lbImg.alt = `Risk ${e.risk} clear by ${e.submitter}`;
	const ops = e.squad.join(" · ");
	lbMeta.textContent = `RISK ${e.risk}  ·  ${PHASE_NAMES[e.group] || ""}  ·  ${e.submitter}${e.date ? "  ·  " + e.date : ""}${ops ? "  ·  " + ops : ""}`;
	lightbox.hidden = false;
}
function closeLightbox() { lightbox.hidden = true; lbImg.src = ""; }
lightbox.addEventListener("click", ev => { if (ev.target === lightbox || ev.target.classList.contains("lightbox-close")) closeLightbox(); });
document.addEventListener("keydown", ev => { if (ev.key === "Escape") closeLightbox(); });

function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
