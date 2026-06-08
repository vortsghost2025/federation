#!/usr/bin/env node
const fs = require("fs");
const p = process.argv[2];
const d = JSON.parse(fs.readFileSync(p, "utf8"));
const n = d.nvidia;
if (!n) { console.log("NO NVIDIA SECTION"); process.exit(1); }
let l = [];
l.push("=== NVIDIA PROVIDER ===");
l.push("ENV: " + (n.env ? n.env.join(", ") : ""));
l.push("API: " + (n.api || ""));
l.push("");
l.push("=== NVIDIA MODELS WITH tool_call=true ===");
for (const [k, m] of Object.entries(n.models)) {
  if (m.tool_call === true) {
    l.push(k + " | ctx=" + m.limit.context + " | out=" + m.limit.output + " | cost_in=" + m.cost.input + " | cost_out=" + m.cost.output + " | reasoning=" + m.reasoning);
  }
}
fs.writeFileSync("S:/federation/tmp_nvidia.txt", l.join("\n") + "\n", "utf8");
console.log("WRITTEN");
