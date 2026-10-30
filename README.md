# Choano

Swim, eat and grow in a microscopic world. Eat equal or smaller amoebas,
avoid larger ones, and stay inside the petri dish. Spawn warnings give you
time to move; cumulative growth earns extra lives. An illustrated title screen opens the game, with native in-app navigation.

Reaching full size unlocks Fish mode in the open sea. Fish of many kinds,
seahorses, lobsters and starfish are food at your size or smaller and bite
when bigger; seahorses are big, so grow before you hunt them. Dash past
jellyfish, collect golden pearls, feast on sardine schools, and swim clear
when tense music announces a shark. Now and then a gentle sea turtle swims
by: it never bites and leaves a short trail of golden pearls.

[Play in your browser](https://choano.waozi.xyz/)
· [Downloads](https://github.com/waozixyz/choano/releases/latest)
· [Source](https://github.com/waozixyz/choano)

![Choano replacement artwork](assets/choano/title-landscape.jpg)

Six quiet event chimes replace the old beat and spawn noises. There is no
loading message or browser footer; forming bubbles stay beneath the player.

Native and browser editions share the same Ziran game rules and Kryon
widgets. The website's title screen links the latest release's APKs,
AppImage and Windows installer. All artwork and audio are replacements made
for Choano. Original Moeboid assets and binaries are excluded; see
[asset provenance](ASSETS.md).

## Controls

Desktop and browser: hold arrow keys or WASD to swim. Enter after game over
or R starts a fresh run. In Fish mode, X or Shift dashes. On touch screens hold and drag
anywhere to swim that way; letting go glides smoothly to a stop, and a tap alone does nothing. Fish mode adds a
Dash button. Swipe steering is the default; choose the direction pad or
turn sound off in the in-app Settings, also reachable from Pause. Profile pauses play and opens the shared Entity account UI;
Back returns to the same run. Signing in is optional. Earned growth stages
follow that account; the current run stays on this device and is not restored
after closing the game.

The same title, pause, settings and movement-control flow runs in compatible
game libraries. Back returns through the current screen before leaving the game.

## Build and local tests

Install Ziran and the SDL2, Cairo, FreeType, Fontconfig, Pango, GTK and X11
development libraries. Emscripten is needed for the browser edition. Package
sources and the compiler are pinned in `ziran.lock`; local overrides belong
in ignored `ziran.local.toml`.

```sh
ziran fetch --locked
make test
make input-test
make all
./build/Choano-native
make web
python3 -m http.server --directory build/web
```

`EMCC` may point to Emscripten's `emcc`; otherwise the browser builder uses
`~/emsdk/upstream/emscripten/emcc` or `emcc` from PATH. `make all` produces
`build/Choano-native` and `build/choano.zx`. Window tests use only a fresh
private Xvfb display; browser tests use a disposable headless Chromium profile.
`make input-test` exercises the actual Frame and a portable game through the
current Apps host. If Ziran is installed through a launcher, set `ZIRAN_ROOT`
to its existing build tree (or `ZIRAN_LIB` to its `build/libziran.a`).

Movement reads Kryon’s owned frame snapshot on desktop, Windows, browser and
compatible portable hosts. Keyboard shortcuts and text keep their existing
event queues; the floating stick, simulation clock and tick clamp are unchanged.
The portable source now requires a host with `frame_snapshot.CaptureFrameInputHost`;
Arcade 0.7.113 does not provide it. A new portable release must wait for a
compatible host.

## Linux AppImage

`make appimage` rebuilds the native game and packs it with its libraries and
art into `build/Choano.AppImage`; `--use-built-native` on
`scripts/desktop_release.py appimage` packs the existing build instead. The
pinned linuxdeploy tools are downloaded once into ignored `work/tools` and
checked against their SHA-256. `make appimage-test` unpacks the image, checks
its assets and libraries, and plays it in both modes on a private Xvfb display
through `APPIMAGE_EXTRACT_AND_RUN`, without FUSE. Releases name it
`choano-vVERSION-linux-x86_64.AppImage`.

## Windows installer

`python3 scripts/desktop_release.py windows` builds `build/Choano-setup.exe`.
`src/windows.zi` runs the same game Frame on Kryon's raylib host (RGFW, OpenGL
1.1, JPEG titles and raylib audio for the chimes and shark loop), linked
statically with MinGW-w64 from the locked Ziran runtime and raylib; the build
keeps its intermediates in `build/windows`. NSIS (`makensis`) packs the
program, Kryon's Liberation Sans and every asset into a per-user installer:
no administrator rights, Start menu and desktop shortcuts, and an uninstall
entry in the player's own registry. Settings live in
`%LOCALAPPDATA%\Choano` and stay after uninstalling. The installer is not
Authenticode-signed. `python3 tests/windows_release_test.py` installs it
silently in a private Wine prefix under `work/`, plays it on a private Xvfb
display against the native build's title screens, saves its settings and
uninstalls it. Releases name it `choano-vVERSION-windows-x86_64-setup.exe`.

## Android

`make android` builds the unsigned release APK on Kryon's Android host and
`make android-gplay` the Google Play edition's. They need JDK 21 and the
Android SDK's NDK 28.2.13676358, build-tools 36.0.0, android-36 and CMake
3.22.1; Gradle's project is generated in ignored `droid/` from the locked
Kryon. `python3 scripts/android.py sign APK --output FILE` signs with the
ignored `backup/android-signing` key and verifies the package, both ARM
architectures, the bundled art and the Choano certificate.

The Android workflow builds `choano-vVERSION.apk`, the same Google-free build
as `choano-VERSION-fdroid.apk`, and `choano-vVERSION-gplay.apk`, the only one
with a Google library (Play Billing). It checks both editions with Kryon's
`google-free` action and signs them with the `CHOANO_ANDROID_KEYSTORE` and
`CHOANO_ANDROID_KEYSTORE_PASSWORD` secrets.

## Releases

`VERSION` and the newest numbered `CHANGELOG.md` entry name the release, 0.1.0
first; `python3 scripts/release.py assets` lists its five files: the normal,
F-Droid and Google Play APKs, the Linux AppImage and the Windows installer.
Nothing is submitted to a store.

## Independent game package

`apps.json` and `catalog.json` declare Choano's stable identity
`xyz.waozi.choano`, portable entry and cover artwork. The portable edition uses
`apps/node_app`, the generic `kryonlabs/game2d` navigation/control modules,
and Entity's `game_progress` schema through bounded host
services. Hosts own account keys, record IDs, storage and synchronization.
Arcade is a consumer/catalog of this package and is not a Choano dependency.
This repository does not change Arcade's catalog or publish a signed node package.

## Website delivery

The Choano GitHub Actions workflow tests the native and portable game, builds
the browser edition with the locked shared Entity provider, and exercises
swimming, Profile/Back, restart and reload in headless Chromium. Successful
master builds deploy to the Cloudflare Pages project `choano` and connect
`choano.waozi.xyz`. Repository secrets `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` configure deployment; credentials are never committed.
