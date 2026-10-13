// Browser acceptance for the verified Parallax candidate in the real Excalidraw editor.
// The scene is built and the feature is used only through visible UI; window.h is read for verification.
import { chromium } from "playwright";
import fs from "node:fs";

const out = process.argv[2];
fs.mkdirSync(out, { recursive: true });
const results = [];
const check = (name, ok, detail) => { results.push({ name, ok, detail }); console.log((ok ? "PASS " : "FAIL ") + name + (detail ? "  " + JSON.stringify(detail) : "")); };

const browser = await chromium.launch({ slowMo: Number(process.env.SLOWMO || 0) });
const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, recordVideo: { dir: out, size: { width: 1280, height: 800 } } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto("http://127.0.0.1:5199/", { waitUntil: "load" });
await page.waitForSelector("canvas.interactive");
await page.waitForFunction(() => window.h && window.h.app);
await page.waitForTimeout(800);

const texts = () => page.evaluate(() => window.h.elements.filter((e) => e.type === "text" && !e.isDeleted)
  .map((e) => ({ id: e.id, text: e.text, original: e.originalText, locked: e.locked, width: Math.round(e.width) }))
  .sort((a, b) => a.id.localeCompare(b.id)));
// Paced recordings hold each checkpoint so a viewer can read it.
const shot = async (name) => { if (process.env.SLOWMO) await page.waitForTimeout(1500); await page.screenshot({ path: `${out}/${name}.png` }); };

async function addText(x, y, value) {
  await page.keyboard.press("t");
  await page.mouse.click(x, y);
  await page.waitForSelector("textarea.excalidraw-wysiwyg");
  await page.keyboard.type(value, { delay: 15 });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
}

await addText(420, 260, "the cat sat");
await addText(420, 340, "black cat, white cat");
await addText(420, 420, "dog");
await addText(420, 500, "locked cat");
await page.keyboard.press("ControlOrMeta+Shift+L"); // lock the last (still selected) text
await page.mouse.click(1000, 700);
const before = await texts();
check("scene built through the UI", before.length === 4 && before.some((t) => t.text === "locked cat" && t.locked), before.map((t) => [t.text, t.locked]));
await shot("01-scene");

await page.keyboard.press("ControlOrMeta+F");
const search = page.locator(".layer-ui__search input");
await search.waitFor();
await search.fill("CAT");
await page.waitForTimeout(700);
const count = await page.locator(".layer-ui__search-count").innerText();
check("case-insensitive search finds every occurrence including the locked one", /^1 \/ 4 results$/.test(count.trim()), count);
const status = await page.locator('.layer-ui__search [role="status"]').innerText();
check("protected results are announced before acting, in the singular", /\b1 protected result\b(?!s)/.test(status), status);
const field = page.getByLabel("Replace with");
check("Replace with field is visible and accessibly named", await field.isVisible());
await field.fill("bird $& $1");
await shot("02-search-and-replacement");
const box = async (locator) => locator.boundingBox();
const fieldBox = await box(field);
const buttons = [await box(page.getByRole("button", { name: "Replace", exact: true })), await box(page.getByRole("button", { name: "Replace all" }))];
const lineHeight = await page.getByRole("button", { name: "Replace all" }).evaluate((el) => parseFloat(getComputedStyle(el).lineHeight) || 20);
check("Replace buttons are single-line and aligned within the panel", buttons.every((b) => b.x >= fieldBox.x - 0.5 && b.x + b.width <= fieldBox.x + fieldBox.width + 0.5 && b.height < lineHeight * 2 + 4 && b.height >= 24), { fieldBox, buttons, lineHeight });

await page.getByRole("button", { name: "Replace all" }).click();
await page.waitForTimeout(500);
const after = await texts();
const byId = Object.fromEntries(after.map((t) => [t.id, t]));
const expected = { "the cat sat": "the bird $& $1 sat", "black cat, white cat": "black bird $& $1, white bird $& $1", "dog": "dog", "locked cat": "locked cat" };
const allOk = before.every((t) => byId[t.id] && byId[t.id].text === expected[t.text] && byId[t.id].original === expected[t.text]);
check("Replace all is literal, keeps element ids, skips the locked text", allOk, after.map((t) => t.text));
check("text geometry was recomputed for grown labels", before.filter((t) => t.text.includes("cat") && !t.locked).every((t) => byId[t.id].width > t.width), after.map((t) => t.width));
check("result is reported with correct plurals", ((t) => /Replaced 3 occurrences\b/.test(t) && !/\b1 protected results\b/.test(t))(await page.locator('.layer-ui__search [role="status"]').innerText()), await page.locator('.layer-ui__search [role="status"]').innerText());
await shot("03-after-replace-all");

await page.keyboard.press("Escape");
await page.mouse.click(1000, 700);
await page.keyboard.press("ControlOrMeta+Z");
await page.waitForTimeout(300);
const undone = await texts();
check("one undo restores the entire previous text content and geometry", JSON.stringify(undone) === JSON.stringify(before), undone.map((t) => [t.text, t.width]));
await shot("04-after-undo");
await page.keyboard.press("ControlOrMeta+Shift+Z");
await page.waitForTimeout(300);
check("one redo restores the replaced content", JSON.stringify(await texts()) === JSON.stringify(after));

// Replace only the focused occurrence.
await page.keyboard.press("ControlOrMeta+Z");
await page.keyboard.press("ControlOrMeta+F");
await search.fill("white cat");
await page.waitForTimeout(700);
await field.fill("white tiger");
await page.getByRole("button", { name: "Replace", exact: true }).click();
await page.waitForTimeout(400);
const single = await texts();
check("single replacement is reported in the singular", /\bReplaced 1 occurrence\b(?!s)/.test((await page.locator('.layer-ui__search [role="status"]').innerText()).trim()), await page.locator('.layer-ui__search [role="status"]').innerText());
check("Replace changes only the focused occurrence", single.filter((t) => t.text === "black cat, white tiger").length === 1 && single.filter((t) => t.text === "the cat sat").length === 1, single.map((t) => t.text));

// Dark mode presentation and view mode refusal.
await page.keyboard.press("Escape");
await page.mouse.click(1000, 700);
await page.keyboard.press("Alt+Shift+D");
await page.keyboard.press("ControlOrMeta+F");
await search.fill("cat");
await page.waitForTimeout(700);
await field.focus();
await shot("05-dark-mode-focus");
await page.keyboard.press("Escape");
await page.mouse.click(1000, 700);
await page.keyboard.press("Alt+R");
await page.waitForTimeout(200);
await page.keyboard.press("ControlOrMeta+F");
await search.fill("cat");
await page.waitForTimeout(700);
const viewCount = await page.locator(".layer-ui__search-count").innerText();
const disabled = await page.getByRole("button", { name: "Replace all" }).isDisabled();
check("search stays available in view mode and replacement is refused", /results?/.test(viewCount) && disabled && await field.isDisabled(), { viewCount, disabled });
await shot("06-view-mode");

check("no uncaught page errors", errors.length === 0, errors.slice(0, 3));
const video = page.video();
await context.close();
await browser.close();
fs.renameSync(await video.path(), `${out}/walkthrough.webm`);
fs.writeFileSync(`${out}/results.json`, JSON.stringify(results, null, 1));
console.log(`${results.filter((r) => r.ok).length}/${results.length} browser checks passed`);
