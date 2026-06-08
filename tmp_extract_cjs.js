const fs = require("fs");
const path = "C:/Users/seand/AppData/Local/AgentProfiles/kilo-a/cache/kilo/models.json";
const data = JSON.parse(fs.readFileSync(path, "utf8"));
const nvidia = data.nvidia;
let lines = [];
lines.push("=== NVIDIA PROVIDER ===");
lines.push("ENV: " + (nvidia.env ? nvidia.env.join(", ") : ""));
lines.push("API: " + (nvidia.api || ""));
lines.push("");
lines.push("=== NVIDIA MODELS WITH tool_call=true ===");
for (const [name, model] of Object.entries(nvidia.models)) {
  if (model.tool_call === true) {
    lines.push(name + " | ctx=" + model.limit.context + " | out=" + model.limit.output + " | cost_in=" + model.cost.input + " | cost_out=" + model.cost.output + " | reasoning=" + model.reasoning);
  }
}
fs.writeFileSync("S:/federation/tmp_nvidia_output.txt", lines.join("\n") + "\n", "utf8");
