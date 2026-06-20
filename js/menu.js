(async function () {
	const tiles = document.getElementById("tiles");
	let seasons;
	try {
		const res = await fetch("data/seasons.json", { cache: "no-cache" });
		seasons = await res.json();
	} catch (e) {
		tiles.innerHTML = '<p class="status">Could not load data/seasons.json</p>';
		return;
	}
	tiles.innerHTML = "";
	for (const s of seasons) {
		const a = document.createElement("a");
		a.className = "tile" + (s.disabled ? " disabled" : "");
		a.href = s.disabled ? "#" : `cc/?s=${encodeURIComponent(s.id)}`;
		a.innerHTML =
			`<div class="tile-icon">${s.icon ? `<img src="${s.icon}" alt="">` : ""}</div>` +
			`<div class="tile-name">${escapeHtml(s.label || s.id)}</div>`;
		tiles.appendChild(a);
	}
	function escapeHtml(t){return String(t).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
})();
