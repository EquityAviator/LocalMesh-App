"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  BadgeCheck,
  Ban,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  ClipboardCheck,
  Clock,
  Copy,
  FileCode2,
  FlaskConical,
  GitBranch,
  GitCommitHorizontal,
  ScanSearch,
  ShieldCheck,
  Stethoscope,
  Timer,
  TriangleAlert,
  Wifi,
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
  notes?: string;
}
interface Gate {
  name: string;
  result: "pass" | "skip-announced" | "vacuous-pass";
  detail?: string;
  ref: string;
}
interface SecurityTest {
  id: string;
  title: string;
  status: "delivered" | "pending" | "vacuous" | "smoke";
  where: string;
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
  securityTests: SecurityTest[];
  openQuestions: OpenQuestion[];
  nextSteps: string[];
  live: {
    git: { hash: string; subject: string; date: string };
    stats: {
      agentSrcFiles: number;
      agentSrcLoc: number;
      testFiles: number;
      testFunctions: number;
      fakeBackendFiles: number;
      openQuestionEntries: number;
    };
  };
}

type WpFilter = "all" | "done" | "in-progress" | "planned";

const WP_FILTERS: { key: WpFilter; label: string }[] = [
  { key: "all", label: "all" },
  { key: "done", label: "done" },
  { key: "in-progress", label: "in progress" },
  { key: "planned", label: "planned" },
];

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

function SecTestBadge({ status }: { status: string }) {
  if (status === "delivered")
    return (
      <Badge className="shrink-0 gap-1 border-emerald-500/30 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
        <ShieldCheck className="h-3 w-3" /> delivered
      </Badge>
    );
  if (status === "vacuous")
    return (
      <Badge variant="outline" className="shrink-0 gap-1 text-muted-foreground">
        <BadgeCheck className="h-3 w-3" /> vacuous
      </Badge>
    );
  if (status === "smoke")
    return (
      <Badge
        variant="outline"
        className="shrink-0 gap-1 border-amber-500/30 text-amber-600 dark:text-amber-400"
      >
        <FlaskConical className="h-3 w-3" /> smoke
      </Badge>
    );
  return (
    <Badge variant="outline" className="shrink-0 gap-1 text-muted-foreground">
      <CircleDashed className="h-3 w-3" /> pending
    </Badge>
  );
}

const STATUS_ACCENT: Record<string, string> = {
  done: "border-l-emerald-500/60",
  "in-progress": "border-l-amber-500/70",
  next: "border-l-amber-500/40",
  planned: "border-l-border",
};

export default function Home() {
  const [data, setData] = useState<StatusPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());
  const [wpFilter, setWpFilter] = useState<WpFilter>("all");
  const [expandedWp, setExpandedWp] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(() => {
    fetch("/api/localmesh/status")
      .then((r) => {
        if (!r.ok) throw new Error(`status ${r.status}`);
        return r.json();
      })
      .then((d: StatusPayload) => {
        setData(d);
        setError(null);
        setCheckedAt(Date.now());
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // "checked Ns ago" ticker — 5 s cadence, aligned with motion-reduce.
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(t);
  }, []);

  const doneMilestones =
    data?.milestones.filter((m) => m.status === "done").length ?? 0;
  const activeMilestones =
    data?.milestones.filter((m) => m.status === "in-progress").length ?? 0;
  const progressPct = data
    ? (doneMilestones / data.milestones.length) * 100
    : 20;

  const wpCounts = useMemo(() => {
    const counts: Record<WpFilter, number> = {
      all: 0,
      done: 0,
      "in-progress": 0,
      planned: 0,
    };
    for (const wp of data?.workPackages ?? []) {
      counts.all += 1;
      counts[wp.status] = (counts[wp.status] ?? 0) + 1;
    }
    return counts;
  }, [data]);

  const visibleWps = useMemo(() => {
    const list = data?.workPackages ?? [];
    return wpFilter === "all" ? list : list.filter((wp) => wp.status === wpFilter);
  }, [data, wpFilter]);

  const secDelivered = data?.securityTests.filter((t) => t.status === "delivered").length ?? 0;
  const secTotal = data?.securityTests.length ?? 0;

  const agoSeconds =
    checkedAt !== null ? Math.max(0, Math.round((now - checkedAt) / 1000)) : null;

  const copyHash = useCallback(async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.live.git.hash);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable — non-fatal */
    }
  }, [data]);

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
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={copyHash}
                      aria-label={`Copy HEAD hash ${data.live.git.hash}`}
                      title="Copy HEAD hash"
                      className="group inline-flex items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-xs text-muted-foreground transition-all hover:border-muted-foreground/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <GitCommitHorizontal className="h-3.5 w-3.5" />
                      {data.live.git.hash}
                      <span aria-hidden className="opacity-0 transition-opacity group-hover:opacity-100">
                        {copied ? (
                          <Check className="h-3 w-3 text-emerald-500" />
                        ) : (
                          <Copy className="h-3 w-3" />
                        )}
                      </span>
                      <span className="sr-only" role="status">
                        {copied ? "copied" : ""}
                      </span>
                    </button>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={load}
                    className="gap-1.5 transition-all hover:gap-2.5 focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <ScanSearch className="h-3.5 w-3.5" /> Refresh
                  </Button>
                  {agoSeconds !== null && (
                    <p className="text-[10px] text-muted-foreground tabular-nums" role="status">
                      checked {agoSeconds < 60 ? `${agoSeconds}s` : `${Math.round(agoSeconds / 60)}m`} ago
                    </p>
                  )}
                </>
              ) : (
                <Skeleton className="h-6 w-24" />
              )}
            </div>
          </div>
          <div className="mt-6">
            <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground">
              <span className="flex items-center gap-2">
                Milestone progress (M0–M9)
                {activeMilestones > 0 && (
                  <span className="rounded bg-amber-500/10 px-1.5 py-0.5 font-medium text-amber-600 tabular-nums dark:text-amber-400">
                    {activeMilestones} active
                  </span>
                )}
              </span>
              <span className="tabular-nums">
                {doneMilestones} / {data?.milestones.length ?? 10} complete
                {data && (
                  <span className="ml-2 font-medium text-foreground">
                    {Math.round(progressPct)}%
                  </span>
                )}
              </span>
            </div>
            <div className="relative">
              <Progress
                value={progressPct}
                className="h-2 [&>div]:bg-gradient-to-r [&>div]:from-emerald-600 [&>div]:to-emerald-400"
              />
              {data && activeMilestones > 0 && (
                <span
                  aria-hidden
                  className="pointer-events-none absolute inset-y-0 right-0 w-16 rounded-r-full bg-gradient-to-l from-amber-400/40 to-transparent motion-safe:animate-pulse"
                />
              )}
            </div>
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
              aria-labelledby="roadmap-h"
            >
              <h2
                id="roadmap-h"
                className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground"
              >
                Roadmap (§22.1 scope fence)
              </h2>
              <div className="flex flex-wrap gap-2">
                {data.milestones.map((m) => (
                  <div
                    key={m.id}
                    title={m.detail}
                    className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
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
                aria-labelledby="wp-h"
              >
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <h2
                    id="wp-h"
                    className="text-sm font-semibold uppercase tracking-wider text-muted-foreground"
                  >
                    Work packages (§22.2)
                  </h2>
                  <div
                    className="flex flex-wrap gap-1"
                    role="group"
                    aria-label="Filter work packages by status"
                  >
                    {WP_FILTERS.map((f) => (
                      <button
                        key={f.key}
                        type="button"
                        aria-pressed={wpFilter === f.key}
                        onClick={() => setWpFilter(f.key)}
                        className={`rounded-md border px-2 py-0.5 font-mono text-[10px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                          wpFilter === f.key
                            ? "border-foreground/40 bg-foreground/5 font-semibold text-foreground"
                            : "border-transparent text-muted-foreground hover:border-border hover:text-foreground"
                        }`}
                      >
                        {f.label}
                        <span className="ml-1 tabular-nums opacity-60">
                          {wpCounts[f.key] ?? 0}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
                <ScrollArea className="h-[30rem] rounded-xl border">
                  <div className="divide-y divide-border">
                    {visibleWps.map((wp) => {
                      const expanded = expandedWp === wp.id;
                      return (
                        <div
                          key={wp.id}
                          className={`border-l-2 transition-colors ${STATUS_ACCENT[wp.status] ?? "border-l-border"} ${
                            expanded ? "bg-muted/40" : "hover:bg-muted/40"
                          }`}
                        >
                          <button
                            type="button"
                            aria-expanded={expanded}
                            aria-controls={`wp-notes-${wp.id}`}
                            onClick={() => setExpandedWp(expanded ? null : wp.id)}
                            className="flex w-full items-start justify-between gap-3 p-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
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
                            <span className="flex shrink-0 items-center gap-1.5">
                              <StatusBadge status={wp.status} />
                              {wp.notes && (
                                <ChevronDown
                                  aria-hidden
                                  className={`h-3.5 w-3.5 text-muted-foreground transition-transform duration-200 ${
                                    expanded ? "rotate-180" : ""
                                  }`}
                                />
                              )}
                            </span>
                          </button>
                          <AnimatePresence initial={false}>
                            {expanded && wp.notes && (
                              <motion.div
                                id={`wp-notes-${wp.id}`}
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: "auto", opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                transition={{ duration: 0.22, ease: "easeOut" }}
                                className="overflow-hidden"
                              >
                                <p className="border-t border-dashed border-border/70 px-4 py-3 text-xs leading-relaxed text-muted-foreground">
                                  <span className="font-medium text-foreground">
                                    delivery notes ·{" "}
                                  </span>
                                  {wp.notes}
                                </p>
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </div>
                      );
                    })}
                    {visibleWps.length === 0 && (
                      <p className="p-4 text-xs text-muted-foreground">
                        No work packages match this filter.
                      </p>
                    )}
                  </div>
                </ScrollArea>
              </motion.section>

              {/* Quality gates */}
              <motion.section
                className="lg:col-span-2"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.15 }}
                aria-labelledby="gate-h"
              >
                <h2
                  id="gate-h"
                  className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground"
                >
                  CI-equivalent gate (§21.4)
                </h2>
                <Card className="transition-shadow hover:shadow-md">
                  <CardContent className="p-0">
                    <ScrollArea className="h-[30rem]">
                      <div className="divide-y divide-border">
                        {data.gates.map((g) => (
                          <div
                            key={g.name}
                            className="group flex items-center justify-between gap-2 px-4 py-2.5 transition-colors hover:bg-muted/40"
                          >
                            <div className="min-w-0">
                              <p className="truncate text-xs font-medium text-foreground">
                                {g.name}
                              </p>
                              {g.detail && (
                                <p className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-muted-foreground">
                                  {g.detail}
                                </p>
                              )}
                            </div>
                            <div className="flex shrink-0 flex-col items-end gap-1">
                              <GateBadge result={g.result} />
                              <span className="font-mono text-[9px] text-muted-foreground/70 opacity-0 transition-opacity group-hover:opacity-100">
                                {g.ref}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </ScrollArea>
                  </CardContent>
                </Card>
              </motion.section>
            </div>

            <div className="grid gap-6 lg:grid-cols-5">
              {/* Security posture */}
              <motion.section
                className="lg:col-span-3"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.2 }}
                aria-labelledby="sec-h"
              >
                <div className="mb-3 flex items-center justify-between">
                  <h2
                    id="sec-h"
                    className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground"
                  >
                    <ClipboardCheck className="h-3.5 w-3.5" aria-hidden />{" "}
                    Security test plan (§17.13)
                  </h2>
                  <span className="text-[10px] text-muted-foreground tabular-nums">
                    {secDelivered}/{secTotal} delivered
                  </span>
                </div>
                <Card className="transition-shadow hover:shadow-md">
                  <CardContent className="p-0">
                    <div className="divide-y divide-border">
                      {data.securityTests.map((t) => (
                        <div
                          key={t.id}
                          className="flex items-center justify-between gap-3 px-4 py-2.5 transition-colors hover:bg-muted/40"
                        >
                          <div className="min-w-0">
                            <p className="text-xs font-medium text-foreground">
                              <span className="font-mono">{t.id}</span>{" "}
                              <span className="font-normal text-muted-foreground">
                                {t.title}
                              </span>
                            </p>
                            <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground/80">
                              {t.where}
                            </p>
                          </div>
                          <SecTestBadge status={t.status} />
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.section>

              {/* Live repo stats */}
              <motion.section
                className="lg:col-span-2"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.25 }}
                aria-labelledby="repo-h"
              >
                <h2
                  id="repo-h"
                  className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground"
                >
                  Repository (live)
                </h2>
                <Card className="transition-shadow hover:shadow-md">
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2 text-sm">
                      <GitBranch className="h-4 w-4" /> main
                    </CardTitle>
                    <CardDescription className="line-clamp-2 text-xs">
                      {data.live.git.subject}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid grid-cols-2 gap-3">
                    <div className="rounded-lg border p-3 transition-all hover:-translate-y-0.5 hover:border-muted-foreground/40 hover:shadow-sm">
                      <p className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                        <FileCode2 className="h-3 w-3" /> agent src
                      </p>
                      <p className="mt-1 text-lg font-semibold tabular-nums">
                        {data.live.stats.agentSrcLoc.toLocaleString()}
                      </p>
                      <p className="text-[10px] text-muted-foreground tabular-nums">
                        LOC · {data.live.stats.agentSrcFiles} files
                      </p>
                    </div>
                    <div className="rounded-lg border p-3 transition-all hover:-translate-y-0.5 hover:border-muted-foreground/40 hover:shadow-sm">
                      <p className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                        <FlaskConical className="h-3 w-3" /> tests
                      </p>
                      <p className="mt-1 text-lg font-semibold tabular-nums">
                        {data.live.stats.testFunctions.toLocaleString()}
                      </p>
                      <p className="text-[10px] text-muted-foreground tabular-nums">
                        test fns · {data.live.stats.testFiles} files
                      </p>
                    </div>
                    <div className="rounded-lg border p-3 transition-all hover:-translate-y-0.5 hover:border-muted-foreground/40 hover:shadow-sm">
                      <p className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                        <Wifi className="h-3 w-3" /> discovery
                      </p>
                      <p className="mt-1 text-lg font-semibold tabular-nums">
                        §16.2
                      </p>
                      <p className="text-[10px] text-muted-foreground">
                        mDNS advertise live
                      </p>
                    </div>
                    <div className="rounded-lg border p-3 transition-all hover:-translate-y-0.5 hover:border-muted-foreground/40 hover:shadow-sm">
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
                <div className="mt-3 flex items-start gap-2 rounded-lg border border-dashed border-border p-3 text-[11px] leading-relaxed text-muted-foreground">
                  <Stethoscope className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span>
                    Next sandbox increment:{" "}
                    <span className="font-medium text-foreground">
                      Doctor v1
                    </span>{" "}
                    — the §18.1 connection-ladder self-check, findings keyed by
                    CI-ID.
                  </span>
                </div>
              </motion.section>
            </div>

            {/* Open questions */}
            <motion.section
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.3 }}
              aria-labelledby="oq-h"
            >
              <h2
                id="oq-h"
                className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground"
              >
                Open questions &amp; owner actions (§24)
              </h2>
              <div className="grid gap-3 md:grid-cols-2">
                {data.openQuestions.map((q) => {
                  const blocking = q.status === "BLOCKING";
                  return (
                    <Card
                      key={q.id}
                      className={`group transition-all hover:shadow-md ${
                        blocking
                          ? "border-amber-500/40 hover:border-amber-500/60"
                          : "border-amber-500/20 hover:border-amber-500/40"
                      }`}
                    >
                      <CardContent className="flex items-start gap-3 p-4">
                        {blocking ? (
                          <Ban className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                        ) : (
                          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                        )}
                        <div className="min-w-0">
                          <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-foreground">
                            <span className="font-mono text-xs">{q.id}</span>
                            {q.title}
                          </p>
                          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                            {q.impact}
                          </p>
                        </div>
                        <Badge
                          variant="outline"
                          className={`ml-auto shrink-0 text-[10px] transition-colors ${
                            blocking
                              ? "border-amber-500/50 text-amber-600 dark:text-amber-400"
                              : "text-amber-600 dark:text-amber-400"
                          }`}
                        >
                          {q.status}
                        </Badge>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </motion.section>

            {/* Next steps */}
            <motion.section
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.35 }}
              aria-labelledby="next-h"
            >
              <h2
                id="next-h"
                className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground"
              >
                Next milestone — M3 / M2 completion (§22.1)
              </h2>
              <Card className="transition-shadow hover:shadow-md">
                <CardContent className="p-4">
                  <ol className="space-y-2">
                    {data.nextSteps.map((s, i) => (
                      <li
                        key={i}
                        className="group flex items-start gap-3 rounded-md px-2 py-1 text-sm text-foreground transition-colors hover:bg-muted/40"
                      >
                        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-border bg-muted font-mono text-[10px] font-semibold text-muted-foreground transition-colors group-hover:border-emerald-500/40 group-hover:text-emerald-600 dark:group-hover:text-emerald-400">
                          {i + 1}
                        </span>
                        <span className="leading-relaxed">{s}</span>
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
