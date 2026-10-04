Contents

1. [1 Scope and source analysis](#s1)
2. [2 Design principles](#s2)
3. [3 Visual language](#s3)
4. [4 Navigation and flows](#s4)
5. [5 Connection status system](#s5)
6. [6 Screen specifications](#s6)
7. [6.1 Welcome and first run](#s61)
8. [6.2 Pair a machine](#s62)
9. [6.3 Machines](#s63)
10. [6.4 Machine detail](#s64)
11. [6.5 Chat](#s65)
12. [6.6 Model and routing](#s66)
13. [6.7 Attachments and voice](#s67)
14. [6.8 Library and documents](#s68)
15. [6.9 Tasks and agents](#s69)
16. [6.10 Settings](#s610)
17. [6.11 Notifications](#s611)
18. [6.12 Offline mode](#s612)
19. [7 Component library](#s7)
20. [8 States and errors](#s8)
21. [9 Adaptive layouts](#s9)
22. [10 Accessibility](#s10)
23. [11 Microcopy](#s11)
24. [12 Phases and handoff](#s12)
25. [13 Open decisions](#s13)

# LocalMesh AI Android UI design specification

How the app looks, behaves and talks, from first launch to a streaming reply. It covers screens, components, states and copy only. Architecture, networking and backend choices are taken as given from your three source files.

Wi-Fi Secure tunnel Relay Offline

Platform: Android (phones first, tablets and foldables adapted) Version 1.0 draft

## 1 Scope and source analysis

This document defines the user interface of the LocalMesh AI Android app: a phone client that finds the AI machines you own (a PC running LM Studio, Ollama, llama.cpp or similar), connects to them at home or from anywhere, and lets you chat, send images, voice and documents, and later run tasks on them.

### What each source file contributes to the UI

| Source | UI requirements taken from it |
| --- | --- |
| **info.docx** (product concept) | The "My AI Machines" list with status dot, GPU, model and tokens per second. An "AI PC" detail view with hardware, models and services (LLM, Vision, Voice, RAG, OCR, Agent). One calm message, "Connected to Gaming PC", regardless of how the connection is made. Auto-routing by input type (image → vision model, long reasoning → larger model). Camera, voice and PDF flows that run on the PC. The phone as a remote AI workstation. |
| **Executive Summary PDF** | Native Android with Kotlin and Jetpack Compose. Chat with file, voice and image attachments. Connection icon showing LAN, tunnel or offline. Which model answered. Offline mode with a disabled send button at minimum. "Notify me when done" for backgrounded replies. QR or code pairing and a device revocation screen. Minimal permissions. Chat export as JSON or Markdown. "PC busy" warning. Warning before actions that run on the PC with the user's privileges. |
| **Feasibility study PDF** | Streaming rendering rules: batch UI updates every 50–100 ms, show a typing indicator first, apply full markdown after the message ends, and keep the partial reply when Stop is pressed. Local chat history. Device list with models and live metrics. Connection order of direct LAN, then mDNS, then the remote tunnel. A manual address field for the first release. A remote tunnel that may need a second app installed on the phone. |

### Where the sources disagree, and what this spec does

| Topic | Disagreement | UI decision |
| --- | --- | --- |
| Framework | Executive Summary says Kotlin and Jetpack Compose. Feasibility study recommends React Native. | The spec is toolkit-neutral. Section 12 maps every component to Jetpack Compose. Streaming notes that matter for React Native are marked. |
| Remote transport | Tailscale (needs its own app on the phone) versus WebRTC or a relay (no extra app). | The remote setup screen is a checklist driven by status, so it works for either. It never shows a vendor name unless that vendor is actually in use. |
| Encryption on Wi-Fi | Executive Summary says TLS plus AES everywhere. Feasibility study allows plain HTTP on the LAN for the MVP. | Every connection shows its security level in the connection details sheet. Plain HTTP on Wi-Fi is labelled "Not encrypted on this network" so the user is never misled. |
| Scope | The concept includes Whisper, OCR, RAG and agents. Not every PC will run them. | The UI is capability-driven. A feature appears when a machine reports it, and when it does not, the screen says why. |

## 2 Design principles

#### Machines, not networks

People pick "Gaming PC", never an IP address. Addresses, ports and tunnel names live behind a details sheet.

#### One status language

Four connection paths, each with a fixed colour, icon and label, used identically on every screen.

#### Say where the data goes

Privacy is the product. The app shows the route a message takes and whether it is encrypted, in plain words.

#### Capability-driven

Vision, voice and documents appear only when the chosen machine supports them. A missing capability gets an explanation and an alternative, not a greyed-out button.

#### Streaming is the product

Replies appear smoothly, never jump, and can be stopped without losing what has arrived.

#### Recoverable by default

Drops, sleeping PCs and cold model loads are normal. Partial replies are kept, messages can be retried, and the app reconnects without asking.

#### Depth on demand

Routing rules, tokens per second and path details are one tap away but never in the way of a simple chat.

#### Calm and plain

Sentence case, active verbs, no jargon, and no apologising in error messages. Errors say what happened and what to do.

## 3 Visual language

The look is quiet and technical: a cool neutral base, one indigo brand colour, and four connection-path colours that carry meaning wherever they appear. Colour is never the only signal; every path also has an icon and a text label. Toggle the preview at the top of the page to see the app in light and dark.

### 3.1 Colour tokens

| Role | Light | Dark | Use |
| --- | --- | --- | --- |
| Background | #F7F7FB | #0E1018 | Screen background |
| Surface | #FFFFFF | #171A25 | Cards, sheets, bars |
| Surface raised | #EEF0F6 | #1F2332 | Composer, chips, inline code, meters |
| Outline | #D6D9E4 | #2E3347 | Dividers, card borders |
| Text | #151826 | #E8EAF3 | Primary text |
| Text secondary | #5A6075 | #9AA0B6 | Captions, metadata |
| Primary (Mesh indigo) | #3F3FD9 | #9A9AFF | Main actions, send button, selected state |
| Primary container | #E3E3FF | #2A2A6B | Your message bubble, selected nav pill, tonal buttons |
| Path: Wi-Fi | #0E7A4F | #3DD598 | Direct LAN connection, online dot |
| Path: Secure tunnel | #2563D8 | #7AAEFF | Remote connection through the encrypted tunnel |
| Path: Relay | #A86412 | #F2B84B | Fallback relay, slower path, warnings |
| Path: Offline | #6B7186 | #8A90A6 | Unreachable machine, no network |
| Error | #C62F3E | #FF7A88 | Failed send, revoke and forget actions |

Values were picked to reach 4.5:1 for text on Surface. Re-check them with your contrast tool when they are applied in Figma or Compose, especially chip text on its 15% tint.

On Android 12 and newer, offer "Dynamic colour" as an opt-in in Appearance settings. When it is on, only Primary and Primary container follow the wallpaper. The four path colours stay fixed so status always means the same thing.

### 3.2 Typography

Use Roboto Flex (or the system sans) for the whole app and a monospace face for code only. Everything scales with the system font size; layouts must survive 200%.

| Style | Size / line | Weight | Used for |
| --- | --- | --- | --- |
| Title large | 22 / 28 sp | Medium | Screen titles |
| Title medium | 16 / 24 sp | Medium | Card titles, machine names, sheet headings |
| Body large | 16 / 24 sp | Regular | Chat text (default; user can change 14–20 sp in Chat settings) |
| Body medium | 14 / 20 sp | Regular | List rows, descriptions |
| Label large | 14 / 20 sp | Medium | Buttons, tabs |
| Label medium | 12 / 16 sp | Medium | Chips, captions, message metadata |
| Code | 13 / 18 sp | Regular, monospace | Code blocks, inline code, addresses in details sheets |

### 3.3 Spacing, shape and elevation

| Token | Value | Rule |
| --- | --- | --- |
| Grid | 4 dp | All spacing is a multiple of 4. Common steps: 4, 8, 12, 16, 24, 32. |
| Screen margin | 16 dp | Horizontal padding for lists and cards. 24 dp on tablets. |
| Card | 16 dp padding, 12 dp gap between cards | Radius 16 dp. 1 dp outline, no shadow, so lists stay flat and fast. |
| Chips | 24 dp high, 12 dp radius | Visual height is 24 dp; the touch target is padded to 48 dp. |
| Buttons | 40 dp high, fully rounded | Touch target 48 dp. One primary button per screen section. |
| Composer | 52 dp minimum, 28 dp radius | Grows to 6 lines, then scrolls inside. |
| Sheets | 28 dp top radius | Drag handle, scrim at 50% black. Used for choices that belong to the current screen. |
| Elevation | Floating action button and sheets only | Everything else is separated by outline or tone. |
| Touch target | 48 × 48 dp minimum | Applies to every tappable element, including chips and icons. |

### 3.4 Icons

Use Material Symbols (Rounded, weight 400, 24 dp, 1.8 dp stroke in custom drawings). The set below is the minimum needed; every icon is paired with text wherever meaning could be lost.

Wi-Fi path

Secure tunnel

Relay

Offline

Machine

Auto routing

### 3.5 Motion

| Moment | Behaviour | Duration |
| --- | --- | --- |
| Screen transitions | Material shared-axis (horizontal) between list and detail; fade-through between bottom-nav tabs. | 300 ms |
| Connection chip change | Colour and label cross-fade. No bounce, no shake. | 200 ms |
| Connecting | The dot pulses softly (opacity 40–100%) only while connecting. | 1.2 s loop |
| First token | The typing indicator is replaced in place by text, with no layout jump. | 100 ms |
| Streaming text | Appended in batches (see 6.5). No per-character animation. A thin cursor blinks at the end. | n/a |
| Sheets | Slide up with standard deceleration, dismiss by drag or scrim tap. | 250 ms |

When the system "Remove animations" setting is on, replace slides with fades, stop all pulsing and blinking, and keep state changes instant.

## 4 Navigation and flows

### 4.1 Information architecture

```
App
├─ Welcome (first run only)
│  ├─ Find my PC on this Wi-Fi → Found machines → Confirm → Name
│  └─ Connect from anywhere → Sign in → Scan QR or enter code → Verify → Remote access check
├─ Chats (tab)
│  ├─ Conversation list (search, filter by machine)
│  └─ Chat
│     ├─ Model and routing sheet
│     ├─ Attach sheet → Camera · Photos · Files · Voice note · Scan document
│     ├─ Voice mode (full screen)
│     ├─ Connection details sheet
│     └─ Message details sheet
├─ Machines (tab)
│  ├─ Machine detail → Models · Services · Hardware · Rename · Forget
│  └─ Add machine
├─ Library (tab, from phase 2)
│  ├─ Documents → Document chat
│  └─ Images and voice notes
└─ Settings (tab)
   ├─ Account · Connection · Devices and security · Models and routing
   └─ Chat · Notifications · Storage and history · Appearance · About and diagnostics
```

Tasks and agents (phase 5) are reached from Machine detail → Services → Agent, and from a "Tasks" filter at the top of the Chats list.

### 4.2 Navigation rules

- **Compact screens:** a 4-item bottom navigation bar (Chats, Machines, Library, Settings). In phase 1 there are three items; Library is added in phase 2.
- **Start destination:** Chats when at least one paired machine is online; Machines when none is.
- **Back:** system back always closes the top-most sheet, then goes up one level. From a tab root, back goes to the Chats tab, then exits.
- **Deep links:** notifications open the exact conversation or task. The pairing QR can also open the app directly into the pairing flow.
- **Bottom bar hides** while a chat is open so the composer has the full width and height.

### 4.3 Core flows

| Flow | Steps | Target |
| --- | --- | --- |
| First chat at home | Open app → "Find my PC on this Wi-Fi" → tap the found machine → name it → chat opens with the machine's default model. | Under 60 seconds, 4 taps |
| Connect from anywhere | Sign in → scan QR on the PC → confirm matching code → remote access check → done. | Under 3 minutes, once |
| Daily use | Open app → last conversation is ready on the last machine → type → reply streams. | 0 taps before typing |
| Image question | In a chat tap + → Camera → take photo → type question → send. Routing picks a vision model and tells the user. | 5 taps |
| Machine goes offline mid-reply | Partial reply stays. A banner appears. The app retries across paths. On success, "Retry" continues the reply; on failure it offers another machine. | No lost text |

## 5 Connection status system

The app tries a direct Wi-Fi connection first, then the secure tunnel, then a relay if the user allows it. The user should only ever see the result, in one consistent form.

### 5.1 The four paths

| State | Chip label | Icon | Meaning | Detail line (in the details sheet) |
| --- | --- | --- | --- | --- |
| Wi-Fi | Wi-Fi | wifi | Direct to the PC on the same network | "Direct on Home Wi-Fi · 4 ms" plus the security level (see below) |
| Secure tunnel | Secure tunnel | shield | Remote, end-to-end encrypted | "Encrypted tunnel · 46 ms" |
| Relay | Relay | cloud | Fallback path that bounces through a server. Content stays encrypted, but replies may be slower. | "Encrypted relay · 180 ms. Slower than usual." |
| Offline | Offline | wifi-off | The machine cannot be reached on any path | "Last seen 2 days ago" |

Two transient states reuse these chips. **Connecting** keeps the previous colour with a pulsing dot and the label "Connecting". **Needs attention** uses the Error colour with the label "Sign in again" or "Access removed" when authentication fails or the machine was revoked.

### 5.2 Security level shown in the details sheet

- **Encrypted end to end** (tunnel, relay, or TLS on Wi-Fi). Shown with a lock icon.
- **Not encrypted on this network** (plain HTTP on Wi-Fi). Shown with a warning tint and a link: "Trust this network" or "Turn on encryption". Trusted networks are remembered in Settings → Connection.

### 5.3 Where the chip appears

- **Machine card:** under the machine name.
- **Chat top bar:** in the route row, next to the machine and model name. Tap opens the connection details sheet.
- **Notifications and widgets:** text label only, no colour dependency.

### 5.4 Connection details sheet

A bottom sheet with: machine name, current path chip, address (monospace, tap to copy), latency, security level, and a "Connection attempts" list showing each path tried with a tick or a short reason ("Wi-Fi: PC not found on this network", "Secure tunnel: connected"). A single "Reconnect" button runs the sequence again. The path order itself is configured in Settings → Connection.

### 5.5 Switching behaviour

- The app races paths in order and settles on the best working one within about 3 seconds per step.
- A change of path never interrupts an open stream silently: the chip updates, and if the stream breaks, the partial reply is kept and a Retry row appears.
- Moving from Wi-Fi to tunnel (leaving home) shows a snackbar once: "Switched to secure tunnel."
- Moving to Relay shows a banner once per session: "Using a slower relay connection."

## 6 Screen specifications

Each screen lists its purpose, layout, behaviour, states and key copy. Mockups are drawn at 360 × 740 dp and scaled down here. They are structural references, not final art.

### 6.1 Welcome and first run

9:41●●▮

Chat with AI that runs on your own PC

Private by design. Your chats stay on your devices.

Find my PC on this Wi-Fi

Connect from anywhere

Looking for machines nearby…

Welcome. Scanning starts silently in the background.

9:41●●▮

Found on this Wi-Fi

Gaming PC

LM Studio · 192.168.1.100

Online

Connect

Workstation

Ollama · 192.168.1.42

Online

Connect

Enter address manually

Not listed? Make sure the LocalMesh agent or your model server is running on the same Wi-Fi.

Machines found by Wi-Fi discovery, with a manual fallback.

#### Purpose

Get a first-time user to a working chat in one minute, or into remote pairing, without any network vocabulary.

#### Layout

- **Welcome:** brand mark, one-line promise, two stacked buttons. The primary action is the local one because it is faster and works with no account.
- **Found machines:** a list of cards (name, backend and address in small text, status chip, Connect button) and an "Enter address manually" outlined button beneath.

#### Behaviour

- Local discovery starts when the app opens. If one machine is found within 3 seconds, the primary button changes to "Connect to Gaming PC" with the caption "Found on this Wi-Fi". With several, it opens the list.
- Permissions are requested at the moment of use, each with a one-line reason shown first: nearby-device or local-network access when scanning starts, camera when scanning a QR code, microphone on the first voice use, and notifications when the user first turns on "Notify me when done".
- After connecting, ask for a friendly name (prefilled with the machine's reported name) and open a new chat.

#### Manual entry form

| Field | Default and helper text |
| --- | --- |
| Address | Placeholder `192.168.1.100`. Accepts IP or `name.local`. Helper: "Find this in your model server's network settings." |
| Port | Placeholder `1234`. Helper: "LM Studio uses 1234. Ollama uses 11434." |
| Access token (optional) | Password field with show/hide. Helper: "Only needed if you turned on authentication on the PC." |
| Actions | "Test connection" runs a check and shows the result inline (reachable, models found, or the exact reason). "Save" stays disabled until the test passes. |

#### States

- **Scanning:** small progress indicator and "Looking for machines nearby…".
- **Nothing found:** "No machines found on this Wi-Fi." with \[Try again\] and \[Enter address manually\].
- **Permission denied:** "LocalMesh needs permission to find devices on your Wi-Fi." with \[Allow in settings\] and the manual option still available.

### 6.2 Pair a machine (remote access)

9:41●●▮

Pair a machine

Step 2 of 4

Scan the QR code on your PC

Open LocalMesh on your PC and choose Add device.

Enter code instead

Step 2: scan. Camera permission is asked just before this screen.

9:41●●▮

Pair a machine

Step 3 of 4

Check the code

Your PC should show the same six digits.

482 917

Expires in 0:52

They match

They don't match

Step 3: verify. Protects against pairing with the wrong device.

9:41●●▮

Pair a machine

Step 4 of 4

Connect from anywhere

Three quick checks so Gaming PC works away from home.

**Signed in**Identity only. Chats never go through Google.

**Gaming PC is paired**Named "Gaming PC"

**Secure tunnel app**Not installed on this phone

Install

Test remote connection

Use on home Wi-Fi only

Step 4: remote access check, driven by live status.

#### Flow

1. **Sign in with Google.** One screen, one button. Caption: "Google only confirms it's you. Your chats never go through Google or LocalMesh servers."
2. **Scan the QR code** shown by the PC. "Enter code instead" accepts the 8-character code printed under the QR.
3. **Verify.** Show a six-digit comparison code in large type with a countdown. Two choices: "They match" and "They don't match". The second cancels pairing and tells the user to start again on the PC.
4. **Name the machine** (prefilled), then the **remote access check**.

#### Remote access check

A three-row status list. Each row has a state icon, a title, one line of detail and, when action is needed, a single button. Rows are generated from the connection setup in use, so a transport that needs no extra app simply has no third row. The primary button runs a real end-to-end test and reports the path and latency. "Use on home Wi-Fi only" is always available, so remote access is never forced.

#### Failure states

| Situation | Message | Actions |
| --- | --- | --- |
| QR not recognised | "That isn't a LocalMesh QR code." | Try again · Enter code instead |
| Code expired | "That code expired. Ask your PC for a new one." | Scan again |
| PC not reachable during pairing | "Can't reach your PC. Make sure it's on and LocalMesh is running." | Try again |
| Different Google account | "Your PC is signed in as a different account." | Switch account · Learn how |

### 6.3 Machines (home of the mesh)

9:41●●▮

My AI machines

2 of 3 online

**Gaming PC**

Wi-FiRTX 4070 · 12 GB

Qwen 3.5 9B · 18 tok/s

ChatVisionVoiceDocuments

New chatDetails

**Workstation**

RelayCPU only

Qwen 3.5 4B · 7 tok/s

Chat

**Laptop**

OfflineLast seen yesterday

Add machine

Chats

Machines

Library

Settings

Machines list. Connection chip, hardware, current model and speed per card.

9:41●●▮

My AI machines

No machines yet

Add the PC that runs your models to chat with them from this phone.

Add your first machine

Chats

Machines

Library

Settings

Empty state: one explanation, one action.

#### Card anatomy

| Element | Spec |
| --- | --- |
| Header row | Machine icon (tinted by status), name in Title medium, preferred star if set, overflow menu at the far right. |
| Status row | Connection chip, then a short hardware summary in secondary text, such as "RTX 4070 · 12 GB" or "CPU only". |
| Model line | Current default model and last measured speed, such as "Qwen 3.5 9B · 18 tok/s". Speed is labelled "last measured" in its content description. |
| Capability chips | Non-interactive chips from the machine's reported services: Chat, Vision, Voice, Documents, OCR, Agent. Wrap to a second line if needed. |
| Actions | Primary "New chat" and secondary "Details". Offline cards have only "Details". |

#### Behaviour

- Order: online machines first, preferred machine on top, then by most recently used.
- Tapping the card opens Machine detail. Tapping "New chat" starts a chat with the machine's default model, with no extra step.
- Overflow menu: Rename, Set as preferred, Open connection details, Forget this machine (opens a confirmation dialog).
- Pull to refresh re-runs discovery. Live metrics refresh every 5 seconds only while this screen is visible.
- Offline cards stay legible at 78% opacity. Never grey text below the contrast minimum.

#### States

- **Loading:** three skeleton cards (static when animations are off).
- **Busy:** a small "Busy" chip in place of the speed text when the GPU is saturated.
- **Needs attention:** an Error-tinted chip, "Sign in again" or "Access removed", with a single fix button.

### 6.4 Machine detail

9:41●●▮

Gaming PC

Wi-Fi · 4 msPreferred

**RTX 4070**64 °C

VRAM7.2 of 12 GB

Memory18 of 32 GB

Models

**Qwen 3.5 9B**Q4_K_M · 32k context · loaded

Reasoning

**Qwen Vision**Q4_K_M · 8k context · loaded

Images

**Qwen 3.5 4B**Q4_K_M · 32k context · on disk

Fast

Services

ChatVisionVoiceDocumentsAgent · not set up

Start chat

Machine detail: live hardware, models and services.

#### Sections, top to bottom

- **Header chips:** connection path with latency, and a Preferred toggle chip.
- **Hardware:** GPU or CPU name, temperature if reported, and two meters (VRAM, system memory) with "used of total". Meters use Primary below 85% and the Relay/warning colour above it.
- **Models:** one row per model: loaded dot, name, a detail line (quantisation, context length, loaded or on disk) and a capability chip. Tap a row to start a chat with it. If the PC allows remote loading, long-press offers Load or Unload.
- **Services:** chips for each capability. A service that is not set up shows a muted chip and a "Set up on your PC" link explaining what to install.
- **Connection:** opens the connection details sheet.
- **Forget this machine:** destructive text button at the bottom with a confirmation dialog.

#### Busy and queue

When the PC reports load above about 90% or a queue, show a banner under the header: "Gaming PC is busy · 2 requests ahead of yours." It is informational, not blocking.

### 6.5 Chat

9:41●●▮

Checkout dark patterns

Gaming PC

Wi-FiQwen 3.5 9BAuto

List five dark patterns I should check on a checkout page.

Qwen 3.5 9B · Gaming PC

Thought for 6 s

Here are five patterns worth checking:\
1\. Hidden costs: fees that only appear on the last step\
2\. Pre-ticked add-ons: insurance or newsletters selected by default\
3\. False urgency: countdown timers that reset

Message Gaming PC

Chat while a reply is streaming. Send turns into Stop.

9:41●●▮

Checkout dark patterns

Gaming PC

Connection dropped. Your reply so far is saved.

Review this screenshot for dark patterns.

Qwen Vision · Gaming PC · chosen because you sent an image

The screenshot shows a checkout page with a pre-selected "Add protection plan" box and a countdown banner that

RetryUse another machine

Message Gaming PC

Interrupted reply. Partial text is kept; the fix is one tap.

9:41●●▮

Checkout dark patterns

##### Connection

**Gaming PC**Wi-Fi

192.168.1.100:1234 · 4 ms

Not encrypted on this network. Trust this network

Connection attempts

**Wi-Fi**

Connected

–

**Secure tunnel**

Not needed

–

**Relay**

Not needed

Reconnect

Connection details sheet, opened from the connection chip.

#### Top area

- **App bar:** back, conversation title (editable by tap), machine name as subtitle, overflow menu (Rename, Export as Markdown or JSON, Clear chat, Delete).
- **Route row** directly below: connection chip (opens connection details), model chip with a dropdown arrow (opens Model and routing sheet), and an "Auto" chip when automatic routing is on.
- The route row is pinned and never scrolls away.

#### Messages

- **Your messages:** right-aligned bubble in Primary container, maximum 82% of the width, corner radius 18 dp with a 4 dp tail corner. Attachments sit above the text.
- **Replies:** full width with no bubble, so long answers, tables and code read comfortably. A small header shows a path-coloured dot, the model and the machine.
- **Routing note:** when Auto picked a model, the header adds a short reason such as "chosen because you sent an image". Tapping it opens the Model and routing sheet.
- **Reasoning block:** models that think first show a collapsed row, "Thought for 6 s". It is collapsed by default, expandable, and excluded from copy and export unless the user expands it.
- **Code blocks:** language label, Copy button, horizontal scroll without wrapping, monospace 13 sp.
- **Reply footer** (after completion): Copy, Regenerate, Share, and a details button showing model, tokens, tokens per second and path.
- **Your message actions** (long-press): Copy, Edit and resend, Delete.

#### Streaming behaviour

1. On send, the message appears immediately and a three-dot typing indicator takes the reply position. The Send button becomes Stop.
2. If no token arrives within 8 seconds, replace the indicator text with "Loading the model on Gaming PC. The first reply can take up to a minute." This covers cold starts after a model was unloaded.
3. Tokens are collected and drawn in batches every 50–100 ms, never one render per token. (This is the key rule if the app is built with React Native.)
4. During streaming, text is shown as plain text with a thin cursor. When the reply finishes, full markdown formatting is applied once, with no visible jump in position.
5. **Auto-scroll:** the list follows the newest text only while the user is at the bottom. If they scroll up, stop following and show a small "Jump to latest" pill above the composer.
6. **Stop:** cancels the request, keeps all text received so far, tags the reply "Stopped", and shows Continue and Regenerate.
7. **Interruption:** keep the partial text, show the banner and a Retry row (see the second mockup). Retry resumes on the same machine; "Use another machine" opens the picker.
8. **Screen readers:** announce "Reply started" once and the full reply once it finishes. Never announce each batch.

#### Composer

- A rounded field with a leading + (attach), a multi-line text input (up to 6 lines), and a trailing circular button that changes with state: microphone when empty, Send when there is text or attachments, Stop while streaming.
- Placeholder: "Message Gaming PC". If the machine is offline the placeholder is "Gaming PC is offline" and Send is disabled (see 6.12).
- Enter inserts a new line by default; an option in Chat settings makes Enter send for hardware keyboards.
- Draft text is kept per conversation, including after the app is closed.

#### Empty chat

Show the machine name and model, then up to four suggestion chips based on what the machine can do, for example "Summarise a document", "Describe a photo", "Explain some code", "Transcribe a voice note". Chips for services the machine does not have are not shown.

### 6.6 Model and routing

9:41●●▮

Checkout dark patterns

##### Model and routing

Auto

Choose

Gaming PC

**Qwen 3.5 9B**18 tok/s · fits in memory

**Qwen Vision**For images · 12 tok/s

**Qwen 3.5 4B**Fastest · needs loading

Workstation

**Qwen 3.5 4B**CPU · 7 tok/s

**Laptop**Offline

**Use for new chats**

Off

Choose a model manually. Auto mode shows the routing rules instead.

#### Two modes

- **Auto (default from phase 4):** the sheet lists the rules in plain language, such as "Images → Qwen Vision", "Code and hard problems → Qwen 3.5 9B", "Everything else → Qwen 3.5 4B", each with an on/off switch. An "Edit rules" row opens the full rules editor.
- **Choose:** machines grouped as headings, models as radio rows with speed and a fit note ("fits in memory", "needs loading", "too large for free memory"). Offline machines are listed but disabled with the reason.

#### Rules

- Selection applies to the current chat. "Use for new chats" makes it the default.
- Changing the model mid-chat inserts a thin divider in the thread, "Switched to Qwen Vision", so the history stays honest.
- When the selected model lacks a capability the user is asking for (for example an image), the composer shows an inline notice, "Qwen 3.5 9B can't read images. Switch to Qwen Vision?" with a one-tap switch.

### 6.7 Attachments and voice

9:41●●▮

Checkout dark patterns

##### Attach

Camera

Photos

Files

Voice note

Scan document

Task

Task needs an agent on Gaming PC. Set it up

Attach sheet. Unavailable options say why.

9:41●●▮

Voice mode

Wi-Fi

Listening

"Summarise the notes from today's lecture…"

Transcribed by Whisper on Gaming PC

Voice mode: listening, thinking and speaking states.

#### Attach sheet

A 3-column grid of tiles: Camera, Photos, Files, Voice note, Scan document, and (phase 5) Task. A tile that the current machine cannot serve stays visible, muted, with a one-line reason and a link, instead of disappearing. Tapping a muted tile explains what is missing and offers to switch machine.

#### Composer attachment previews

- A horizontal strip above the text field. Images appear as 56 dp rounded thumbnails; files as a card with type icon, name and size.
- Each item has a remove button (48 dp touch target). While uploading, a progress ring replaces the remove button and the item reads "Sending to Gaming PC…".
- Large images are resized before sending. Show a caption once: "Resized to save bandwidth."
- Limits (type and size) are shown before the upload starts. Over-limit example: "This file is 142 MB. The limit for sending to Gaming PC is 50 MB."

#### Camera and scan

A full-screen capture view with flash, flip and a shutter. After capture: Retake, Crop (scan only), Use photo. Scan document captures multiple pages into one PDF with edge detection and a page counter, then adds it as one attachment.

#### Voice

- **Hold the microphone** in the composer to record; release to stop, slide left to cancel, slide up to lock. The composer is replaced by a waveform and timer while recording.
- The transcript appears in the text field before sending so the user can correct it. A caption names where it was transcribed, for example "Transcribed by Whisper on Gaming PC".
- **Voice mode** is a full-screen hands-free loop with three labelled states: Listening, Thinking, Speaking. Controls: mute microphone and end. The waveform animates only while a state is active, and is static with reduced motion.
- Spoken replies show captions of the same text. Speech can be paused from the notification and the lock screen.

### 6.8 Library and documents

Library arrives with phase 2 for files and images and grows in phase 4 with document question answering. It has three tabs: **Documents**, **Images**, **Voice notes**.

- **Document row:** type icon, name, page count, the machine that holds the index, and a status chip: Uploading → Reading text → Indexing → Ready. Failed shows "Couldn't read this file" with Retry and the reason (for example scanned pages that need OCR).
- **Upload:** a floating "Add" button opens the system file picker. A progress bar shows bytes sent; the row keeps working in the background and a notification reports completion.
- **Document chat:** opens a normal chat with a document chip pinned above the composer ("Asking: Contract.pdf"). Several documents can be attached to one chat.
- **Citations:** answers carry small numbered chips linked to pages, such as "p. 4". Tapping one opens a bottom sheet with the passage and its page number.
- **Images:** a 3-column grid of photos sent to the PC, with the question and answer on tap.
- **Empty state:** "Nothing here yet. Add a document to ask questions about it on your PC."

### 6.9 Tasks and agents (phase 5)

Tasks are longer jobs the PC runs for the user, such as browsing, working with files or calling APIs. The UI makes progress visible and puts the user in control of anything risky.

```
Tasks
┌────────────────────────────────────────┐
│ Collect 10 prices from three shop sites │
│ Gaming PC · Running · step 4 of 7       │
│ ▓▓▓▓▓▓░░░░                    [Stop]    │
├────────────────────────────────────────┤
│ Rename and sort the Downloads folder    │
│ Gaming PC · Needs your approval         │
│ [Review]                                │
├────────────────────────────────────────┤
│ Summarise weekly notes        Done 9:12 │
└────────────────────────────────────────┘
```

- **Task list:** status chips are Queued, Running, Needs approval, Done, Failed, Stopped. "Needs approval" sorts to the top and drives a notification.
- **Task detail:** a vertical timeline of steps in plain language ("Opened the site", "Read the page", "Saved results to a file"), the machine it runs on, elapsed time, and Stop. No raw logs by default; "Show details" reveals them.
- **Approval sheet:** shown before any step that changes files, runs commands, or uses accounts. It states exactly what will happen on which machine: "Gaming PC will rename 48 files in Downloads." Buttons: Allow once, Always allow this kind of step (off by default and listed in Settings), Cancel. A fixed line reminds the user: "This runs on your PC with your permissions."
- **Results:** a summary message plus any files, which open in the Library.

### 6.10 Settings

9:41●●▮

Settings

A

**Signed in with Google**you@example.com

**Connection**Path order, trusted networks

**Devices and security**2 phones, 3 machines · App lock

**Models and routing**Auto routing on

**Chat**Text size, Enter key, markdown

**Notifications**Replies, machines, approvals

**Storage and history**Export, auto-delete, clear

**Appearance**Theme, dynamic colour

**About and diagnostics**Version, share logs without chats

Chats

Machines

Library

Settings

Settings root. Every row has a title and a live summary.

| Section | Contents |
| --- | --- |
| Account | Signed-in identity, Sign out. Signing out keeps local chats but disables remote machines. If not signed in, the card offers "Sign in to connect from anywhere". |
| Connection | Path order (Wi-Fi first, then tunnel, then relay, reorderable). "Allow relay fallback" switch with a one-line explanation. Trusted Wi-Fi networks list. Manual endpoints and tokens. "Switch automatically" on by default. |
| Devices and security | Lists "This phone", other phones and machines, each with last active time. Tap a device for Rename and Remove access. Removing shows a confirmation dialog naming the device. App lock (biometric or device PIN) and "Hide chats in recent apps" switches. |
| Models and routing | Auto routing switch, routing rules editor, speed-versus-quality preference (Fast, Balanced, Best), "Keep models loaded" request, default machine. |
| Chat | Text size slider (14–20 sp), Enter key behaviour, show reasoning blocks, show tokens per second, haptics on reply complete. |
| Notifications | See 6.11. |
| Storage and history | Export all chats (JSON or Markdown), auto-delete after (never, 30 days, 1 year), clear all chats, storage used. |
| Appearance | Theme (System, Light, Dark), dynamic colour on Android 12+, chat density. |
| About and diagnostics | Version, open-source licences, privacy statement, "Share diagnostics" which exports connection events with no prompts or replies. |

### 6.11 Notifications

| Channel | When | Default | Example text |
| --- | --- | --- | --- |
| Replies | A reply finishes while the app is in the background | On after the user enables "Notify me when done" | "Reply ready from Gaming PC" |
| Machines | A preferred machine goes offline or comes back | Off | "Gaming PC is back online" |
| Approvals | A task needs permission to continue | On | "A task on Gaming PC needs your approval" |
| Security | A new device paired, access removed, sign-in expired | On, cannot be disabled | "A new phone was added to your account" |
| Ongoing | Foreground notification while a long reply or voice mode runs | On while active | "Gaming PC is replying" with Stop |

Notification text never includes prompts or reply content. On the lock screen, show only the generic text. Tapping a notification opens the exact conversation or task.

### 6.12 Offline mode

| Situation | What the user sees |
| --- | --- |
| Phone has no network | A banner at the top of every screen: "No internet or Wi-Fi." The composer is disabled with the placeholder "You're offline". History, search and export keep working. |
| Machine is offline, phone is fine | The chip becomes Offline. Banner: "Gaming PC can't be reached." Actions: Try again · Choose another machine. Typed text is kept as a draft. |
| Tunnel unreachable away from home | The details sheet lists each failed path with its reason. Banner offers Reconnect. |
| Queued sending (optional) | A "Send when connected" button replaces Send. Queued messages show a clock icon and send in order after reconnection. Off by default; enabled per chat. |
| On-device fallback (optional) | If a small model is installed on the phone, the banner adds "Use on-device model (4B)". Replies from it carry a different header dot and the label "On this phone", so users know the answer did not come from their PC. |

## 7 Component library

| Component | Variants and states | Key specs | Compose starting point |
| --- | --- | --- | --- |
| Connection chip | Wi-Fi, Secure tunnel, Relay, Offline, Connecting, Needs attention | 24 dp high, 16 dp icon + 12 sp label, 15% tint of path colour. Content description "Connection: Wi-Fi". | Custom `Surface` with `CircleShape`; clickable variant uses `AssistChip` |
| Machine card | Online, Busy, Offline, Connecting, Needs attention, Preferred | 16 dp padding, 16 dp radius, 1 dp outline. Offline at 78% opacity. | `OutlinedCard` |
| Model row | Loaded, On disk, Selected, Disabled | Two-line list item, loaded dot leading, capability chip trailing. | `ListItem` |
| Capability chip | Available, Not set up | Non-interactive. Muted when not set up. | `SuggestionChip` (disabled click) |
| Your message | Sending, Sent, Failed, Edited | Primary container, 82% max width, 18/4 dp corners. Failed shows an Error icon and a Retry text button. | `Surface` with custom `RoundedCornerShape` |
| Reply | Waiting, Streaming, Complete, Stopped, Interrupted | No bubble. Header, body, optional reasoning block, footer actions only when complete. | Custom composable inside `LazyColumn` |
| Reasoning block | Collapsed, Expanded, Live (while thinking) | Outlined, 12 dp radius. Label "Thinking…" live, "Thought for N s" afterwards. | `AnimatedVisibility` |
| Code block | Default, Copied | Language label, Copy button, horizontal scroll, Surface raised background. | Custom with `horizontalScroll` |
| Composer | Empty, Typing, With attachments, Streaming, Recording, Disabled | 52 dp minimum, 6 lines max, trailing button swaps mic, send and stop. | `BasicTextField` in `Surface` |
| Attachment thumbnail | Idle, Uploading, Failed | 56 dp, progress ring while uploading, 48 dp remove target. | Custom with `CircularProgressIndicator` |
| Bottom sheet | Partial, Expanded | 28 dp top radius, drag handle, scrim 50%. | `ModalBottomSheet` |
| Banner | Info, Warning, Error | One at a time, persistent until resolved, with at most one action. Priority: Offline, Needs attention, Warning, Info. | Custom `Row` in `Surface` |
| Snackbar | Confirmation | 4 seconds, one optional action. Reuse the verb of the action ("Copied"). | `SnackbarHost` |
| Step progress | n of N | Linear bar plus "Step 2 of 4" in the app bar. | `LinearProgressIndicator` |
| Metric meter | Normal, High (above 85%) | 6 dp high. Label left, "used of total" right. | `LinearProgressIndicator` (custom height) |
| Empty state | Per screen | 48–56 dp icon, title, one sentence, one action. Centered. | Custom `Column` |
| Skeleton | Animated, Static | Same shapes as the real content. Static when animations are off. | Custom shimmer modifier |
| Confirm dialog | Standard, Destructive | Title names the object ("Forget Gaming PC?"). Destructive button uses the Error colour and an explicit verb. | `AlertDialog` |

## 8 States and errors

### 8.1 State coverage checklist

Every screen needs a design for each of these before it is considered done:

| Screen | Loading | Empty | Error | Offline | Permission denied |
| --- | --- | --- | --- | --- | --- |
| Welcome and discovery | Scanning | Nothing found | Test failed | No Wi-Fi | Local network blocked |
| Pairing | Verifying | n/a | Expired, mismatch | No internet | Camera blocked |
| Machines | Skeleton cards | No machines | Needs attention | Machine offline | n/a |
| Machine detail | Skeleton meters | No models loaded | Metrics unavailable | Last known data, dimmed | n/a |
| Chat | Typing, model loading | Suggestion chips | Interrupted reply | Disabled composer | Microphone or camera blocked |
| Library | Indexing | Nothing here yet | Couldn't read file | Local list only | File access blocked |
| Tasks | Running | No tasks | Task failed | Paused, waiting for machine | n/a |

### 8.2 Message catalogue

| Situation | Message | Actions |
| --- | --- | --- |
| Machine not found on Wi-Fi | "Can't find Gaming PC on this Wi-Fi. Check that it's on and the agent is running." | Try again · Connect remotely |
| No model loaded | "Gaming PC has no model loaded. Load one on the PC or pick another." | Choose model |
| Cold start | "Loading Qwen 3.5 9B on Gaming PC. The first reply can take up to a minute." | Cancel |
| Machine busy | "Gaming PC is busy. Yours is next." | Cancel |
| Stream interrupted | "The connection dropped. Your reply so far is saved." | Retry · Use another machine |
| Out of memory on the PC | "Gaming PC ran out of memory for this model. Try a smaller one." | Choose model |
| Sign-in expired | "Sign in again to use machines away from home." | Sign in |
| Access removed | "This phone no longer has access to Gaming PC." | Pair again · Remove |
| No vision model | "Gaming PC has no model that can read images." | Choose machine |
| File too large | "This file is 142 MB. The limit for sending to Gaming PC is 50 MB." | Choose another file |
| Microphone blocked | "Microphone access is off. Turn it on to record." | Open settings |
| Plain HTTP on Wi-Fi | "Not encrypted on this network." | Trust this network · Turn on encryption |

Rules for error copy: say what happened first, then what to do; use the machine's name; do not apologise, blame the user or show codes (codes live in "Share diagnostics").

## 9 Adaptive layouts

| Window size | Navigation | Layout |
| --- | --- | --- |
| Compact, under 600 dp (most phones) | Bottom navigation bar | Single pane. Lists push to detail screens. Chat is full screen. |
| Medium, 600–839 dp (foldables open, small tablets, phones in landscape) | Navigation rail | Machines and Library use list + detail side by side. Chat is a single pane at up to 720 dp wide, centered. |
| Expanded, 840 dp and wider (tablets) | Navigation rail | Chats: conversation list (360 dp) on the left, chat on the right. Machines: list left, detail right. Sheets open as centered dialogs of 560 dp. |

- **Chat reading width:** text never exceeds about 720 dp so lines stay readable.
- **Keyboard:** the composer sits above the keyboard and the list keeps the newest message visible. The route row collapses into the app bar when height is tight.
- **Landscape phone:** compact composer (44 dp), bottom navigation becomes a rail.
- **Foldable tabletop posture:** messages on the top half, composer and keyboard on the bottom half.
- **Edge to edge** with correct insets, and support for predictive back so the back gesture previews the screen being returned to.

## 10 Accessibility and localisation

### 10.1 Accessibility

- **Touch targets** of at least 48 × 48 dp, with spacing of at least 8 dp between neighbours.
- **Contrast:** 4.5:1 for text and 3:1 for icons and component outlines, in both themes.
- **Not colour alone:** every connection state has an icon and a text label; every status dot is paired with words.
- **TalkBack:** meaningful content descriptions on icon buttons; connection chip reads "Connection: Wi-Fi, 4 milliseconds"; machine card reads as one group: name, status, model, speed. Reply streaming is announced once at start and once at completion, using a polite live region on the status text rather than on the reply body.
- **Font scaling to 200%:** cards grow, chips wrap, nothing truncates critical status. Test with the largest system font and display size.
- **Reduced motion:** follow the system setting for every animation in section 3.5.
- **Focus order and keyboard:** logical order, visible focus ring, composer reachable by Tab, Ctrl+Enter or Enter to send on hardware keyboards.
- **Haptics:** a light tick when a reply completes and a distinct pattern for errors, both optional in Chat settings.
- **Time limits:** the pairing code countdown can be extended by requesting a new code, and is also announced as text.

### 10.2 Localisation

- All strings live in resources with no concatenated sentences; use placeholders with plurals.
- Full right-to-left mirroring, including bubble alignment and back arrows. Mixed-direction text inside messages uses bidirectional isolation.
- Numbers, dates and units follow the device locale. Speeds are always written "tok/s".
- Allow 40% text expansion in buttons and chips.

## 11 Microcopy

### 11.1 Vocabulary

| Use | Instead of | Note |
| --- | --- | --- |
| Machine | Node, host, server, instance | "My AI machines" is the name of the Machines screen. |
| Secure tunnel | VPN, WireGuard, mesh peer | Technical names appear only in Settings → Connection → Details. |
| Pair, Add machine | Register, enrol |  |
| Forget this machine | Delete device | The PC is not deleted, only this phone's link to it. |
| Remove access | Revoke | Used for removing a phone or machine from the account. |
| Reply | Completion, response |  |
| Stop | Abort, cancel generation | Stop keeps the partial reply; Cancel discards a pending action. |
| Retry | Try again later | One word for the same action everywhere, including its confirmation message. |
| Tok/s | Throughput | Shown only on machine cards, reply details and the model picker. |

### 11.2 Key strings

| Where | String |
| --- | --- |
| Welcome headline | Chat with AI that runs on your own PC |
| Welcome support line | Private by design. Your chats stay on your devices. |
| Connected snackbar | Connected to Gaming PC |
| Path switch snackbar | Switched to secure tunnel |
| Relay banner | Using a slower relay connection |
| Privacy line in connection sheet | Your messages go straight to Gaming PC. LocalMesh servers never see them. |
| Sign-in caption | Google only confirms it's you. Your chats never go through Google or LocalMesh servers. |
| Composer placeholder | Message Gaming PC |
| Notification, reply ready | Reply ready from Gaming PC |
| Forget dialog | Forget Gaming PC? This phone will stop connecting to it. You can pair it again later. \[Cancel\] \[Forget\] |
| Remove access dialog | Remove access for "Old phone"? It will be signed out of your machines right away. \[Cancel\] \[Remove access\] |

## 12 Phases and handoff

### 12.1 UI delivery by phase

This follows the roadmap in the feasibility study and the concept notes, expressed as interface work.

| Phase | UI to ship |
| --- | --- |
| 1 · LAN chat MVP | Welcome, discovery and manual entry (6.1). Machines list with single-machine cards (6.3). Chat with full streaming behaviour, Stop, local history, copy (6.5). Settings basics. Connection chip with Wi-Fi and Offline. Reply-ready notification. Offline states (6.12). |
| 2 · Machines, models, files | Machine detail with hardware and model list (6.4). Model picker (6.6). Several machines. Attach sheet with images and files (6.7). Library with documents and images (6.8). Chat search and export. |
| 3 · Accounts and remote access | Sign-in, QR pairing, verify and remote access check (6.2). Secure tunnel and Relay chips, connection details sheet and path switching (section 5). Devices and security with Remove access (6.10). |
| 4 · Intelligence | Auto routing, routing rules editor and routing notes in replies (6.6). Voice mode (6.7). Document chat with citations (6.8). Busy and queue banners (6.4). |
| 5 · Agents and tablets | Tasks list, detail and approval sheet (6.9). Two-pane tablet layouts (section 9). Optional on-device fallback model UI (6.12). |

### 12.2 Jetpack Compose handoff notes

| Need | Suggested approach |
| --- | --- |
| Theme | Material 3 `MaterialTheme` with a custom colour scheme for the tokens in 3.1, and an extra `PathColors` object (LAN, tunnel, relay, offline) exposed through `CompositionLocal` so they never follow dynamic colour. |
| Navigation | Navigation Compose with the tab roots as top-level destinations; adaptive navigation (bar on compact, rail on larger) through the Material 3 adaptive navigation suite. |
| Two-pane screens | Material 3 adaptive list-detail scaffold driven by window size class. |
| Chat list | `LazyColumn` with stable item keys. Streaming state held as a flow that is throttled to roughly 80 ms (for example with `sample`) before it reaches the UI. |
| Markdown | Render plain text while streaming; parse and render markdown once on completion, off the main thread. |
| Sheets and dialogs | `ModalBottomSheet` and `AlertDialog`; sheets become dialogs on expanded widths. |
| Accessibility | `Modifier.semantics` with merged descendants on cards, and a polite live region on the status text only. |
| If React Native is chosen | Same visual spec. Batch streaming updates every 50–100 ms using `requestAnimationFrame`, show a typing indicator until the first token, apply markdown after completion, and cancel generation with an abort controller while keeping the partial reply. |

### 12.3 Definition of done for each screen

- All states in section 8.1 designed and implemented.
- Light, dark and dynamic-colour screenshots reviewed.
- Checked at 320 dp width, 200% font size, and in landscape.
- TalkBack pass completed, including reading order.
- Strings externalised and checked against the vocabulary in section 11.
- Reduced-motion behaviour verified.
- Screenshot tests added for the main states of the screen.

## 13 Open decisions

These affect the UI and need an answer before the related screens are finalised.

1. **Remote transport for the first release.** It decides whether the remote access check has a "secure tunnel app" row (section 6.2).
2. **Plain HTTP on Wi-Fi.** The feasibility study allows it for personal builds but not for public store release. Decide whether release builds require encryption on Wi-Fi, which changes the "Not encrypted" warning flow.
3. **Conversation sync.** Chats are stored on the phone only in the sources. If syncing between phones is wanted, the Chats list needs an account-level scope and a privacy explanation.
4. **On-device fallback model.** Include the UI in version 1 or defer to phase 5.
5. **Auto routing default.** On for everyone, or opt-in until the rules editor exists.
6. **Minimum Android version.** Affects dynamic colour, predictive back and the notification permission flow.
7. **Name and logo.** "LocalMesh AI" and the three-node mark here are placeholders.
8. **Other surfaces.** The concept notes also mention a desktop companion, web dashboard and CLI. They are outside this Android specification.