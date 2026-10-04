import { execSync } from "child_process";
import { readFileSync, readdirSync, statSync } from "fs";
import path from "path";
import { NextResponse } from "next/server";
import statusData from "@/data/localmesh-status.json";

export const dynamic = "force-dynamic";

/**
 * LocalMesh progress API.
 *
 * Serves the curated milestone/WP snapshot plus LIVE repository stats
 * (Python LOC, file counts, git HEAD) read from disk at request time.
 * One-way data flow only: the LocalMesh Python monorepo never imports from
 * this Next.js app (sandbox boundary, see worklog.md).
 */

function walkPyFiles(dir: string, acc: string[] = []): string[] {
  let entries: ReturnType<typeof readdirSync>;
  try {
    entries = readdirSync(dir);
  } catch {
    return acc;
  }
  for (const entry of entries) {
    if (entry === ".venv" || entry === "__pycache__" || entry.startsWith(".")) continue;
    const full = path.join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) walkPyFiles(full, acc);
    else if (entry.endsWith(".py")) acc.push(full);
  }
  return acc;
}

function countLines(files: string[]): number {
  return files.reduce((sum, f) => {
    try {
      return sum + readFileSync(f, "utf-8").split("\n").length;
    } catch {
      return sum;
    }
  }, 0);
}

function gitHead(): { hash: string; subject: string; date: string } {
  try {
    const hash = execSync("git rev-parse --short HEAD").toString().trim();
    const subject = execSync("git log -1 --format=%s").toString().trim();
    const date = execSync("git log -1 --format=%ci").toString().trim();
    return { hash, subject, date };
  } catch {
    return { hash: "unknown", subject: "git unavailable", date: "" };
  }
}

export async function GET() {
  const agentSrc = path.join(process.cwd(), "agent", "src");
  const agentTests = path.join(process.cwd(), "agent", "tests");
  const fakeBackends = path.join(process.cwd(), "tools", "fake-backends");

  const srcFiles = walkPyFiles(agentSrc);
  const testFiles = [
    ...walkPyFiles(agentTests),
    ...walkPyFiles(fakeBackends).filter((f) => f.includes("tests")),
  ];
  const fakeFiles = walkPyFiles(fakeBackends).filter((f) => !f.includes("tests"));

  let openQuestions = 0;
  try {
    const oq = readFileSync(
      path.join(process.cwd(), "docs", "OPEN_QUESTIONS.md"),
      "utf-8"
    );
    openQuestions = (oq.match(/^## QUESTION-\d+/gm) || []).length;
  } catch {
    openQuestions = 0;
  }

  return NextResponse.json({
    ...statusData,
    live: {
      git: gitHead(),
      stats: {
        agentSrcFiles: srcFiles.length,
        agentSrcLoc: countLines(srcFiles),
        testFiles: testFiles.length,
        fakeBackendFiles: fakeFiles.length,
        openQuestionEntries: openQuestions,
      },
    },
  });
}
