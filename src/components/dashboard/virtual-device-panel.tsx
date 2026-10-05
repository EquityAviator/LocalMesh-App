"use client";

/**
 * Virtual Device panel — the REAL Local Mesh AI app (apps/mobile Expo/React
 * Native source) exported for web (react-native-web) and rendered inside a
 * phone frame. It talks to the REAL Python Agent running in this sandbox
 * through the demo bridge (/api/localmesh/demo/* → 127.0.0.1:8443,
 * --dev-insecure-loopback §17.9 — token auth bypassed, QUESTION-105).
 *
 * Sandbox-demo-only surface: the production app uses the native Kotlin
 * mesh-core transport with TLS 1.3 + SPKI pinning (§17.3/§17.9).
 */

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ExternalLink, MonitorSmartphone, RefreshCw, Wifi, WifiOff } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

interface AgentInfo {
  agent_id?: string;
  display_name?: string;
  agent_version?: string;
  pairing_open?: boolean;
}

export function VirtualDevicePanel() {
  const [agent, setAgent] = useState<AgentInfo | null>(null);
  const [live, setLive] = useState<boolean | null>(null);
  const [nonce, setNonce] = useState(0);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch(`/api/localmesh/demo/info?n=${nonce}`, { cache: "no-store" });
        if (!res.ok) throw new Error(String(res.status));
        const info = (await res.json()) as AgentInfo;
        if (!cancelled) {
          setAgent(info);
          setLive(true);
        }
      } catch {
        if (!cancelled) setLive(false);
      }
    };
    check();
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: 0.3 }}
      aria-labelledby="vdev-h"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-y-1">
        <h2
          id="vdev-h"
          className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground"
        >
          <MonitorSmartphone className="h-3.5 w-3.5" aria-hidden /> Virtual device —
          the real app, live (§11 · react-native-web)
        </h2>
        <span className="text-[10px] text-muted-foreground tabular-nums">
          apps/mobile source · expo export web · demo bridge → real Agent
        </span>
      </div>
      <Card className="transition-shadow hover:shadow-md">
        <CardContent className="p-4 sm:p-6">
          <div className="grid gap-6 lg:grid-cols-[auto_minmax(0,1fr)]">
            {/* Phone frame */}
            <div className="mx-auto w-fit">
              <div className="relative rounded-[2.2rem] border-[10px] border-zinc-900 bg-zinc-900 shadow-2xl dark:border-zinc-700">
                {/* Notch */}
                <div className="absolute left-1/2 top-1.5 z-10 h-4 w-24 -translate-x-1/2 rounded-full bg-zinc-900 dark:bg-zinc-800" />
                <iframe
                  key={nonce}
                  src={`/virtual-device/?n=${nonce}`}
                  title="Local Mesh AI virtual device — live app preview"
                  className="block h-[560px] w-[280px] overflow-hidden rounded-[1.6rem] bg-white dark:bg-zinc-950"
                  onLoad={() => setLoaded(true)}
                />
              </div>
              <p className="mt-2 text-center text-[10px] text-muted-foreground">
                {loaded ? "App bundle loaded — interact with the screens" : "Loading app bundle…"}
              </p>
            </div>

            {/* Side info */}
            <div className="flex min-w-0 flex-col gap-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge
                  variant="outline"
                  className={
                    live === null
                      ? "text-[10px] text-muted-foreground"
                      : live
                        ? "border-emerald-500/40 font-mono text-[10px] text-emerald-600 dark:text-emerald-400"
                        : "border-amber-500/40 font-mono text-[10px] text-amber-600 dark:text-amber-400"
                  }
                >
                  {live === null ? (
                    "checking agent…"
                  ) : live ? (
                    <>
                      <Wifi className="mr-1 inline h-3 w-3" aria-hidden />
                      agent live: {agent?.display_name ?? "unknown"} · v{agent?.agent_version ?? "?"}
                    </>
                  ) : (
                    <>
                      <WifiOff className="mr-1 inline h-3 w-3" aria-hidden />
                      agent offline — app shows fallback states
                    </>
                  )}
                </Badge>
                <Badge variant="outline" className="text-[10px] text-muted-foreground">
                  package ai.localmesh.app
                </Badge>
              </div>

              <p className="max-w-prose text-xs leading-relaxed text-muted-foreground">
                This is the <strong className="text-foreground">actual app source</strong> from{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">apps/mobile</code>{" "}
                (Expo / React Native, expo-router screens, SM-CONN / SM-STREAM domain machines)
                bundled with react-native-web. On this panel it runs the{" "}
                <strong className="text-foreground">sandbox demo transport</strong> — plain HTTP
                fetch through the bridge to the real Agent in dev-insecure loopback mode. On a
                real phone the identical code uses the native Kotlin{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">mesh-core</code>{" "}
                module: TLS 1.3-only, SPKI pinning, mDNS discovery (§16.2, §17.3, §17.9).
              </p>

              <ul className="grid list-inside list-disc gap-1 text-xs text-muted-foreground sm:grid-cols-2">
                <li>Machines tab — live /info + /health + /models</li>
                <li>Machine detail — model load / unload, backend chips</li>
                <li>Chat — real SSE streaming through the Agent queue</li>
                <li>Doctor — §18.4 ladder via the transport</li>
              </ul>

              <div className="mt-auto flex flex-wrap gap-2 pt-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  onClick={() => setNonce((n) => n + 1)}
                >
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Reload device
                </Button>
                <Button size="sm" variant="outline" className="gap-1.5" asChild>
                  <a href="/virtual-device/" target="_blank" rel="noreferrer">
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden /> Open full screen
                  </a>
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.section>
  );
}
