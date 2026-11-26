# Apple Music tools

Control the Music app on this Mac from the command line (`./am`) or from an AI client (`mcp_server.py`).
Needs macOS and Python 3. Local commands need no packages or sign-in; `cloud` needs both.

    ./am -h                                  # all commands
    ./am playlists
    ./am search "take on me"
    ./am playlist-tracks "luh"
    ./am create-playlist "Road Trip"
    ./am add-to-playlist "Road Trip" TRACK_ID TRACK_ID
    ./am remove-from-playlist "Road Trip" TRACK_ID          # preview
    ./am remove-from-playlist "Road Trip" TRACK_ID --yes    # do it
    ./am delete-playlist "Road Trip" --yes
    ./am import-files song.mp3 --playlist "Road Trip"
    ./am update-track TRACK_ID --set rating=80 --set favorited=true
    ./am delete-from-library TRACK_ID --yes
    ./am playback play --playlist "luh"
    ./am catalog-search "artist song"
    ./am browse most_played                  # also recently_added, favorites, duplicates, artists...
    ./am copy-playlist "luh" "luh sorted" --sort-by artist
    ./am move-playlist "Road Trip" "King"
    ./am playback --position 30
    ./am airplay --devices "Speaker Name"
    ./am download TRACK_ID
    ./am artwork TRACK_ID cover.jpg
    ./am backup
    ./am list-backups
    ./am restore-playlist BACKUP_FOLDER_OR_JOURNAL_FILE --playlist "luh"

## Apple Music online (`./am cloud`)

Uses the open-source [applemusic-mcp](https://github.com/epheterson/applemusic-mcp) (MIT) with your own
subscription. It is unofficial and may stop working if Apple changes its website.

One-time setup:

1. `pipx install applemusic-mcp==0.22.1`
2. Safari: sign in at music.apple.com. In Settings > Advanced turn on web developer features,
   then turn on Develop > Allow JavaScript from Apple Events.
3. `applemusic-mcp login`, then turn that Safari setting off again.

Examples:

    ./am cloud                                       # list online tools
    ./am cloud catalog                               # help for one tool
    ./am cloud catalog search "query=maher zain" limit=5
    ./am cloud library add track=CATALOG_ID
    ./am cloud discover recommendations
    ./am cloud discover charts

Delete, remove, logout, reset and clear actions, and any `replace=`, need `--yes`. They are not journalled, so run
`./am backup` first. To sign out: `applemusic-mcp logout`.

Agents: read `AGENTS.md` first.

## Use from Claude Code

Run from this folder (re-run if you move it):

    claude mcp add apple-music -- python3 "$PWD/mcp_server.py"

## Safety

- Deletes and removals only preview unless you pass `--yes` (`confirm: true` over MCP).
- Before a confirmed delete or removal, and after an edit or rename, a record is saved in
  `~/Music/AppleMusicBackups/journal/`.
- `restore-playlist` always makes a new playlist. It does not overwrite, rebuild folders or smart rules.
- A preview lists `onlyInThisPlaylist`: songs found nowhere else, which restore cannot bring back.
- Deleting from the library cannot be undone by these tools. Music may ask you to confirm in a dialog.

## Limits

The local commands use only the Music app's official scripting interface (no UI clicking), which does not offer the items below (`cloud` covers some):

- adding catalog songs to your library
- Play Next, the Up Next queue, stations, recommendations, charts or share links
- creating or editing smart playlists, or moving a playlist out of a folder
- changing the equalizer (it can only be read)

- "Create song" means importing an audio file. These tools do not compose music.
- Catalog songs can be searched and opened, but you press + in Music to add them.
- Smart, folder and system playlists cannot have songs added or removed.
- `./am backup --copy-files` also copies the library database; quit Music first.
