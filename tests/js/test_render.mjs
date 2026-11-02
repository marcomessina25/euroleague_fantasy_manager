import assert from "node:assert";

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderBuyButton(p) {
  return `<button class="btn btn-primary" style="padding:0.2rem 0.5rem; font-size:0.75rem;" data-action="add-trade-in" data-player-id="${p.player_id}" data-player-name="${escapeHtml(p.name)}" data-player-credits="${p.credits}">+ Buy</button>`;
}

let addedPlayer = null;
let scriptExecuted = false;

globalThis.alert = function () {
  scriptExecuted = true;
};

function simulateClick(htmlString) {
  const match = htmlString.match(/data-action="([^"]+)"\s+data-player-id="([^"]+)"\s+data-player-name="([^"]+)"\s+data-player-credits="([^"]+)"/);
  assert(match, "Button must contain required data attributes");
  const [, action, id, name, credits] = match;
  const decodedName = name
    .replace(/&#039;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&gt;/g, '>')
    .replace(/&lt;/g, '<')
    .replace(/&amp;/g, '&');

  if (action === "add-trade-in") {
    addTradeIn(Number(id), decodedName, Number(credits));
  }
}

function addTradeIn(id, name, credits) {
  addedPlayer = { id, name, credits };
}

// 1. Amath M'baye
const p1 = { player_id: 101, name: "Amath M'baye", credits: 11.5 };
const btnHtml1 = renderBuyButton(p1);
assert(!btnHtml1.includes("onclick="), "Button must not contain inline onclick handler");
simulateClick(btnHtml1);
assert.strictEqual(addedPlayer.name, "Amath M'baye");
assert.strictEqual(addedPlayer.id, 101);
assert.strictEqual(addedPlayer.credits, 11.5);
assert.strictEqual(scriptExecuted, false);

// 2. Malicious payload x', alert(1), '
const p2 = { player_id: 102, name: "x', alert(1), '", credits: 9.0 };
const btnHtml2 = renderBuyButton(p2);
assert(!btnHtml2.includes("onclick="), "Button must not contain inline onclick handler");
simulateClick(btnHtml2);
assert.strictEqual(addedPlayer.name, "x', alert(1), '");
assert.strictEqual(addedPlayer.id, 102);
assert.strictEqual(addedPlayer.credits, 9.0);
assert.strictEqual(scriptExecuted, false, "Alert script must never execute");

console.log("All JS render tests passed successfully!");
