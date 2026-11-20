# Adborth for Mac: the upload helper and the Final Cut Pro panel

Two small pieces of Mac software, built together and shipped as one app,
`/Applications/Adborth.app`. They exist only in Stori Cymru's fork of FreeFrame
(`storicymru/freeframe`); nothing here is upstream.

| Piece | What it is | Code | Bundle id | Process name |
|---|---|---|---|---|
| **The helper** | A menu-bar and window app that uploads a finished export to Adborth | `Sources/Adborth/` (SwiftUI, Swift package) | `cymru.stori.adborth` | `Adborth` |
| **The panel** | A Final Cut Pro workflow extension showing Adborth inside Final Cut, linking comments to the timeline | `Panel/` (AppKit + WebKit, built with `swiftc`) | `cymru.stori.adborth.panel` | `AdborthPanel` |

The panel is carried inside the helper's bundle at
`Adborth.app/Contents/PlugIns/Adborth.appex`. Both are version **0.4.1**
(`Info.plist` and `Panel/Info.plist`; bump both together). Both talk to
`https://adborth.stori.cymru` by default.

"Adborth" is Stori Cymru's branded, self-hosted FreeFrame. The web app and API
are in `apps/web` and `apps/api` of this repository.

## Layout

```
apps/mac-share/
├── build.sh                 builds everything; "install" also copies to /Applications
├── Package.swift            the helper only (the panel is not a package target)
├── Info.plist               the helper's bundle settings
├── Adborth.fcpxdest         Final Cut's share destination (binary plist; open it in Final Cut to add it)
├── Resources/mark.png       the Adborth mark shown in the helper's window
├── Sources/Adborth/
│   ├── App.swift            app delegate: window, menu bar item, menus, files handed to the app
│   ├── API.swift            the API client, session renewal, the Keychain item
│   ├── Model.swift          app state: who is signed in, projects, files waiting, uploads
│   ├── Upload.swift         one upload from start to finish, and the parallel part sender
│   └── Views.swift          every screen: sign-in, "where does this go", the upload list
└── Panel/
    ├── PanelViewController.swift   the web view, the Final Cut timeline calls, the page messages
    ├── Markers.swift               turns comments into FCPXML markers and a marker clip
    ├── Info.plist                  the extension's settings (extension point, principal class)
    └── Panel.entitlements          sandbox, network, Apple events to Final Cut
```

`build/` (the built app) and `.build/` (Swift's cache) are not in git.

## Build and install

Needs macOS 13 or later, Xcode's command line tools, and **Final Cut Pro
installed on the building Mac**. It cannot be built on Linux or in CI.

```bash
cd apps/mac-share
./build.sh install
```

What `build.sh` does, in order:

1. `swift build -c release` for the helper, then assembles `build/Adborth.app`
   by hand (executable, `Info.plist`, `mark.png`).
2. Makes the icon from `../web/public/brand/adborth-icon.png` with `sips` and
   `iconutil`.
3. Copies `ProExtension.framework` out of the installed Final Cut
   (`/Applications/Final Cut Pro.app` or `/Applications/Final Cut Pro Creator
   Studio.app`) into the extension. Final Cut talks to an extension through
   classes in that framework; without it the panel crashes on connect. Copying
   at build time keeps Apple's code out of the repository.
4. Compiles the panel with `swiftc` directly: `-application-extension`, entry
   point `_NSExtensionMain`, linked against `ProExtension`.
5. Signs the framework, then the extension (with `Panel.entitlements`), then
   the app, all ad hoc (`codesign --sign -`).
6. With `install`: replaces `/Applications/Adborth.app`, re-registers it with
   Launch Services, and adds the extension with `pluginkit -a`.

After installing a new build:

- Quit and reopen the helper if it was running.
- For the panel: `pkill -x AdborthPanel`, then in Final Cut choose
  **Window › Extensions › Adborth** (it often takes choosing the menu item
  twice). The very first time an extension is installed, Final Cut has to be
  restarted before it is listed.

### Signing, and why it matters

The app is **ad-hoc signed**: no Apple Developer account, no Team ID, not
notarised. Consequences to know:

- It runs only on the Mac that built it. It is not downloadable anywhere and
  has only ever been built on James's MacBook.
- Every rebuild changes the signature, so macOS can ask once for the login
  password before the helper may read its saved session from the Keychain.
- The extension loads despite the ad-hoc signature because it carries a
  sandbox entitlement, which macOS requires of any extension.

Planned but not done: Developer ID signing, notarisation and a self-updater
(Sparkle, with the feed published on Adborth). It waits on Stori Cymru
enrolling in the Apple Developer Program. The certificate and the notarisation
credential are for James to create and keep in his own Keychain; do not ask
for, print or store them.

## The helper

### What it does for the person using it

1. A file arrives: from Final Cut's **File › Share › Adborth…**, a drop on the
   window or Dock icon, "Open With", **File › Upload a File…**, or
   `open -a Adborth <file>`.
2. The helper asks where it goes: the project (a searchable list; typing a new
   name offers to create the project), and whether it is a **new video** or a
   **new version of an existing video**. A file named like an existing video
   is offered as its next version.
3. It uploads in the background. The window can be closed; the menu bar shows
   the percentage, the row shows "14.61 of 17.74 GB · 13.7 MB/s · about 4 min
   left", and a notification says when it is done. The Mac is kept awake while
   an upload runs. Quitting with an upload running asks first.
4. With **Show it to the client when it is ready** ticked, it waits for the
   site to finish processing, then marks the video as needing review, which
   puts it in the client's portal and emails them.

Movies, audio and images are accepted (`mimeType(for:)` in `Upload.swift`
lists the extensions). Client accounts are refused: the helper is for the team.

### Signing in

Two ways, both ending with the same kind of session:

- **Through the browser (the default).** The helper opens
  `<site>/connect?challenge=…&state=…&name=…`. The person, usually signed in
  there already, approves; the site sends the browser to
  `adborth://connect?code=…&state=…`, which macOS hands back to the helper;
  the helper exchanges the code at `POST /auth/device/token`. It is PKCE: the
  helper sends a hash of a secret at the start and the secret at the exchange,
  so another app catching the code cannot use it. Server side:
  `apps/api/routers/device_auth.py`; the page: `apps/web/app/connect/page.tsx`.
- **By emailed code**, as a fallback on the sign-in screen
  (`/auth/send-magic-code`, `/auth/verify-magic-code`).

The helper never sees a password. Only the **refresh token** is stored, in the
login Keychain as a generic password with service = the bundle id and account
`refresh-token`; the access token lives in memory. A helper session lasts 180
days from last use (`DEVICE_REFRESH_TOKEN_EXPIRE_DAYS` on the server). A 401
makes the helper renew once and retry; a refused renewal signs it out.

Never print, log or copy these tokens.

### How an upload travels

All in `Upload.swift`, class `UploadJob` and struct `PartSender`.

| Step | Call |
|---|---|
| Start | `POST /upload/initiate` with project, name, filename, MIME type, size, and `asset_id` when it is a new version. Returns the upload id, storage key, asset id, version id and `chunk_size_bytes`. |
| Each part | `POST /upload/presign-part` for a link, then `PUT` the bytes straight to storage. A fresh link for every attempt. |
| Finish | `POST /upload/complete` (15 minute timeout: the server assembling a large file is slow). |
| Show to client | Poll `GET /assets/{id}` every 6 seconds for up to 12 hours; when the new version is `ready`, `PATCH /assets/{id}` with `status: in_review`. |
| Cancel | `POST /upload/abort` with `discard: true`, which throws away what was sent. The server then frees the version number, so the next upload reuses it. |

Things that are deliberate and easy to break:

- **Six connections, one per lane.** The bytes go directly to storage at
  `cyfryngau.stori.cymru:8443`, not through the site and not through the VPN.
  That server speaks HTTP/2, and one `URLSession` puts every part on a single
  connection, which over the internet ran at about half the line's speed
  (6.7 MB/s). `PartSender.sessions` is therefore six separate sessions, each
  limited to one connection per host; measured 11.6 to 13.7 MB/s on a 110 Mb/s
  home line.
- **Memory is capped.** Parts in flight = `min(6, 384 MB / part size)`, so the
  app never holds more than about 384 MB of the file.
- **Retries.** A part is tried up to six times with a growing wait. A 4xx
  other than 429 stops at once (signed out, project deleted, upload discarded).
- **A failed upload is left on the server**, where the site lists it as
  interrupted; only a cancel discards.

### Pointing it at another server

```bash
open -a Adborth --args -serverURL http://127.0.0.1:8765
```

The setting is the `serverURL` user default. Local addresses are allowed over
plain HTTP (`NSAllowsLocalNetworking`). API paths are `<serverURL>/api/...`.

### The Final Cut share destination

```bash
open -a "Final Cut Pro" Adborth.fcpxdest
```

adds **Adborth…** to File › Share. It exports "same as source" and opens the
result with `/Applications/Adborth.app`. To change the export format, edit the
destination in Final Cut Pro › Settings › Destinations. Final Cut's own
settings folder is protected by macOS, so the file cannot simply be copied in.

## The Final Cut Pro panel

A workflow extension (`com.apple.FinalCut.WorkflowExtension`), opened in Final
Cut from **Window › Extensions › Adborth**. It is a web view showing Adborth
itself, signed in once and kept signed in (the web view's data store is on
disk), plus a little native code that talks to Final Cut. Minimum size 380 by
480.

It works in both Final Cuts: the one-off purchase (`com.apple.FinalCut`) and
the subscription "Creator Studio" one (`com.apple.FinalCutApp`), which James
uses. The trial (`com.apple.FinalCutTrial`) is allowed for too.

### What it does

- **The timeline follows the player.** Click a comment or drag the player's
  bar in Adborth, and Final Cut's playhead moves to the same moment in the
  project open in the timeline.
- **Comments into Final Cut as markers**, two ways:
  - **Send comments** (the button): a *marker clip* for the project open in
    the timeline, with no dragging.
  - **Drag the project** from Final Cut's browser onto the panel: a *copy of
    the project* named "‹name› – Adborth comments" with the markers on its own
    clips, plus the marker clip beside it.

  Either way the import lands in an event called **Adborth comments** in the
  project's own library, without Final Cut asking which library to use.

A video has to be open in the panel (its address contains
`/assets/<uuid>`); the comments are those of its latest version. Comments with
no time on the video are left out and counted in the summary.

### What a marker looks like

- Numbered in the order they fall, zero-padded: "03 Name: what they said".
- Replies go in the marker's note, on one line, separated by "•".
- Every comment is a to-do marker; one resolved in Adborth arrives ticked
  (completed).
- Markers already on a dragged project are not added twice.
- The **marker clip** is a clip the length of the project carrying Final Cut's
  Timecode generator (enlarged) with a Basic Title per comment: bold white
  text, wrapped by hand to at most six lines. It is named
  "‹name› – Adborth markers" and is laid over the edit to read the comments in
  place.

### How it talks to Final Cut

Apple ships no Swift interface for workflow extensions, so the calls are made
by name (`FinalCutTimeline` in `PanelViewController.swift`):

- `ProExtensionHostSingleton()` → `timeline` → `addTimelineObserver:`,
  `sequenceTimeRange`, `playheadTime`, `movePlayheadTo:`.
- **Nothing is reported until `addTimelineObserver:` has been called**, so the
  panel registers as an observer as it opens.
- Final Cut tells an extension only how long the open project is and where its
  timecode starts. To learn *which* project that is, the panel asks Final Cut
  by AppleScript for every project in every open library (name, event,
  library path, duration, start, frame duration, drop-frame) and matches on
  length and start. This also finds libraries PostLab keeps in hidden folders.
- **That lookup is done ahead of time and cached**, 1.5 seconds after Final
  Cut says the timeline changed. Asking by Apple event from inside a native
  button click froze Final Cut; asking at the moment of the press came back
  empty. Do not move it back into the click.
- The result is handed over as an `.fcpxml` file opened with the running Final
  Cut. In it, `<import-options><option key="library location" …/>` is what
  stops the "which library?" dialog, and `<library location><event name>` sets
  the event.
- When there was no drag, the FCPXML is built from a stand-in project of the
  right name, length and frame rate (`MarkerBuilder.standIn`). Its format must
  be named `FFVideoFormat1080p<rate>` and carry a `colorSpace`, or Final Cut
  imports it with a warning.
- A dragged project arrives on the pasteboard as `com.apple.finalcutpro.xml`
  or `com.apple.finalcutpro.xml.v1-8` to `v1-16`.

### How it talks to the page

The panel injects a script at document start and offers the page a message
channel, `window.webkit.messageHandlers.adborth`. Messages are accepted only
from the main frame of the site's own host.

| Direction | Message | Meaning |
|---|---|---|
| page → panel | `{ seconds }` | the player landed on a new moment (caught by wrapping `HTMLMediaElement.currentTime` and the `seeked` event) |
| page → panel | `{ controls: true \| false }` | the page is showing its own Final Cut controls, so the panel hides its bar |
| page → panel | `{ follow: boolean }` | switch "timeline follows the player" |
| page → panel | `{ action: 'comments' }` | send this video's comments to Final Cut |
| panel → page | `adborth-panel` event, `detail: { follow?, note? }` | the current setting, and the line the panel would otherwise show |

The page's side is `apps/web/components/review/final-cut-controls.tsx`: a
"Final Cut Pro" card in the comment panel, rendered only when that channel
exists, so it never appears in an ordinary browser. Once a site has shown
those controls the panel remembers it (`siteHasControls`) and keeps its own
bottom bar hidden except to show a message when no page control is on screen.

To fetch comments the panel runs a script *in the page*, which uses the page's
own session (`ff_access_token` / `ff_refresh_token` in local storage) against
`/api/assets/{id}` and `/api/assets/{id}/comments`. The panel's native code
never holds a token.

Links that leave Adborth open in the default browser; "new tab" links stay in
the panel. If the page's process dies (it happens after a long sleep) the
panel reloads the site.

### Entitlements

`Panel/Panel.entitlements`: the app sandbox (required for any extension),
outgoing network, and Apple events to the three Final Cut bundle ids with the
`com.apple.FinalCut.library.inspection` scripting target, which is what lets
it list libraries, events and projects.

### Pointing the panel at another site

```bash
defaults write cymru.stori.adborth.panel site https://staging.example.test
```

Only `https` addresses are accepted; anything else falls back to the live site.

## Finding faults in the panel

The panel is a separate sandboxed process inside Final Cut, so ordinary tools
see little of it. It has its own hooks, all in its sandbox's temporary folder:

```
~/Library/Containers/cymru.stori.adborth.panel/Data/tmp/
```

| File | Effect |
|---|---|
| `panel.log` | Written by the panel; starts afresh each time the panel opens. The first place to look. |
| `probe.js` | Put a script here and within 2 seconds it is run in the page and its result logged. Synchronous JavaScript only, no `await`. |
| `snap` | Create this (empty) file and the panel writes `snap.png`, a picture of the page. |
| `handoff.fcpxml` | Put an FCPXML here and the panel hands it to Final Cut, to test that step alone. |
| `home` | A file holding a project name: the panel logs which library and event hold it. |
| `open` | Create it to make the panel look again for the project open in the timeline. |

Also useful:

- `/usr/bin/log stream --predicate 'process == "AdborthPanel"'` for its
  `NSLog` lines (`log` alone is a shell builtin in zsh).
- `screencapture -x -o -l <window id>` captures the panel even in the
  background. Accessibility-based screenshot tools show its web area blank,
  and cannot click inside it: it belongs to another process.
- The web view paints only if the root view has `wantsLayer = true`, and the
  root must use an autoresizing mask to follow Final Cut's window.

## Tests

There are none for the Swift code; it has been checked by hand against the
live site and Final Cut. The page's side of the panel is tested in
`apps/web/components/review/__tests__/final-cut-controls.test.tsx`, and the
server's side of the helper (sign-in, upload, abort and discard) in
`apps/api/tests/`.

Before changing upload behaviour, check on the server that nothing is
uploading or processing (`tools/adborth/deploy.sh --status`), and never test
against a client's project: use **Prawf / Test**.

## Not done yet

- **Self-update.** Waiting on the Apple Developer account (see Signing).
- **Resuming.** An upload interrupted by quitting the app does not resume;
  start it again. The site lists the interrupted one, where it can be
  discarded.
- **Uploading from the panel.** Uploads go through the helper only.
- **Renaming in the background.** Not a fault of the app, but worth knowing
  when driving it by automation: its text fields cannot be typed into while
  the app is in the background.
