import initSqlJs from "https://esm.sh/sql.js@1.10.3";

const allChairs = Array.from({ length: 12 }, (_, i) => i + 1);
const selectedChairs = new Set(allChairs);

const wasmUrl = new URL("./vendor/sqljs-wasm.wasm", import.meta.url).toString();
const dataBaseUrl = new URL("./data/", import.meta.url);

let manifest = null;
let activeShardFile = null;
let activeDb = null;
let sqlJs = null;

function computeStateKey(attackerPoints, defenderPoints, attackerShocks, defenderShocks, chairMask) {
  return (
    (attackerPoints << 22) |
    (defenderPoints << 16) |
    (attackerShocks << 14) |
    (defenderShocks << 12) |
    chairMask
  );
}

function computeChairMask() {
  let mask = 0;
  for (const chair of selectedChairs) {
    mask |= 1 << (chair - 1);
  }
  return mask;
}

function countBits(n) {
  let count = 0;
  while (n) {
    count += n & 1;
    n >>= 1;
  }
  return count;
}

function deriveRoundNum(attackerShocks, defenderShocks, chairMask) {
  const totalShocks = attackerShocks + defenderShocks;
  const chairCount = countBits(chairMask);
  const removedChairs = 12 - chairCount;
  return totalShocks + removedChairs + 1;
}

function formatProb(prob) {
  return `${(Number(prob) * 100).toFixed(2)}%`;
}

function fillTable(tableId, strategy) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  tbody.innerHTML = "";
  for (const [chair, prob] of strategy) {
    if (Number(prob) < 0.0001) continue;
    const tr = document.createElement("tr");
    const tdChair = document.createElement("td");
    tdChair.textContent = String(chair);
    const tdProb = document.createElement("td");
    tdProb.textContent = formatProb(prob);
    tr.appendChild(tdChair);
    tr.appendChild(tdProb);
    tbody.appendChild(tr);
  }
}

function updateChairsHiddenInput() {
  const ordered = allChairs.filter((chair) => selectedChairs.has(chair));
  document.getElementById("chairs").value = ordered.join(",");
  const status = document.getElementById("chairs_selection_status");
  status.textContent = `選択中: ${ordered.length}脚`;
}

function renderChairButtons() {
  const container = document.getElementById("chair_grid");
  container.innerHTML = "";

  for (const chair of allChairs) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `chair-btn ${selectedChairs.has(chair) ? "active" : ""}`;
    button.textContent = String(chair);
    button.ariaPressed = selectedChairs.has(chair) ? "true" : "false";
    button.title = selectedChairs.has(chair) ? `椅子${chair}: 選択中` : `椅子${chair}: 未選択`;
    button.dataset.chair = String(chair);
    button.addEventListener("click", () => {
      if (selectedChairs.has(chair)) {
        selectedChairs.delete(chair);
      } else {
        selectedChairs.add(chair);
      }
      button.classList.toggle("active", selectedChairs.has(chair));
      button.ariaPressed = selectedChairs.has(chair) ? "true" : "false";
      button.title = selectedChairs.has(chair) ? `椅子${chair}: 選択中` : `椅子${chair}: 未選択`;
      updateChairsHiddenInput();
    });
    container.appendChild(button);
  }

  updateChairsHiddenInput();
}

function setupRange(inputId, valueId) {
  const input = document.getElementById(inputId);
  const value = document.getElementById(valueId);
  const sync = () => {
    value.textContent = input.value;
  };
  input.addEventListener("input", sync);
  sync();
}

function setupToggleButtons() {
  const buttons = document.querySelectorAll(".toggle-btn");
  for (const button of buttons) {
    button.addEventListener("click", () => {
      const target = button.dataset.target;
      const value = button.dataset.value;
      if (!target || value === undefined) return;

      document.getElementById(target).value = value;

      const group = button.parentElement;
      if (!group) return;
      for (const sibling of group.querySelectorAll(".toggle-btn")) {
        sibling.classList.remove("active");
      }
      button.classList.add("active");
    });
  }
}

function setToggleValue(targetId, value) {
  const hidden = document.getElementById(targetId);
  if (!hidden) return;
  hidden.value = String(value);

  const selector = `.toggle-btn[data-target="${targetId}"]`;
  const buttons = document.querySelectorAll(selector);
  for (const button of buttons) {
    const isActive = button.dataset.value === String(value);
    button.classList.toggle("active", isActive);
  }
}

function setupSwapSides() {
  const button = document.getElementById("swap_sides");
  if (!button) return;

  button.addEventListener("click", () => {
    const attackerPointsInput = document.getElementById("attacker_points");
    const defenderPointsInput = document.getElementById("defender_points");
    const attackerPoints = attackerPointsInput.value;
    const defenderPoints = defenderPointsInput.value;
    attackerPointsInput.value = defenderPoints;
    defenderPointsInput.value = attackerPoints;
    attackerPointsInput.dispatchEvent(new Event("input"));
    defenderPointsInput.dispatchEvent(new Event("input"));

    const attackerShocks = document.getElementById("attacker_shocks").value;
    const defenderShocks = document.getElementById("defender_shocks").value;
    setToggleValue("attacker_shocks", defenderShocks);
    setToggleValue("defender_shocks", attackerShocks);
  });
}

function updateDatasetStats(meta) {
  const el = document.getElementById("dataset-stats");
  if (!el || !meta) return;
  const rows = Number(meta.rows || 0).toLocaleString();
  const shards = Number(meta.shards || 0).toLocaleString();
  el.textContent = `データ件数: ${rows}件（${shards} shard）`;
}

function setupQuickChairActions() {
  document.getElementById("select_all").addEventListener("click", () => {
    selectedChairs.clear();
    for (const chair of allChairs) {
      selectedChairs.add(chair);
    }
    renderChairButtons();
  });

  document.getElementById("clear_all").addEventListener("click", () => {
    selectedChairs.clear();
    renderChairButtons();
  });
}

function getCell(row, key) {
  if (key in row) return row[key];
  const upper = key.toUpperCase();
  if (upper in row) return row[upper];
  return undefined;
}

function decodeStrategy(blob) {
  if (!blob) return [];
  const bytes = blob instanceof Uint8Array ? blob : new Uint8Array(blob);
  const pairs = [];
  let total = 0;
  for (let i = 0; i + 1 < bytes.length; i += 2) {
    total += bytes[i + 1];
  }
  if (total <= 0) return pairs;
  for (let i = 0; i + 1 < bytes.length; i += 2) {
    const chair = bytes[i];
    const q = bytes[i + 1];
    if (q <= 0) continue;
    pairs.push([chair, q / total]);
  }
  return pairs;
}

function findShardForKey(stateKey) {
  if (!manifest || !manifest.ranges) return null;
  for (const range of manifest.ranges) {
    if (stateKey >= range.min_key && stateKey <= range.max_key) {
      return range.file;
    }
  }
  return null;
}

async function loadManifest() {
  if (manifest) return manifest;
  const res = await fetch(new URL("sqlite_manifest.json", dataBaseUrl).toString());
  if (!res.ok) {
    throw new Error(`manifest fetch failed: ${res.status}`);
  }
  manifest = await res.json();
  return manifest;
}

async function ensureSqlJs() {
  if (sqlJs) return sqlJs;
  sqlJs = await initSqlJs({
    locateFile: () => wasmUrl,
  });
  return sqlJs;
}

async function loadShardDb(fileName) {
  if (activeDb && activeShardFile === fileName) return activeDb;

  const summary = document.getElementById("summary");
  if (summary.classList.contains("status-msg")) {
    summary.textContent = `SQLite shard読込中... (${fileName})`;
  }

  if (activeDb && typeof activeDb.close === "function") {
    try {
      activeDb.close();
    } catch (_e) {
      // ignore close errors
    }
  }

  const sqlite = await ensureSqlJs();
  const shardUrl = new URL(fileName, dataBaseUrl).toString();
  const resp = await fetch(shardUrl, { cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`shard fetch failed: ${resp.status} (${fileName})`);
  }

  const raw = await resp.arrayBuffer();
  activeDb = new sqlite.Database(new Uint8Array(raw));
  activeShardFile = fileName;
  return activeDb;
}

async function lookupState(stateKey) {
  const meta = await loadManifest();
  const shardFile = findShardForKey(stateKey);
  if (!shardFile) return null;
  const db = await loadShardDb(shardFile);
  const stmt = db.prepare("SELECT sv_i, a, d, t FROM lookup WHERE state_key = ?");
  try {
    stmt.bind([stateKey]);
    if (!stmt.step()) return null;

    const row = stmt.getAsObject();
    const svScale = Number(meta.sv_scale || 1000);
    return {
      sv: Number(getCell(row, "sv_i")) / svScale,
      a: decodeStrategy(getCell(row, "a")),
      d: decodeStrategy(getCell(row, "d")),
      t: Boolean(getCell(row, "t")),
    };
  } finally {
    stmt.free();
  }
}

async function onSubmit(event) {
  event.preventDefault();
  const summary = document.getElementById("summary");

  if (selectedChairs.size === 0) {
    summary.className = "summary-box status-msg";
    summary.innerHTML = "エラー: 残り椅子を1つ以上選択してください";
    return;
  }

  const attackerPoints = parseInt(document.getElementById("attacker_points").value, 10);
  const defenderPoints = parseInt(document.getElementById("defender_points").value, 10);
  const attackerShocks = parseInt(document.getElementById("attacker_shocks").value, 10);
  const defenderShocks = parseInt(document.getElementById("defender_shocks").value, 10);
  const chairMask = computeChairMask();

  const stateKey = computeStateKey(attackerPoints, defenderPoints, attackerShocks, defenderShocks, chairMask);
  const result = await lookupState(stateKey);

  if (!result) {
    summary.className = "summary-box status-msg";
    summary.innerHTML = "この状態はデータに含まれていません。";
    fillTable("attacker-table", []);
    fillTable("defender-table", []);
    return;
  }

  const roundNum = deriveRoundNum(attackerShocks, defenderShocks, chairMask);
  const normalizedAdvantage = Math.max(-2, Math.min(2, result.sv)) / 2;
  const attackerRate = Math.round(50 + normalizedAdvantage * 50);
  const defenderRate = 100 - attackerRate;

  summary.className = "summary-box";
  summary.innerHTML = `
    <div class="win-rate-display">
      <div class="win-rate-header">第${roundNum}ラウンド時点での優勢度</div>
      <div class="win-rate-bar-wrap">
        <span class="win-rate-label attacker">座る側</span>
        <div class="win-rate-bar">
          <div class="win-rate-fill attacker" style="width: ${attackerRate}%"></div>
          <div class="win-rate-fill defender" style="width: ${defenderRate}%"></div>
          <div class="win-rate-center"></div>
        </div>
        <span class="win-rate-label defender">仕掛ける側</span>
      </div>
      <div class="win-rate-values">
        <span class="attacker">${attackerRate}%</span>
        <span class="defender">${defenderRate}%</span>
      </div>
    </div>
  `;

  fillTable("attacker-table", result.a);
  fillTable("defender-table", result.d);
}

window.addEventListener("DOMContentLoaded", () => {
  document.getElementById("lookup-form").addEventListener("submit", onSubmit);
  setupRange("attacker_points", "attacker_points_value");
  setupRange("defender_points", "defender_points_value");
  setupToggleButtons();
  setupSwapSides();
  setupQuickChairActions();
  renderChairButtons();

  loadManifest()
    .then((meta) => {
      const summary = document.getElementById("summary");
      summary.className = "summary-box status-msg";
      summary.textContent = `SQLite準備完了（${Number(meta.rows).toLocaleString()}件 / ${meta.shards} shard）`;
      updateDatasetStats(meta);
    })
    .catch((err) => {
    const summary = document.getElementById("summary");
    summary.className = "summary-box status-msg";
      summary.textContent = `SQLite初期化エラー: ${err}`;
      const datasetStats = document.getElementById("dataset-stats");
      if (datasetStats) {
        datasetStats.textContent = "データ件数: 読み込み失敗";
      }
    });
});
