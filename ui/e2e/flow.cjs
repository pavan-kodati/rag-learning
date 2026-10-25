// Browser end-to-end test: a user creates a matter, uploads two batches of documents, and reads the results.
// Run against a running stack:  BASE_URL=http://localhost:8000 node e2e/flow.cjs   (set SHOTS=dir to save screenshots)
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.BASE_URL || "http://localhost:8000";
const DATA = path.resolve(__dirname, "../../data/synthetic/M2");
const SHOTS = process.env.SHOTS;
let step = 0;
const log = (m) => console.log(`  ✓ ${m}`);
const must = (cond, msg) => { if (!cond) throw new Error(`ASSERTION FAILED: ${msg}`); };

async function shot(page, name) {
  if (SHOTS) { fs.mkdirSync(SHOTS, { recursive: true }); await page.screenshot({ path: path.join(SHOTS, `${String(++step).padStart(2, "0")}-${name}.png`), fullPage: false }); }
}

async function uploadAndCommit(page, batchDir, batchNo) {
  const files = fs.readdirSync(batchDir).filter((f) => f.endsWith(".pdf")).sort().map((f) => path.join(batchDir, f));
  await page.getByRole("button", { name: /Start first batch|New batch/ }).click();
  await page.getByTestId("file-input").setInputFiles(files);
  await page.getByRole("button", { name: /^Upload \d+ file/ }).click();
  await page.getByText(/file\(s\) uploaded\./).waitFor();
  await page.getByRole("button", { name: "Commit batch" }).click();
  await page.locator(".card", { hasText: `Batch ${batchNo}` }).locator(".badge", { hasText: /^committed$/i }).first().waitFor({ timeout: 90000 });
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(`console: ${m.text()}`); });

  await page.goto(BASE);
  await page.getByText("Select or create a matter").waitFor();
  await page.getByText("Demo mode.").waitFor();
  await shot(page, "empty-workspace");
  log("empty workspace and demo-mode banner");

  // ---- create the matter -------------------------------------------------------------------------------
  await page.getByRole("button", { name: "+ New matter" }).click();
  await page.getByLabel("Case number").fill("CS(COMM) 412/2025");
  await page.getByLabel("Title").fill("Vardhan Infotech v Kestrel");
  await page.getByLabel("Forum (optional)").fill("High Court of Delhi");
  await shot(page, "new-matter");
  await page.getByRole("button", { name: "Create matter" }).click();
  await page.getByText("No documents yet").first().waitFor();
  log("matter created; lands on Documents");

  // ---- batch 1 -------------------------------------------------------------------------------------------
  await uploadAndCommit(page, path.join(DATA, "batch1"), 1);
  await shot(page, "batch1-committed");
  log("batch 1: 5 files uploaded, processed and committed");
  await page.getByRole("tab", { name: "Position" }).click();
  await page.getByText("Contract terms").waitFor();
  must(await page.locator(".sentence.CURRENT .stext", { hasText: "Contract value (MSA-2023): ₹48,00,000" }).count() === 1, "contract value shown");
  must(await page.locator(".sentence.CURRENT .stext", { hasText: "Delivery / completion date (MSA-2023): 30 Jun 2024" }).count() === 1, "delivery date 30 Jun 2024 is current in batch 1");
  must(await page.getByText("15 Aug 2024").count() === 0, "e-mail proposals are not presented as current");
  await shot(page, "position-batch1");
  log("position after batch 1");

  // click-to-source with highlight
  await page.getByRole("button", { name: /Open source: Master Services Agreement, p.1/ }).first().click();
  await page.getByTestId("highlight").first().waitFor();
  must(await page.getByAltText(/Master Services Agreement, page 1/).isVisible(), "page image visible");
  must((await page.getByTestId("highlight").count()) >= 1, "quote highlighted on the page");
  await shot(page, "source-viewer-highlight");
  await page.getByRole("button", { name: "Close source viewer" }).click();
  log("click-to-source shows the page with the cited quote highlighted");

  // ---- batch 2 ---------------------------------------------------------------------------------------------
  await page.getByRole("tab", { name: "Documents" }).click();
  await uploadAndCommit(page, path.join(DATA, "batch2"), 2);
  must(await page.getByText(/Duplicates skipped: 07b_Bank_statement_duplicate.pdf/).count() === 1, "duplicate listed");
  log("batch 2: uploaded and committed; the duplicate was skipped and listed");

  await page.getByRole("tab", { name: "What changed" }).click();
  await page.getByText("documents processed").first().waitFor();
  const changes = await page.locator(".change").allInnerTexts();
  must(changes.some((c) => /Superseded/i.test(c) && /31 Jul 2024/.test(c)), "SUPERSEDED delivery date in report");
  must(changes.some((c) => /Narrowed/i.test(c) && /12,40,000/.test(c)), "NARROWED outstanding amount in report");
  must(changes.some((c) => /Disputed/i.test(c)), "DISPUTED notice in report");
  await shot(page, "what-changed-batch2");
  log("What-Changed report: superseded, narrowed and disputed items with sources");

  await page.getByRole("tab", { name: "Position" }).click();
  await page.getByText("No longer valid (").waitFor();
  must(await page.locator(".sentence.CURRENT .stext", { hasText: "Delivery / completion date (MSA-2023): 31 Jul 2024" }).count() === 1, "delivery date now 31 Jul 2024");
  must(await page.locator(".sentence.CURRENT .stext", { hasText: "30 Jun 2024" }).count() === 0, "the old delivery date is not shown as current");
  must(await page.locator(".sentence.CURRENT .stext", { hasText: "Outstanding on INV-014: ₹12,40,000" }).count() === 1, "outstanding now 12,40,000");
  must(await page.locator(".sentence.CURRENT .stext", { hasText: "Outstanding on INV-014: ₹18,40,000" }).count() === 0, "the pleaded figure is not current");
  must(await page.getByText(/2 point\(s\) are disputed/).isVisible(), "dispute callout");
  await shot(page, "position-batch2");
  log("position after batch 2 uses only current facts; earlier understanding is listed as no longer valid");

  await page.getByLabel("View as of").selectOption("1");
  await page.getByText("Showing what the system understood after batch 1").waitFor();
  must(await page.locator(".sentence.CURRENT .stext", { hasText: "Delivery / completion date (MSA-2023): 30 Jun 2024" }).count() === 1, "as-of batch 1 view restores the old value");
  await page.getByLabel("View as of").selectOption("2");
  log("as-of selector reproduces the earlier state");

  // ---- chronology, claims, directions ------------------------------------------------------------------------
  await page.getByRole("tab", { name: "Chronology" }).click();
  await page.locator(".tl-item.SUPERSEDED").first().waitFor();
  await shot(page, "chronology");
  await page.getByRole("tab", { name: "Claims & evidence" }).click();
  await page.getByRole("heading", { name: "Kestrel Limited" }).waitFor();
  await shot(page, "claims-board");
  await page.getByLabel("Today").fill("2025-10-20");
  await page.getByRole("tab", { name: "Directions" }).click();
  await page.getByText("10 Oct 2025").first().waitFor();
  must(await page.locator(".due.OVERDUE").count() >= 1, "replication deadline is overdue on 20 Oct 2025");
  await shot(page, "directions");
  log("chronology (struck-through superseded items), claims board, directions with computed deadlines");

  // ---- ask ---------------------------------------------------------------------------------------------------
  await page.getByRole("tab", { name: "Ask" }).click();
  await page.getByLabel("Question").fill("How much is still unpaid on INV-014?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText(/Outstanding on INV-014: ₹12,40,000/).first().waitFor();
  await shot(page, "ask-unpaid");
  await page.getByLabel("Question").fill("What colour is the Defendant's office building?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText("Not found.").waitFor();
  log("grounded answer with a source; an unanswerable question says 'not found'");

  await page.getByRole("tab", { name: "Legal research" }).click();
  await page.getByLabel("Legal question").fill("liquidated damages penalty");
  await page.getByRole("button", { name: "Search authorities" }).click();
  await page.getByText(/Indian Contract Act, 1872, s\.74/).first().waitFor();
  await shot(page, "legal-research");
  log("legal research returns authorities flagged as unverified text");

  // ---- hearing brief -----------------------------------------------------------------------------------------
  await page.getByRole("tab", { name: "Hearing brief" }).click();
  await page.getByRole("button", { name: "Prepare hearing brief" }).click();
  await page.getByRole("heading", { name: "8. Open risks and to-do" }).waitFor();
  must((await page.locator(".brief h2").count()) >= 8, "all eight brief sections");
  must(await page.getByText(/OVERDUE:/).count() >= 1, "overdue risk flagged");
  await shot(page, "hearing-brief");
  log("hearing brief with all eight sections");

  await page.getByRole("tab", { name: "Review" }).click();
  await shot(page, "review");

  must(errors.length === 0, `browser errors: ${errors.join(" | ")}`);
  await browser.close();
  console.log("\nBROWSER E2E PASSED");
})().catch((e) => { console.error("\nBROWSER E2E FAILED:", e.message); process.exit(1); });
