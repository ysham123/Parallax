/** Parse a unified Git patch without discarding metadata, binary notices, or blank lines. */
export type DiffLine = {
  text: string;
  kind: "addition" | "deletion" | "context" | "hunk" | "meta";
  old?: number;
  next?: number;
};
export type DiffFile = {
  path: string;
  previousPath?: string;
  added: number;
  removed: number;
  lines: DiffLine[];
};
function gitPath(input: string, stripPrefix = true): string {
  let path = input.split("\t")[0];
  if (path.startsWith('"') && path.endsWith('"')) {
    const bytes: number[] = [];
    const content = path.slice(1, -1);
    for (let i = 0; i < content.length; i++) {
      if (content[i] === "\\") {
        const octal = content.slice(i + 1).match(/^[0-7]{1,3}/)?.[0];
        if (octal) {
          bytes.push(parseInt(octal, 8));
          i += octal.length;
          continue;
        }
        const next = content[++i];
        bytes.push(
          ...new TextEncoder().encode(
            (
              {
                n: "\n",
                r: "\r",
                t: "\t",
                b: "\b",
                f: "\f",
                v: "\v",
              } as Record<string, string>
            )[next] ?? next,
          ),
        );
      } else {
        const point = content.codePointAt(i)!;
        bytes.push(...new TextEncoder().encode(String.fromCodePoint(point)));
        if (point > 0xffff) i++;
      }
    }
    path = new TextDecoder().decode(new Uint8Array(bytes));
  }
  return stripPrefix ? path.replace(/^[ab]\//, "") : path;
}
export function parseDiff(patch: string): DiffFile[] {
  if (!patch.trim()) return [];
  const files: DiffFile[] = [];
  let file: DiffFile | undefined,
    old = 0,
    next = 0,
    inHunk = false;
  const lines = patch.split("\n");
  if (lines.at(-1) === "") lines.pop();
  for (const text of lines) {
    if (text.startsWith("diff --git ") || !file) {
      const paths = text.match(
        /^diff --git ("(?:[^"\\]|\\.)*"|.*?) ("(?:[^"\\]|\\.)*"|b\/.*)$/,
      );
      file = {
        path: paths ? gitPath(paths[2]) : "Patch",
        added: 0,
        removed: 0,
        lines: [],
      };
      files.push(file);
      inHunk = false;
    }
    const line: DiffLine = { text, kind: "meta" };
    const hunk = text.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) {
      old = Number(hunk[1]);
      next = Number(hunk[2]);
      inHunk = true;
      line.kind = "hunk";
    } else if (inHunk && text.startsWith("+")) {
      line.kind = "addition";
      line.next = next++;
      file.added++;
    } else if (inHunk && text.startsWith("-")) {
      line.kind = "deletion";
      line.old = old++;
      file.removed++;
    } else if (inHunk && text.startsWith(" ")) {
      line.kind = "context";
      line.old = old++;
      line.next = next++;
    } else if (!inHunk && text.startsWith("+++ ") && text !== "+++ /dev/null") {
      file.path = gitPath(text.slice(4));
    } else if (!inHunk && text.startsWith("--- ") && text !== "--- /dev/null") {
      file.previousPath = gitPath(text.slice(4));
    } else if (text.startsWith("rename to ")) {
      file.path = gitPath(text.slice(10), false);
    } else if (text.startsWith("rename from ")) {
      file.previousPath = gitPath(text.slice(12), false);
    }
    file.lines.push(line);
  }
  return files;
}
