"""Shared logic for the CLI (am) and the MCP server."""
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from cloud import cloud

HERE = Path(__file__).resolve().parent
BACKUPS = Path(os.environ.get("AM_BACKUP_DIR", "~/Music/AppleMusicBackups")).expanduser()
LIBRARY_DIRS = [
    Path("~/Music/Music/Music Library.musiclibrary").expanduser(),
    Path("~/Music/Music/Previous Libraries.localized").expanduser(),
]


class MusicError(Exception):
    pass


def jxa(op, timeout=600, **args):
    payload = json.dumps({"op": op, **args})
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", str(HERE / "music.js"), payload],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise MusicError(f"Music did not answer within {timeout}s; check for a dialog in the app")
    if proc.returncode != 0:
        raise MusicError(proc.stderr.strip() or "osascript failed")
    reply = json.loads(proc.stdout)
    if not reply["ok"]:
        raise MusicError(reply["error"])
    return reply["result"]


def stamp():
    return dt.datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")


def journal(op, data):
    """Keep a record of what a change replaced or removed."""
    folder = BACKUPS / "journal"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp()}_{op}.json"
    path.write_text(json.dumps({"op": op, "data": data}, indent=2, ensure_ascii=False))
    return str(path)


# ---- backup ---------------------------------------------------------------

def backup(into=None, copy_files=False):
    """Export every track and playlist to JSON and CSV. Optionally copy the library files."""
    folder = Path(into).expanduser() if into else BACKUPS / stamp()
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "library.json").exists():
        raise MusicError(f"{folder} already holds a backup")
    if copy_files:
        if subprocess.run(["/usr/bin/pgrep", "-x", "Music"], capture_output=True).returncode == 0:
            raise MusicError("Quit Music before copying library files (a live database may copy badly)")
        for src in LIBRARY_DIRS:
            if src.exists():
                shutil.copytree(src, folder / "library-files" / src.name, symlinks=True)
    data = jxa("export_all", timeout=900)
    data["exportedAt"] = dt.datetime.now().astimezone().isoformat()
    (folder / "library.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))

    def write_csv(path, rows):
        if not rows:
            return
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    write_csv(folder / "all-tracks.csv", data["tracks"])
    (folder / "playlists").mkdir(exist_ok=True)
    for p in data["playlists"]:
        safe = re.sub(r"[/:\x00]", "-", p["name"]).strip()[:80] or "untitled"
        write_csv(folder / "playlists" / f"{safe} [{p['persistentID']}].csv", p["tracks"])
    return {
        "folder": str(folder),
        "tracks": len(data["tracks"]),
        "playlists": [{"name": p["name"], "tracks": len(p["tracks"])} for p in data["playlists"]],
    }


def list_backups():
    if not BACKUPS.exists():
        return []
    found = [p.parent for p in BACKUPS.glob("*/library.json")]
    found += [p for p in (BACKUPS / "journal").glob("*.json")]
    return sorted(str(p) for p in found)


def _snapshots(source):
    """Playlists stored in a full backup folder or a journal file."""
    path = Path(source).expanduser()
    if path.is_dir():
        path = path / "library.json"
    data = json.loads(path.read_text())
    if "playlists" in data:
        return data["playlists"]
    inner = data.get("data", {})
    for key in ("deleted", "snapshot"):
        if isinstance(inner.get(key), dict) and "tracks" in inner[key]:
            return [inner[key]]
    raise MusicError("That file holds no playlist to restore")


def restore_playlist(source, playlist=None, new_name=None):
    """Recreate a playlist from a backup as a NEW playlist; never overwrites."""
    options = _snapshots(source)
    if playlist:
        options = [p for p in options if playlist in (p["name"], p["persistentID"])]
    if len(options) != 1:
        raise MusicError("Name exactly one playlist to restore (by name or ID)")
    old = options[0]
    name = new_name or f"{old['name']} (restored {dt.datetime.now():%Y-%m-%d %H.%M.%S})"
    have = set(jxa("available_ids"))
    wanted = [t["persistentID"] for t in old["tracks"]]
    usable = [i for i in wanted if i in have]
    made = jxa("create_playlist", name=name, description=old.get("description"))
    if usable:
        jxa("add_to_playlist", timeout=900, playlist=made["persistentID"], ids=usable,
            allow_duplicates=True)
    return {
        "restoredAs": name,
        "persistentID": made["persistentID"],
        "tracksRestored": len(usable),
        "tracksUnavailable": [t for t in old["tracks"] if t["persistentID"] not in have],
    }


# ---- changes (journalled) -------------------------------------------------

def _destructive(op, **args):
    confirm = args.pop("confirm")
    result = jxa(op, **args, confirm=False)
    if not confirm:
        return result
    saved = journal(op + "_before", _restorable(op, args, result))
    done = jxa(op, **args, confirm=True)
    done.pop("snapshot", None)
    done["journal"] = saved
    return done


def _restorable(op, args, preview):
    if op == "delete_playlist":
        return {"deleted": preview["wouldDelete"]}
    if op == "remove_from_playlist":
        full = jxa("playlist_tracks", playlist=args["playlist"])
        return {"snapshot": {**full["playlist"], "tracks": full["tracks"]}, "removing": args["ids"]}
    return preview


def delete_playlist(playlist, confirm=False):
    return _destructive("delete_playlist", playlist=playlist, confirm=confirm)


def remove_from_playlist(playlist, ids, confirm=False):
    return _destructive("remove_from_playlist", playlist=playlist, ids=ids, confirm=confirm)


def delete_from_library(ids, confirm=False):
    return _destructive("delete_from_library", ids=ids, confirm=confirm)


def update_track(id, fields):
    result = jxa("update_track", id=id, fields=fields)
    result["journal"] = journal("update_track", result)
    return result


def rename_playlist(playlist, name=None, description=None, favorited=None, disliked=None):
    result = jxa("rename_playlist", playlist=playlist, name=name, description=description,
                 favorited=favorited, disliked=disliked)
    result["journal"] = journal("rename_playlist", result)
    return result


def import_files(paths, playlist=None):
    full = []
    for p in paths:
        f = Path(p).expanduser().resolve()
        if not f.is_file():
            raise MusicError(f"Not a file: {f}")
        full.append(str(f))
    return jxa("import_files", paths=full, playlist=playlist)


def artwork(id, file, set=False):
    path = Path(file).expanduser().resolve()
    if set and not path.is_file():
        raise MusicError(f"Not a file: {path}")
    if not set and path.exists():
        raise MusicError(f"{path} already exists")
    proc = subprocess.run(
        ["/usr/bin/osascript", str(HERE / "artwork.applescript"), "set" if set else "get", id, str(path)],
        capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise MusicError(proc.stderr.strip())
    return {"id": id, "file": str(path), "result": proc.stdout.strip()}


# ---- Apple Music catalog (public iTunes Search API, no sign-in) -----------

def catalog_search(query, limit=10, country="US"):
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": query, "media": "music", "entity": "song", "limit": limit, "country": country})
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.load(r)
    return [{"name": s.get("trackName"), "artist": s.get("artistName"),
             "album": s.get("collectionName"), "url": s.get("trackViewUrl")}
            for s in data["results"]]


def open_in_music(url):
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or parts.hostname != "music.apple.com":
        raise MusicError("Only https://music.apple.com/ links can be opened")
    subprocess.run(["/usr/bin/open", "-a", "Music", url], check=True)
    return {"opened": url, "note": "Press + in Music to add it to your library"}


# ---- tool registry: one definition drives both the CLI and MCP ------------

def S(desc):
    return {"type": "string", "description": desc}


IDS = {"type": "array", "items": {"type": "string"}, "description": "Track persistent IDs"}
PL = S("Playlist name or persistent ID")
CONFIRM = {"type": "boolean", "description": "false (default) only previews; true makes the change"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}


def _op(name):
    return lambda **a: jxa(name, **a)


# name: (function, description, properties, required, positional-args)
TOOLS = {
    "status": (_op("status"), "Library size and Music version", {}, [], []),
    "search": (_op("search"), "Search songs in your library",
               {"query": S("Words matched against title, artist and album"), "name": S("Title contains"),
                "artist": S("Artist contains"), "album": S("Album contains"),
                "genre": S("Genre contains"), "limit": INT}, [], ["query"]),
    "get_track": (_op("get_track"), "All details of one song and which playlists hold it",
                  {"id": S("Track persistent ID")}, ["id"], ["id"]),
    "playlists": (_op("playlists"), "List all playlists", {}, [], []),
    "playlist_tracks": (_op("playlist_tracks"), "Songs in a playlist, in order",
                        {"playlist": PL}, ["playlist"], ["playlist"]),
    "create_playlist": (_op("create_playlist"), "Create a playlist or playlist folder",
                        {"name": S("Name"), "description": S("Description"),
                         "folder": S("Folder to put it in"), "is_folder": BOOL}, ["name"], ["name"]),
    "rename_playlist": (rename_playlist, "Rename a playlist, change its description or favorite it",
                        {"playlist": PL, "name": S("New name"), "description": S("New description"),
                         "favorited": BOOL, "disliked": BOOL},
                        ["playlist"], ["playlist"]),
    "move_playlist": (_op("move_playlist"), "Move a playlist into a folder",
                      {"playlist": PL, "folder": S("Folder name or ID")},
                      ["playlist", "folder"], ["playlist", "folder"]),
    "copy_playlist": (_op("copy_playlist"), "Copy a playlist, optionally sorted, shuffled or de-duplicated",
                      {"playlist": PL, "name": S("Name of the new playlist"),
                       "sort_by": {"type": "string", "enum": ["name", "artist", "album", "year",
                                   "duration", "dateAdded", "playedCount", "trackNumber"]},
                       "reverse": BOOL, "shuffle": BOOL, "dedupe": BOOL},
                      ["playlist", "name"], ["playlist", "name"]),
    "delete_playlist": (delete_playlist, "Delete a playlist (songs stay in the library)",
                        {"playlist": PL, "confirm": CONFIRM}, ["playlist"], ["playlist"]),
    "add_to_playlist": (_op("add_to_playlist"), "Add library songs to a playlist",
                        {"playlist": PL, "ids": IDS, "allow_duplicates": BOOL},
                        ["playlist", "ids"], ["playlist", "ids"]),
    "remove_from_playlist": (remove_from_playlist, "Remove songs from a playlist (all copies of each)",
                             {"playlist": PL, "ids": IDS, "confirm": CONFIRM},
                             ["playlist", "ids"], ["playlist", "ids"]),
    "import_files": (import_files, "Create library songs from audio files on this Mac",
                     {"paths": {"type": "array", "items": {"type": "string"}}, "playlist": PL},
                     ["paths"], ["paths"]),
    "update_track": (update_track, "Edit song details, rating or favorite",
                     {"id": S("Track persistent ID"),
                      "fields": {"type": "object", "description":
                                 "e.g. {\"name\": \"x\", \"rating\": 80, \"favorited\": true}"}},
                     ["id", "fields"], ["id"]),
    "delete_from_library": (delete_from_library, "Permanently delete songs from the library",
                            {"ids": IDS, "confirm": CONFIRM}, ["ids"], ["ids"]),
    "now_playing": (_op("now_playing"), "What is playing", {}, [], []),
    "playback": (_op("playback"), "Control playback",
                 {"action": {"type": "string",
                             "enum": ["play", "pause", "toggle", "stop", "next", "previous", "restart",
                                      "resume", "fast_forward", "rewind"]},
                  "position": {"type": "integer", "description": "Seek to this second"}, "mute": BOOL,
                  "shuffle_mode": {"type": "string", "enum": ["songs", "albums", "groupings"]},
                  "id": S("Song to play"), "playlist": PL, "volume": INT, "shuffle": BOOL,
                  "repeat": {"type": "string", "enum": ["off", "one", "all"]}}, [], ["action"]),
    "browse": (_op("browse"), "Library views: recents, most played, favorites, duplicates, artists...",
               {"view": {"type": "string", "enum": ["recently_added", "recently_played", "most_played",
                         "most_skipped", "top_rated", "favorites", "disliked", "never_played",
                         "duplicates", "artists", "albums", "genres"]}, "limit": INT}, [], ["view"]),
    "airplay": (_op("airplay"), "List or choose speakers and set their volume",
                {"devices": {"type": "array", "items": {"type": "string"}, "description": "Play on these"},
                 "device": S("Device whose volume to set"), "volume": INT}, [], []),
    "equalizer": (_op("equalizer"), "Show equalizer state and presets (read-only)", {}, [], []),
    "download": (_op("download"), "Download songs for offline play", {"ids": IDS}, ["ids"], ["ids"]),
    "artwork": (artwork, "Save a song's cover art to a file, or set it from a file",
                {"id": S("Track persistent ID"), "file": S("Image path"), "set": BOOL},
                ["id", "file"], ["id", "file"]),
    "reveal": (_op("reveal"), "Show a song or playlist in the Music window",
               {"id": S("Track persistent ID"), "playlist": PL}, [], []),
    "selection": (_op("selection"), "Songs currently selected in the Music window", {}, [], []),
    "open_stream": (_op("open_stream"), "Play an internet radio stream link", {"url": S("http(s) link")},
                    ["url"], ["url"]),
    "cloud": (cloud, "Apple Music online: catalog, add to library, recommendations, charts. "
              "Run with no arguments to list tools; give a service only to see its help. Needs sign-in",
              {"service": S("playlist, library, discover, catalog, config or playback"),
               "action": S("Action of that tool"),
               "params": {"type": "array", "items": {"type": "string"}, "description": "key=value pairs"},
               "confirm": CONFIRM}, [], ["service", "action", "params"]),
    "catalog_search": (catalog_search, "Search the Apple Music catalog (sends the query to Apple)",
                       {"query": S("Search words"), "limit": INT, "country": S("Two-letter store")},
                       ["query"], ["query"]),
    "open_in_music": (open_in_music, "Open a catalog link in Music so it can be added",
                      {"url": S("music.apple.com link")}, ["url"], ["url"]),
    "backup": (backup, "Export all songs and playlists to a new backup folder",
               {"into": S("Folder (optional)"), "copy_files": BOOL}, [], []),
    "list_backups": (list_backups, "List backups and change journals", {}, [], []),
    "restore_playlist": (restore_playlist, "Recreate a playlist from a backup as a new playlist",
                         {"source": S("Backup folder or journal file"), "playlist": PL,
                          "new_name": S("Name for the restored copy")}, ["source"], ["source"]),
}


def call(name, args):
    if name not in TOOLS:
        raise MusicError(f"Unknown tool {name}")
    fn, _, props, required, _ = TOOLS[name]
    unknown = set(args) - set(props)
    missing = [r for r in required if args.get(r) in (None, "", [])]
    if unknown or missing:
        raise MusicError(f"Bad arguments. Unknown: {sorted(unknown)}; missing: {missing}")
    for key, value in args.items():
        kind = props[key].get("type")
        expected = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}[kind]
        if value is not None and not isinstance(value, expected):
            raise MusicError(f"{key} must be of type {kind}")
        if kind == "array" and value and not all(isinstance(v, str) for v in value):
            raise MusicError(f"{key} must be a list of strings")
    return fn(**args)
