# Adborth for Mac: Final Cut Pro's "Share to Adborth"

A small Mac app that takes a finished export and uploads it to Adborth in the
background. It is what Final Cut Pro's **File › Share › Adborth…** destination
hands the exported movie to. This lives only in Stori Cymru's fork.

## What it does

1. Final Cut Pro exports the movie (same as source, full quality) and opens it
   with this app.
2. The app asks where it goes: the project, and whether it is a new video or a
   new version of one already there. A file named like an existing video is
   offered as its next version.
3. It uploads in the background, in parts, straight to storage. The window can
   be closed; the menu bar shows the percentage, and a notification says when
   it is done.
4. With "Show it to the client when it is ready" ticked, it waits for the site
   to finish processing and then marks the video as needing review, which puts
   it in the client's portal and emails them.

Sign-in is by emailed code (team accounts only). The session is kept in the
login keychain and lasts as long as the app is used at least once a week.

## Build and install

Needs Xcode's command line tools.

```bash
./build.sh install     # builds build/Adborth.app and copies it to /Applications
```

The app is signed for this Mac only. After a rebuild macOS may ask once for the
login password before the app can read its saved session.

## Add the Final Cut Pro destination

```bash
open -a "Final Cut Pro" Adborth.fcpxdest
```

That adds **Adborth…** to File › Share. It exports "same as source" and opens
the result with `/Applications/Adborth.app`. To change the export format, edit
the destination in Final Cut Pro › Settings › Destinations.

## Pointing it somewhere else

The server defaults to `https://adborth.stori.cymru`. For testing:

```bash
open -a Adborth --args -serverURL http://127.0.0.1:8765
```

## Not done yet

- An upload interrupted by quitting the app does not resume; start it again.
  The site lists the interrupted one, where it can be discarded.
- Markers and comments do not travel back to Final Cut Pro yet.
