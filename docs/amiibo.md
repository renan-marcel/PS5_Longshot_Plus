# Virtual amiibo

The game has amiibo rewards: touch a figure to its reader and it gives something. On the PS5 there is no reader, so
Longshot Plus has a virtual one. The game's own `nn::nfp` calls are answered by the amiibo core (`host/amiibo_core.h`,
`host/nn_nfp.c`) from a figure chosen in the in-game menu, and the game gives the figure's rewards as on a Switch. No
real figure, dump or key is involved.

The design is in [the spec](superpowers/specs/2026-11-26-amiibo-design.md); which `nn::nfp` functions the game imports is
in [amiibo-nfp-calls.md](amiibo-nfp-calls.md).

## Building with Download amiibo

The figures' names and pictures are not shipped. The builder downloads them on your PC, when you ask:

- In the builder's window, tick **Download amiibo**. On the command line, add `--amiibo` (`python -I ps5/builder/pipeline.py ... --amiibo`).
- It is the build's eighth step, "Downloading the amiibo". The download (about 151 MB, from AmiiboAPI) is made once and
  kept in `amiibo-cache` in the build's work folder, so the next build does not repeat it. The title folder gets
  `amiibo/amiibo.idx` and `amiibo/figures.pak`, about 42 MB.
- It needs the Python package `pillow` on the PC (to make the pictures); the builder's check says whether it loads.
- If the download fails, the build goes on with one warning and the title has no `amiibo/`: the Amiibo tab then says
  "No amiibo catalogue: build again with Download amiibo ticked."

## The Amiibo tab

Open the menu (touch pad's click and Options together) and go to the **Amiibo** tab.

| Row | Default | What it does |
|---|---|---|
| **Amiibo emulation** | On | The game finds an amiibo reader and reads the figure chosen below. Off: the game finds no reader, as on a Switch without one. |
| **Series** | All | Which series the Figure row lists: All, or one series. The Legend of Zelda comes first. |
| **Figure** | none until chosen | The figure the game reads when it asks for an amiibo. Left and Right choose; its picture is beside the list. |
| **Surprise me** | | Picks a figure of the series at random. |
| **Random tag ID** | On | Each read is a new figure with a tag ID of its own, so the game lets the same figure be used again. Off: the figure keeps one ID. |
| **Touch when the game asks** | On | The figure is put on the reader as soon as the game looks for one, and taken off when the game stops looking. |
| **Touch / Remove** | | Puts the figure on the reader, or takes it off: for a game that asks you to remove the figure, or with Touch when the game asks off. |

The chosen figure is saved by its ID in `longshot_options.ini` (`amiibo_figure_id=...`), together with the other rows.

**Random tag ID** is for a figure used again and again. A game may remember a figure's tag ID and refuse a reward it
already gave to it (whether Ocarina of Time does is still to be tested on the PS5); with the option on, every read shows
a new tag ID, so the figure would be taken as a new one each time.
The game's data for the figure (its application area) stays the figure's own.

## Where the data is kept

In the title folder on the PS5:

- `user/amiibo/<amiibo id>/<access id>.bin`: what the game wrote to the figure's application area, one file per game
  area.
- `user/amiibo/<amiibo id>/state.txt`: the figure's write counter and dates.
- `logs/nfp.txt`: the `[NFP]` lines the host adds as it answers the game's calls (up to 1 MB a run). On the PC they are
  in `logs/longshot_log.txt`.

`user/` is the folder the save-data advice covers: back it up before updating.

## Limits

- The three amiibo-settings applet calls (`StartNicknameAndOwnerSettings`, `StartGameDataEraser`, `StartRestorer`) are
  answered as "the applet closed, nothing changed" and logged; the figure's registration is always answered, so the
  applet should not be needed.
- The layout of `ApplicationAreaCreateInfo` is still to be confirmed in the game.
- The Amiibo tab's text is English only for now: it is not in the menu's translations (gpu/vk/menu_i18n.h) yet.

## Privacy

The pictures are downloaded on your PC, into your own title folder, and never shared. Nothing here needs amiibo keys,
real figures or dumps of them. The names and pictures are Nintendo's: they stay on your PC and console, and are not
part of the repository or of a release.

## Credits

- [AmiiboAPI](https://github.com/N3evin/AmiiboAPI) (N3evin, MIT): the database of figures and the pictures source,
  downloaded at build time, not shipped.
- Fritchii (Frizti, GPLv3): the NFC code the core's rules and layouts were adapted from.
- [emuiibo](https://github.com/XorTroll/emuiibo) (XorTroll): a reference for how a virtual amiibo should behave; no code
  was taken from it.
