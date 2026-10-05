# RUN-BOOK — LocalMesh AI: run it here, build it anywhere

> Companion to `AGENT-BRIEF.md`. Every command below was executed and
> verified in the sandbox unless marked otherwise.

---

## 1. Full sandbox scenario from scratch (3 terminals or nohup)

```bash
# 1) Fake backends (stdlib Python, no deps)
cd tools/fake-backends
(nohup python3 fake_lmstudio.py --port 1234 --cold-load-ms 400 > /tmp/fake_lmstudio.log 2>&1 &)
(nohup python3 fake_ollama.py  --port 11434 > /tmp/fake_ollama.log 2>&1 &)

# 2) Real Agent (dev-insecure loopback — §17.9 sandbox-only mode:
#    plain HTTP on 127.0.0.1:8443, token auth bypassed, QUESTION-105)
cd agent
(nohup .venv/bin/python -m localmesh_agent run --dev-insecure-loopback > /tmp/agent_run.log 2>&1 &)
curl -s http://127.0.0.1:8443/mesh/v1/health        # → backends up
curl -s http://127.0.0.1:8444/admin/status -H "Authorization: Bearer $(cat data/admin_token 2>/dev/null)"

# 3) Dashboard (serves demo bridge + virtual device)
cd /home/z/my-project && bun run dev                # port 3000
# open /            → dashboard, "Virtual device" panel (iframe)
# open /virtual-device/ → the app full-screen
```

Verify the chain:

```bash
curl -s http://127.0.0.1:3000/api/localmesh/demo/info           # agent info via bridge
curl -s -X POST http://127.0.0.1:8443/mesh/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"ollama::qwen-fake:7b","messages":[{"role":"user","content":"hi"}],"stream":true}' | head -c 400
```

Stop everything: `pkill -f localmesh_agent; pkill -f fake_ollama; pkill -f fake_lmstudio`.

---

## 2. Android APK — verified recipe

### 2a. In this sandbox (already done once; result kept)

Toolchain: OpenJDK 21, Android SDK at `/home/z/android-sdk`
(platform-tools, `platforms;android-35`, `platforms;android-37.0` symlinked
as `android-37`, `build-tools;35.0.0`, cmdline-tools 11076708 + 13114758).

```bash
# One-time deps (node_modules for expo CLI)
cd apps/mobile && bun install

# Generate native project (android/ is gitignored; regenerable)
export ANDROID_HOME=/home/z/android-sdk
bunx expo prebuild --platform android --no-install

# Memory tuning already appended to android/gradle.properties (4 GB box):
#   org.gradle.jvmargs=-Xmx1400m -XX:MaxMetaspaceSize=512m
#   kotlin.compiler.execution.strategy=in-process
#   org.gradle.workers.max=2 ; org.gradle.parallel=false ; caching=true

cd android && ./gradlew assembleDebug --no-daemon
# APK: apps/mobile/android/app/build/outputs/apk/debug/app-debug.apk
```

Install on a phone (owner machine, USB debugging on):

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

### 2b. On any owner machine (recommended path)

1. Install Android Studio (2025.3+ so SDK 37 minor packages register) OR
   commandline-tools ≥ 13114758 + JDK 17+.
2. `sdkmanager "platform-tools" "platforms;android-37.0" "build-tools;35.0.0"`
   (accept licenses; set `ANDROID_HOME`).
3. `cd apps/mobile && npm install` (or bun) → `npx expo prebuild --platform android`.
4. Android Studio: open `apps/mobile/android/` → Run ▶ on device/emulator,
   or `cd android && ./gradlew assembleDebug`.
5. Kotlin module tests: `./gradlew :mesh-core:testDebugUnitTest` (JVM),
   `./gradlew :mesh-core:connectedDebugAndroidTest` (device; includes the
   FR-PAIR-03 pin-mismatch zero-body test — needs a device, no /dev/kvm here).

Emulator note (verified): x86_64 Android emulator **cannot** run in this
sandbox (no `/dev/kvm`; nested virt unavailable). Options are (a) any owner
machine with Android Studio emulator, (b) cloud device farms
(Firebase Test Lab / BrowserStack / pcloudy), or (c) the web virtual device
in the dashboard — the real JS app in a browser, native layer stubbed.

---

## 3. Rebuild the web virtual device (after any apps/mobile change)

```bash
cd apps/mobile
CI=1 EXPO_NO_TELEMETRY=1 bunx expo export --platform web --output-dir dist
rm -rf ../public/_expo ../public/assets ../public/virtual-device
mkdir -p ../public/virtual-device
cp -r dist/_expo ../public/_expo
cp -r dist/assets ../public/assets
cp dist/index.html dist/metadata.json ../public/virtual-device/
```

Then hard-reload the dashboard. The panel's "Reload device" button re-fetches
the iframe; the badge shows the live agent name/version from the bridge.

---

## 4. Fixture capture (owner PC with real backends)

Follow `docs/fixtures/CAPTURE.md` verbatim (LM Studio 0.3.x native + OpenAI
endpoints, Ollama /api/tags|ps|show + chat). Commit under `docs/fixtures/`
in the layout the doc specifies; contract tests
(`agent/tests/contract/`) automatically prefer fixtures over fakes.

---

## 5. Release path (owner)

```bash
# 1) pentest checklist → sign-off
$EDITOR docs/security/pentest-checklist.md && \
  cp docs/security/pentest-signoff.md{,.draft}   # fill, then commit

# 2) gate + artifacts
scripts/release_gate.sh           # all §21.4/RELEASE.md gates incl. pentest
scripts/release_build.sh          # wheel + sdist + SHA256SUMS + TC-SEC-07 scan

# 3) tag + publish
git tag -s v1.0.0-rc.1 -m "LocalMesh AI v1.0.0-rc.1 [M9, §21.6]"
```

APK release build (after signing config): `cd apps/mobile/android &&
./gradlew assembleRelease` — cleartext carve-out is debug-only (§17.9),
PinnedHttp enforces TLS 1.3 + pin in release regardless.
