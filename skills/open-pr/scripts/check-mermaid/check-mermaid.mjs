// Parse every fenced `mermaid` block in a Markdown file with the pinned Mermaid version.
// Usage: node check-mermaid.mjs <file.md | ->
// Exit 0 when every block parses, 1 when a block fails, 2 on a usage or setup error.
// Run it through ../check-mermaid.sh, which installs the pinned packages first.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const USAGE = "usage: check-mermaid.sh <file.md | ->";
const ERROR_LINES = 4;

function fail(message, code = 2) {
  process.stderr.write(`check-mermaid: ${message}\n`);
  process.exit(code);
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    fail(`cannot read ${path}: ${error.message}`);
  }
}

function countNewlines(text) {
  return text.split("\n").length - 1;
}

// Push {line, text} for each fenced code token whose info string starts with "mermaid".
// marked gives no positions, so the line comes from the newlines in the raw text before each token.
// Every token's raw starts on the line where it starts, and the raw texts of siblings join to their
// parent's text. List items and blockquotes keep their newlines when marked strips the markers.
function collectMermaidBlocks(tokens, firstLine, blocks) {
  let line = firstLine;
  for (const token of tokens) {
    if (token.type === "code" && token.codeBlockStyle !== "indented") {
      const language = (token.lang ?? "").trim().split(/\s+/)[0].toLowerCase();
      const leadingBlankLines = countNewlines(/^(?:[ \t]*\n)*/.exec(token.raw)[0]);
      if (language === "mermaid") blocks.push({ line: line + leadingBlankLines, text: token.text });
    } else if (token.type === "list") {
      let itemLine = line;
      for (const item of token.items) {
        collectMermaidBlocks(item.tokens, itemLine, blocks);
        itemLine += countNewlines(item.raw);
      }
    } else if (token.type === "blockquote") {
      collectMermaidBlocks(token.tokens, line, blocks);
    }
    line += countNewlines(token.raw);
  }
  return blocks;
}

// Return [{line, text}] for each mermaid fence that GitHub renders, at any list or quote depth.
// The marked lexer applies the GFM block rules, so indented code and fences inside fences are code.
function findMermaidBlocks(markdown, Lexer) {
  return collectMermaidBlocks(new Lexer({ gfm: true }).lex(markdown), 1, []);
}

const args = process.argv.slice(2);
if (args.length !== 1 || args[0] === "") fail(USAGE);

let markdown;
try {
  markdown = readFileSync(args[0] === "-" ? 0 : args[0], "utf8");
} catch (error) {
  fail(`cannot read ${args[0]}: ${error.message}`);
}

const pins = readJson(join(HERE, "package.json")).dependencies;
for (const [name, pinned] of Object.entries(pins)) {
  const got = readJson(join(HERE, "node_modules", name, "package.json")).version;
  if (got !== pinned) fail(`installed ${name} ${got} does not match the pinned ${pinned}. Run: cd ${HERE} && npm ci`);
}
const installed = pins.mermaid;

// Mermaid may log while it parses. Send every console call to stderr so stdout holds only the summary.
for (const method of ["log", "info", "debug", "warn"]) console[method] = (...parts) => console.error(...parts);

// Mermaid needs a DOM (DOMPurify) before it is imported, or classDef fails with "DOMPurify.addHook".
const { JSDOM } = await import("jsdom");
const { window } = new JSDOM("");
globalThis.window = window;
globalThis.document = window.document;
const { default: mermaid } = await import("mermaid");
mermaid.initialize({ startOnLoad: false, logLevel: "fatal" });

const { Lexer } = await import("marked");
const blocks = findMermaidBlocks(markdown, Lexer);
let failures = 0;
for (const [index, block] of blocks.entries()) {
  try {
    await mermaid.parse(block.text);
  } catch (error) {
    failures += 1;
    const message = String(error?.message ?? error).trim();
    const [first, ...rest] = message.split("\n").slice(0, ERROR_LINES);
    const detail = rest.map((line) => `\n  ${line}`).join("");
    process.stderr.write(`block ${index + 1} (line ${block.line}): ${first}${detail}\n`);
  }
}
window.close();

if (failures > 0) {
  process.stderr.write(`mermaid ${installed}: ${failures} of ${blocks.length} blocks failed to parse\n`);
  process.exitCode = 1;
} else if (blocks.length === 0) {
  process.stdout.write(`mermaid ${installed}: no mermaid blocks\n`);
} else {
  const noun = blocks.length === 1 ? "block" : "blocks";
  process.stdout.write(`mermaid ${installed}: ${blocks.length} ${noun} parsed\n`);
}
