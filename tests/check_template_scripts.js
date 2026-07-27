const fs = require("fs");
const path = require("path");

const templates = ["index.html", "settings.html", "beta.html", "size_wizard.html"];
let checked = 0;

for (const name of templates) {
  const file = path.join(__dirname, "..", "webui", "app", "templates", name);
  const html = fs.readFileSync(file, "utf8");
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
  scripts.forEach((match, index) => {
    const source = match[1].replace(/\{\{[\s\S]*?\}\}/g, "null");
    if (!source.trim()) return;
    try {
      new Function(source);
      checked += 1;
    } catch (error) {
      throw new Error(`${name} inline script ${index + 1}: ${error.message}`);
    }
  });
}

console.log(`Checked ${checked} inline template scripts.`);
