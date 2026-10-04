"use client";

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  BadgeCheck,
  Ban,
  CheckCircle2,
  CircleDashed,
  Clock,
  FileCode2,
  FlaskConical,
  GitCommitHorizontal,
  GitBranch,
  Loader2,
  ScanSearch,
  ShieldCheck,
  Timer,
  TriangleAlert,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";

interface Milestone {
  id: string;
  name: string;
  status: "done" | "in-progress" | "next" | "planned";
  detail: string;
}
interface WorkPackage {
  id: string;
  title: string;
  milestone: string;
  status: "done" | "in-progress" | "next" | "planned";
  reqs: string[];
  commit: string | null;
}
interface Gate {
  name: string;
  result: "pass" | "skip-announced" | "vacuous-pass";
  detail?: string;
  ref: string;
}
interface OpenQuestion {
  id: string;
  title: string;
  status: string;
  impact: string;
}
interface StatusPayload {
  project: string;
  governingSpec: string;
  updatedAt: string;
  milestones: Milestone[];
  workPackages: WorkPackage[];
  gates: Gate[];
  openQuestions: OpenQuestion[];
  nextSteps: string[];
  live: {
    git: { hash: string; subject: string; date: string };
    stats: {
      agentSrcFiles: number;
      agentSrcLoc: number;
      testFiles: number;
      fakeBackendFiles: number;
      openQuestionEntries: number;
    };
  };
}

function StatusBadge({ status }: { status: string }) {
  if (status === "done")
    return (
      <Badge className="gap-1 border-emerald-500/30 bg-emerald-500/15 text-emerald-600 transition-colors hover:bg-emerald-500/25 dark:text-emerald-400">
        <CheckCircle2 className="h-3 w-3" /> done
      </Badge>
    );
  if (status === "in-progress")
    return (
      <Badge className="gap-1 border-amber-500/30 bg-amber-500/15 text-amber-600 dark:text-amber-400">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60 motion-reduce:hidden" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
        </span>
        in progress
      </Badge>
    );
  if (status === "next")
    return (
      <Badge className="gap-1 border-amber-500/30 bg-amber-500/15 text-amber-600 transition-colors hover:bg-amber-500/25 dark:text-amber-400">
        <Timer className="h-3 w-3" /> next
      </Badge>
    );
  return (
    <Badge variant="outline" className="gap-1 text-muted-foreground">
      <CircleDashed className="h-3 w-3" /> planned
    </Badge>
  );
}

function GateBadge({ result }: { result: string }) {
  if (result === "pass")
    return (
      <Badge className="gap-1 border-emerald-500/30 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
        <ShieldCheck className="h-3 w-3" /> pass
      </Badge>
    );
  if (result === "vacuous-pass")
    return (
      <Badge variant="outline" className="gap-1 text-muted-foreground">
        <BadgeCheck className="h-3 w-3" /> vacuous pass
      </Badge>
    );
  return (
    <Badge className="gap-1 border-amber-500/30 bg-amber-500/15 text-amber-600 dark:text-amber-400">
      <TriangleAlert className="h-3 w-3" /> announced skip
    </Badge>
  );
}

export default function Home() {
  const [data, setData] = useState<StatusPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetch("/api/localmesh/status")
      .then((r) => {
        if (!r.ok) throw new Error(`status ${r.status}`);
        return r.json();
      })
      .then((d: StatusPayload) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const doneMilestones =
    data?.milestones.filter((m) => m.status === "done").length ?? 0;

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <motion.header
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="mb-8"
        >
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-widest text-muted-foreground">
                <Activity className="h-3.5 w-3.5" /> milestone tracker
              </p>
              <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
                LocalMesh AI
              </h1>
              <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
                Privacy-first, cross-device AI mesh. Desktop Agent + Android App
                over a zero-cost private network — built to the{" "}
                <span className="font-medium text-foreground">
                  LM-ARCH-001
                </span>{" "}
                specification.
              </p>
            </div>
            <div className="flex flex-col items-start gap-2 sm:items-end">
              {data ? (
                <>
                  <Badge variant="outline" className="gap-1.5 font-mono text-xs">
                    <GitCommitHorizontal className="h-3.5 w-3.5" />
                    {data.live.git.hash}
                  </Badge>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={load}
                    className="gap-1.5 transition-all hover:gap-2.5 focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <ScanSearch className="h-3.5 w-3.5" /> Refresh
                  </Button>
                </>
              ) : (
                <Skeleton className="h-6 w-24" />
              )}
            </div>
          </div>
          <div className="mt-6">
            <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
              <span>Milestone progress (M0–M9)</span>
              <span>
                {doneMilestones} / {data?.milestones.length ?? 10} complete
              </span>
            </div>
            <Progress
              value={
                data ? (doneMilestones / data.milestones.length) * 100 : 20
              }
              className="h-2"
            />
          </div>
        </motion.header>

        {error && (
          <Card className="mb-8 border-destructive/40">
            <CardContent className="flex items-center gap-2 p-4 text-sm text-destructive">
              <TriangleAlert className="h-4 w-4" /> Failed to load status: {error}
            </CardContent>
          </Card>
        )}

        {!data && !error && (
          <div className="grid gap-6 md:grid-cols-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-44 rounded-xl" />
            ))}
          </div>
        )}

        {data && (
          <div className="space-y-8">
            {/* Milestone strip */}
            <motion.section
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.05 }}
            >
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Roadmap (§22.1 scope fence)
              </h2>
              <div className="flex flex-wrap gap-2">
                {data.milestones.map((m) => (
                  <div
                    key={m.id}
                    title={m.detail}
                    className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                      m.status === "done"
                        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 dark:text-emerald-400"
                        : m.status === "in-progress"
                          ? "border-amber-500/40 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 dark:text-amber-400"
                          : m.status === "next"
                            ? "border-amber-500/40 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 dark:text-amber-400"
                            : "border-border text-muted-foreground hover:border-muted-foreground/40"
                    }`}
                  >
                    {m.status === "done" ? (
                      <CheckCircle2 className="h-3.5 w-3.5" />
                    ) : m.status === "in-progress" || m.status === "next" ? (
                      <Clock className="h-3.5 w-3.5" />
                    ) : (
                      <CircleDashed className="h-3.5 w-3.5" />
                    )}
                    <span className="font-semibold">{m.id}</span>
                    <span className="hidden sm:inline">{m.name}</span>
                  </div>
                ))}
              </div>
            </motion.section>

            <div className="grid gap-6 lg:grid-cols-5">
              {/* Work packages */}
              <motion.section
                className="lg:col-span-3"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.1 }}
              >
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  Work packages (§22.2)
                </h2>
                <ScrollArea className="h-[26rem] rounded-xl border">
                  <div className="divide-y divide-border">
                    {data.workPackages.map((wp) => (
                      <div
                        key={wp.id}
                        className="flex items-start justify-between gap-3 p-4 transition-colors hover:bg-muted/40"
                      >
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-xs font-semibold text-foreground">
                              {wp.id}
                            </span>
                            <Badge
                              variant="secondary"
                              className="px-1.5 py-0 text-[10px]"
                            >
                              {wp.milestone}
                            </Badge>
                            {wp.commit && (
                              <span className="font-mono text-[10px] text-muted-foreground">
                                {wp.commit}
                              </span>
                            )}
                          </div>
                          <p className="mt-1 text-sm leading-snug text-foreground">
                            {wp.title}
                          </p>
                          <p className="mt-1 flex flex-wrap gap-1">
                            {wp.reqs.map((r) => (
                              <span
                                key={r}
                                className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                              >
                                {r}
                              </span>
                            ))}
                          </p>
                        </div>
                        <StatusBadge status={wp.status} />
                      </div>
                    ))}
                  </div>
                </ScrollArea>
              </motion.section>

              {/* Quality gates */}
              <motion.section
                className="lg:col-span-2"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.15 }}
              >
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  CI-equivalent gate (§21.4)
                </h2>
                <Card>
                  <CardContent className="p-0">
                    <div className="divide-y divide-border">
                      {data.gates.map((g) => (
                        <div
                          key={g.name}
                          className="flex items-center justify-between gap-2 px-4 py-2.5"
                        >
                          <div className="min-w-0">
                            <p className="truncate text-xs font-medium text-foreground">
                              {g.name}
                            </p>
                            {g.detail && (
                              <p className="truncate text-[10px] text-muted-foreground">
                                {g.detail}
                              </p>
                            )}
                          </div>
                          <GateBadge result={g.result} />
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.section>
            </div>

            <div className="grid gap-6 lg:grid-cols-5">
              {/* Owner actions / open questions */}
              <motion.section
                className="lg:col-span-3"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.2 }}
              >
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  Open questions &amp; owner actions (§24)
                </h2>
                <div className="space-y-3">
                  {data.openQuestions.map((q) => (
                    <Card key={q.id} className="border-amber-500/20">
                      <CardContent className="flex items-start gap-3 p-4">
                        {q.status === "BLOCKING" ? (
                          <Ban className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                        ) : (
                          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                        )}
                        <div className="min-w-0">
                          <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-foreground">
                            <span className="font-mono text-xs">{q.id}</span>
                            {q.title}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {q.impact}
                          </p>
                        </div>
                        <Badge
                          variant="outline"
                          className="ml-auto shrink-0 text-[10px] text-amber-600 dark:text-amber-400"
                        >
                          {q.status}
                        </Badge>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </motion.section>

              {/* Live repo stats */}
              <motion.section
                className="lg:col-span-2"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.25 }}
              >
                <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  Repository (live)
                </h2>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <GitBranch className="h-4 w-4" /> main
                    </CardTitle>
                    <CardDescription className="text-xs">
                      {data.live.git.subject}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg border p-3 transition-colors hover:border-muted-foreground/40">
                      <p className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                        <FileCode2 className="h-3 w-3" /> agent src
                      </p>
                      <p className="mt-1 text-lg font-semibold tabular-nums">
                        {data.live.stats.agentSrcLoc.toLocaleString()}
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        LOC · {data.live.stats.agentSrcFiles} files
                      </p>
                    </div>
                    <div className="rounded-lg border p-3 transition-colors hover:border-muted-foreground/40">
                      <p className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                        <FlaskConical className="h-3 w-3" /> tests
                      </p>
                      <p className="mt-1 text-lg font-semibold tabular-nums">
                        {data.live.stats.testFiles}
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        test files · 104 cases
                      </p>
                    </div>
                    <div className="rounded-lg border p-3 transition-colors hover:border-muted-foreground/40">
                      <p className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                        <Activity className="h-3 w-3" /> fake backends
                      </p>
                      <p className="mt-1 text-lg font-semibold tabular-nums">
                        {data.live.stats.fakeBackendFiles}
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        shared test asset files
                      </p>
                    </div>
                    <div className="rounded-lg border p-3 transition-colors hover:border-muted-foreground/40">
                      <p className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                        <TriangleAlert className="h-3 w-3" /> open questions
                      </p>
                      <p className="mt-1 text-lg font-semibold tabular-nums">
                        {data.live.stats.openQuestionEntries}
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        QUESTION-xxx entries
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </motion.section>
            </div>

            {/* Next steps */}
            <motion.section
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.3 }}
            >
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Next milestone — M2 entry (§22.1)
              </h2>
              <Card>
                <CardContent className="p-4">
                  <ol className="space-y-2">
                    {data.nextSteps.map((s, i) => (
                      <li
                        key={i}
                        className="flex items-start gap-3 text-sm text-foreground"
                      >
                        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted font-mono text-[10px] font-semibold text-muted-foreground">
                          {i + 1}
                        </span>
                        {s}
                      </li>
                    ))}
                  </ol>
                </CardContent>
              </Card>
            </motion.section>
          </div>
        )}
      </main>

      <Separator />

      {/* Sticky footer */}
      <footer className="mt-auto border-t bg-background/95 py-4">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-2 px-4 pb-[env(safe-area-inset-bottom)] text-xs text-muted-foreground sm:flex-row sm:px-6 lg:px-8">
          <p>
            LocalMesh AI · governed by{" "}
            <span className="font-medium text-foreground">AGENTS.md</span> +{" "}
            <span className="font-medium text-foreground">LM-ARCH-001</span>{" "}
            (spec wins on conflict)
          </p>
          <p>
            Updated {data?.updatedAt ?? "—"} · dashboard reads repo state
            one-way
          </p>
        </div>
      </footer>
    </div>
  );
}
