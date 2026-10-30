#!/usr/bin/env node
// Render mermaid (stdin or file arg) as terminal text. Usage: mmd-ascii [file] [--ascii]
import { readFileSync } from 'node:fs';
import { renderMermaidASCII } from 'beautiful-mermaid';

const args = process.argv.slice(2);
const useAscii = args.includes('--ascii');
const file = args.find((a) => !a.startsWith('--'));
const source = readFileSync(file ?? 0, 'utf8');

try {
  console.log(renderMermaidASCII(source, { useAscii }));
} catch (err) {
  process.stderr.write(`mmd-ascii: ${err.message}\n`);
  process.exit(1);
}
