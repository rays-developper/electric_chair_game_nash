function formatProb(prob) {
  return `${(Number(prob) * 100).toFixed(2)}%`;
}

const allChairs = Array.from({ length: 12 }, (_, index) => index + 1);
const selectedChairs = new Set(allChairs);

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
      if (!target || value === undefined) {
        return;
      }

      document.getElementById(target).value = value;

      const group = button.parentElement;
      if (!group) {
        return;
      }
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

function buildQuery() {
  const attackerPoints = document.getElementById("attacker_points").value;
  const defenderPoints = document.getElementById("defender_points").value;
  const attackerShocks = document.getElementById("attacker_shocks").value;
  const defenderShocks = document.getElementById("defender_shocks").value;
  const chairs = document.getElementById("chairs").value;

  const params = new URLSearchParams({
    attacker_points: attackerPoints,
    defender_points: defenderPoints,
    attacker_shocks: attackerShocks,
    defender_shocks: defenderShocks,
    chairs,
  });
  return `/api/lookup?${params.toString()}`;
}

async function onSubmit(event) {
  event.preventDefault();
  const summary = document.getElementById("summary");
  if (selectedChairs.size === 0) {
    summary.className = "summary-box status-msg";
    summary.innerHTML = "エラー: 残り椅子を1つ以上選択してください";
    return;
  }
  summary.className = "summary-box status-msg";
  summary.innerHTML = "検索中...";

  try {
    const res = await fetch(buildQuery());
    const data = await res.json();

    if (data.error) {
      summary.className = "summary-box status-msg";
      summary.innerHTML = `エラー: ${data.error}`;
      return;
    }

    if (!data.found) {
      summary.className = "summary-box status-msg";
      summary.innerHTML = "初期状態から遷移可能な状態ではありません。入力を確認してください";
      fillTable("attacker-table", []);
      fillTable("defender-table", []);
      return;
    }

    const result = data.result;
    
    // state_value を勝率風に変換（期待値を0-100%に正規化）
    // state_value は座る側の期待得点差。ゲームは拮抗しているため ±2 程度を 50% 中心にマップ
    const stateValue = Number(result.state_value);
    const normalizedAdvantage = Math.max(-2, Math.min(2, stateValue)) / 2; // -1 to 1
    const attackerRate = Math.round(50 + normalizedAdvantage * 50);
    const defenderRate = 100 - attackerRate;
    
    summary.className = "summary-box";
    summary.innerHTML = `
      <div class="win-rate-display">
        <div class="win-rate-header">第${result.round_num}ラウンド時点での優勢度</div>
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

    fillTable("attacker-table", result.attacker_strategy);
    fillTable("defender-table", result.defender_strategy);
  } catch (err) {
    summary.className = "summary-box status-msg";
    summary.innerHTML = `通信エラー: ${err}`;
  }
}

window.addEventListener("DOMContentLoaded", () => {
  document.getElementById("lookup-form").addEventListener("submit", onSubmit);
  setupRange("attacker_points", "attacker_points_value");
  setupRange("defender_points", "defender_points_value");
  setupToggleButtons();
  setupQuickChairActions();
  renderChairButtons();
});
