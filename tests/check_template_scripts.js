const fs = require("fs");
const path = require("path");

const templates = ["home.html", "index.html", "autopilot.html", "settings.html", "beta.html", "size_wizard.html"];
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

for (const name of ["app.js", "v3.js"]) {
  const file = path.join(__dirname, "..", "webui", "app", "static", name);
  try {
    new Function(fs.readFileSync(file, "utf8"));
    checked += 1;
  } catch (error) {
    throw new Error(`${name}: ${error.message}`);
  }
}

console.log(`Checked ${checked} template and shared scripts.`);
