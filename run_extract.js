const fs = require("fs");
const d = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const n = d.nvidia;
if (!n) { process.exit(1); }
let l = [];
l.push("=== NVIDIA PROVIDER ===");
l.push("ENV: " + (n.env ? n.env.join(", ") : ""));
l.push("API: " + (n.api || ""));
l.push("");
l.push("=== NVIDIA MODELS WITH tool_call=true ===");
const keys = Object.keys(n.models);
for (let i = 0; i < keys.length; i++) {
  const k = keys[i];
  const m = n.models[k];
  if (m.tool_call === true) {
    l.push(k + " | ctx=" + m.limit.context + " | out=" + m.limit.output + " | cost_in=" + m.cost.input + " | cost_out=" + m.cost.output + " | reasoning=" + m.reasoning);
  }
}
fs.writeFileSync("S:/federation/tmp_nvidia.txt", l.join("\n") + "\n", "utf8");
