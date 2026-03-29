// Chunked JSON-based lookup for GitHub Pages (full data)
let indexData = null;
let loadedChunks = {}; // { chunkFileName: data }
let indexLoading = false;
let indexLoaded = false;

const allChairs = Array.from({ length: 12 }, (_, i) => i + 1);
const selectedChairs = new Set(allChairs);

// Load index file
async function loadIndex() {
  if (indexLoaded || indexLoading) return;
  indexLoading = true;

  try {
    const res = await fetch("data/index.json");
    indexData = await res.json();
    indexLoaded = true;
    console.log(`Index loaded: ${indexData.total} entries in ${indexData.chunks} chunks`);
  } catch (err) {
    console.error("Index load error:", err);
    indexLoading = false;
  }
}

// Find which chunk contains the state_key
function findChunkForKey(stateKey) {
  if (!indexData) return null;
  for (const range of indexData.ranges) {
    if (stateKey >= range.min_key && stateKey <= range.max_key) {
      return range.file;
    }
  }
  return null;
}

// Load a chunk file
async function loadChunk(fileName) {
  if (loadedChunks[fileName]) return loadedChunks[fileName];

  const res = await fetch(`data/${fileName}`);
  const data = await res.json();
  loadedChunks[fileName] = data;
  console.log(`Loaded chunk: ${fileName} (${Object.keys(data).length} entries)`);
  return data;
}

// Lookup state from chunks
async function lookupState(stateKey) {
  const chunkFile = findChunkForKey(stateKey);
  if (!chunkFile) return null;

  const chunkData = await loadChunk(chunkFile);
  return chunkData[String(stateKey)] || null;
}

// Compute state_key from inputs (bit-packed)
// Bit layout: ap(6) | dp(6) | as(2) | ds(2) | cm(12) = 28 bits
function computeStateKey(attackerPoints, defenderPoints, attackerShocks, defenderShocks, chairMask) {
  return (
    (attackerPoints << 22) |
    (defenderPoints << 16) |
    (attackerShocks << 14) |
    (defenderShocks << 12) |
    chairMask
  );
}

// Compute chair_mask from selected chairs
function computeChairMask() {
  let mask = 0;
  for (const chair of selectedChairs) {
    mask |= 1 << (chair - 1);
  }
  return mask;
}

// Derive round number from state
function deriveRoundNum(attackerShocks, defenderShocks, chairMask) {
  const totalShocks = attackerShocks + defenderShocks;
  const chairCount = countBits(chairMask);
  const removedChairs = 12 - chairCount;
  return totalShocks + removedChairs + 1;
}

function countBits(n) {
  let count = 0;
  while (n) {
    count += n & 1;
    n >>= 1;
  }
  return count;
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

async function onSubmit(event) {
  event.preventDefault();
  const summary = document.getElementById("summary");

  if (selectedChairs.size === 0) {
    summary.className = "summary-box status-msg";
    summary.innerHTML = "エラー: 残り椅子を1つ以上選択してください";
    return;
  }

  if (!indexLoaded) {
    await loadIndex();
    if (!indexLoaded) return;
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

  // Derive round_num
  const roundNum = deriveRoundNum(result.as, result.ds, result.cm);

  // state_value を勝率風に変換
  const stateValue = Number(result.sv);
  const normalizedAdvantage = Math.max(-2, Math.min(2, stateValue)) / 2;
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
  setupQuickChairActions();
  renderChairButtons();

  // Start loading index in background
  loadIndex();
});
