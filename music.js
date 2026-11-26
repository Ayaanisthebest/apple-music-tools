// JXA backend. Usage: osascript -l JavaScript music.js '{"op": "...", ...}'
// Prints one JSON object: {"ok": true, "result": ...} or {"ok": false, "error": "..."}.

const M = Application("Music");

const BRIEF = ["persistentID", "name", "artist", "album", "duration"];
const FULL = BRIEF.concat([
  "albumArtist", "composer", "genre", "year", "trackNumber", "trackCount",
  "discNumber", "discCount", "rating", "favorited", "disliked", "playedCount",
  "playedDate", "skippedCount", "dateAdded", "releaseDate", "comment",
  "grouping", "bpm", "lyrics", "kind", "cloudStatus", "enabled", "compilation"
]);
const EDITABLE = ["name", "artist", "albumArtist", "album", "composer", "genre", "year",
  "trackNumber", "trackCount", "discNumber", "discCount", "rating", "favorited",
  "disliked", "comment", "grouping", "bpm", "lyrics", "enabled", "compilation",
  "albumRating", "albumFavorited", "albumDisliked", "playedCount", "skippedCount",
  "volumeAdjustment", "start", "finish", "shufflable", "bookmarkable", "gapless", "EQ",
  "sortName", "sortArtist", "sortAlbum", "sortAlbumArtist", "sortComposer",
  "work", "movement", "movementNumber", "movementCount"];

function attempt(fn, fallback) { try { return fn(); } catch (e) { return fallback; } }

function library() { return M.libraryPlaylists[0]; }

// Read many properties for a whole track collection with one Apple event per property.
function table(tracks, props) {
  if (tracks.length === 0) return [];
  const cols = {};
  const n = tracks.persistentID().length;
  props.forEach(p => {
    let col = attempt(() => tracks[p](), null);
    if (!col || col.length !== n) {
      col = [];
      for (let i = 0; i < n; i++) col.push(attempt(() => tracks[i][p](), null));
    }
    cols[p] = col;
  });
  const rows = [];
  for (let i = 0; i < n; i++) {
    const row = {};
    props.forEach(p => row[p] = cols[p][i]);
    rows.push(row);
  }
  return rows;
}

function inLibrary(id) { return library().tracks.whose({ persistentID: id }).length > 0; }

// Some playlist songs are not in the library, so fall back to searching playlists.
function trackByID(id) {
  const m = library().tracks.whose({ persistentID: id });
  if (m.length) return m[0];
  const all = M.userPlaylists;
  for (let i = 0; i < all.length; i++) {
    const hit = all[i].tracks.whose({ persistentID: id });
    if (hit.length) return hit[0];
  }
  throw new Error("No song in the library or any playlist has ID " + id);
}

function playlistInfo(p) {
  const cls = p.class();
  const info = {
    persistentID: p.persistentID(),
    name: p.name(),
    class: cls,
    specialKind: attempt(() => p.specialKind(), "none"),
    smart: attempt(() => p.smart(), false),
    parentID: attempt(() => p.parent().persistentID(), null),
    description: attempt(() => p.description(), null),
    favorited: attempt(() => p.favorited(), null)
  };
  info.editable = cls === "userPlaylist" && !info.smart && info.specialKind === "none";
  return info;
}

// Accepts a persistent ID or an exact name. Refuses ambiguous names.
function findPlaylist(ref) {
  if (!ref) throw new Error("Playlist is required");
  let m = M.playlists.whose({ persistentID: ref });
  if (m.length === 0) m = M.playlists.whose({ name: ref });
  const found = [];
  for (let i = 0; i < m.length; i++) found.push(m[i]);
  if (found.length === 0) throw new Error("No playlist matches '" + ref + "'");
  const ids = found.map(p => p.persistentID()).filter((v, i, a) => a.indexOf(v) === i);
  if (ids.length > 1) throw new Error("Several playlists are named '" + ref + "'. Use an ID: " + ids.join(", "));
  return found[0];
}

function editablePlaylist(ref) {
  const p = findPlaylist(ref);
  const info = playlistInfo(p);
  if (!info.editable) throw new Error("'" + info.name + "' is a smart, folder or system playlist; its tracks cannot be edited");
  return { p: p, info: info };
}

function ids(p) { return p.tracks.length ? p.tracks.persistentID() : []; }

const OPS = {
  status() {
    return {
      version: M.version(),
      libraryTracks: library().tracks.length,
      playlists: M.playlists.length
    };
  },

  playlists() {
    const out = [];
    const all = M.playlists;
    for (let i = 0; i < all.length; i++) {
      const info = playlistInfo(all[i]);
      info.trackCount = all[i].tracks.length;
      out.push(info);
    }
    return out;
  },

  playlist_tracks(a) {
    const p = findPlaylist(a.playlist);
    return { playlist: playlistInfo(p), tracks: table(p.tracks, BRIEF) };
  },

  search(a) {
    const words = String(a.query || "").toLowerCase().split(/\s+/).filter(Boolean);
    const rows = table(library().tracks, BRIEF.concat(["albumArtist", "genre"]));
    const has = (v, q) => !q || String(v || "").toLowerCase().indexOf(String(q).toLowerCase()) >= 0;
    const hits = rows.filter(r => {
      const text = [r.name, r.artist, r.album, r.albumArtist].join(" ").toLowerCase();
      return words.every(w => text.indexOf(w) >= 0) &&
        has(r.name, a.name) && has(r.artist, a.artist) && has(r.album, a.album) && has(r.genre, a.genre);
    });
    const limit = a.limit || 50;
    return { total: hits.length, tracks: hits.slice(0, limit) };
  },

  get_track(a) {
    const t = trackByID(a.id);
    const row = {};
    FULL.forEach(p => row[p] = attempt(() => t[p](), null));
    row.inLibrary = inLibrary(a.id);
    row.playlists = [];
    const all = M.userPlaylists;
    for (let i = 0; i < all.length; i++) {
      if (all[i].tracks.whose({ persistentID: a.id }).length) row.playlists.push(all[i].name());
    }
    return row;
  },

  available_ids() {
    const seen = {};
    const all = M.playlists;
    for (let i = 0; i < all.length; i++) ids(all[i]).forEach(id => seen[id] = true);
    return Object.keys(seen);
  },

  export_all() {
    const tracks = table(library().tracks, FULL);
    const playlists = [];
    const all = M.playlists;
    for (let i = 0; i < all.length; i++) {
      const info = playlistInfo(all[i]);
      info.tracks = table(all[i].tracks, BRIEF);
      playlists.push(info);
    }
    return { musicVersion: M.version(), tracks: tracks, playlists: playlists };
  },

  create_playlist(a) {
    if (!a.name) throw new Error("name is required");
    if (M.playlists.whose({ name: a.name }).length) throw new Error("A playlist named '" + a.name + "' already exists");
    let folder = null;
    if (a.folder) {
      folder = findPlaylist(a.folder);
      if (folder.class() !== "folderPlaylist") throw new Error("'" + a.folder + "' is not a folder");
    }
    const props = { name: a.name };
    if (a.description) props.description = a.description;
    M.make({ new: a.is_folder ? "folderPlaylist" : "playlist", withProperties: props });
    if (folder) M.move(findPlaylist(a.name), { to: folder });
    return playlistInfo(findPlaylist(a.name));
  },

  rename_playlist(a) {
    const p = findPlaylist(a.playlist);
    const info = playlistInfo(p);
    if (info.specialKind !== "none" && info.class !== "folderPlaylist") throw new Error("System playlists cannot be changed");
    if (info.class === "libraryPlaylist") throw new Error("The library cannot be renamed");
    const id = info.persistentID;
    if (a.name) p.name = a.name;
    if (a.description !== undefined && a.description !== null) findPlaylist(id).description = a.description;
    if (a.favorited !== undefined && a.favorited !== null) findPlaylist(id).favorited = a.favorited;
    if (a.disliked !== undefined && a.disliked !== null) findPlaylist(id).disliked = a.disliked;
    return { before: info, after: playlistInfo(findPlaylist(id)) };
  },

  delete_playlist(a) {
    const p = findPlaylist(a.playlist);
    const info = playlistInfo(p);
    if (info.class !== "userPlaylist" && info.class !== "folderPlaylist") throw new Error("This playlist cannot be deleted");
    if (info.class === "userPlaylist" && info.specialKind !== "none") throw new Error("System playlists cannot be deleted");
    if (info.class === "folderPlaylist") {
      const all = M.userPlaylists;
      for (let i = 0; i < all.length; i++) {
        if (attempt(() => all[i].parent().persistentID(), null) === info.persistentID)
          throw new Error("Folder is not empty. Delete or move its playlists first");
      }
    }
    info.tracks = table(p.tracks, BRIEF);
    if (!a.confirm) {
      const elsewhere = {};
      const others = M.playlists;
      for (let i = 0; i < others.length; i++) {
        if (others[i].persistentID() === info.persistentID) continue;
        ids(others[i]).forEach(id => elsewhere[id] = true);
      }
      return { preview: true, wouldDelete: info, onlyInThisPlaylist: info.tracks.filter(r => !elsewhere[r.persistentID]) };
    }
    M.delete(p);
    return { deleted: info };
  },

  add_to_playlist(a) {
    const target = editablePlaylist(a.playlist);
    const tracks = a.ids.map(trackByID);   // resolve all first so a bad ID changes nothing
    const present = ids(target.p);
    const added = [], skipped = [];
    tracks.forEach((t, i) => {
      const id = a.ids[i];
      if (!a.allow_duplicates && present.indexOf(id) >= 0) { skipped.push(id); return; }
      M.duplicate(t, { to: target.p });
      present.push(id);
      added.push(id);
    });
    return { playlist: target.info.name, added: added, skippedAlreadyThere: skipped, trackCount: target.p.tracks.length };
  },

  remove_from_playlist(a) {
    const target = editablePlaylist(a.playlist);
    const before = table(target.p.tracks, BRIEF);
    const wanted = a.ids;
    const missing = wanted.filter(id => !before.some(r => r.persistentID === id));
    if (missing.length) throw new Error("Not in this playlist: " + missing.join(", "));
    const matches = before.filter(r => wanted.indexOf(r.persistentID) >= 0);
    const snapshot = Object.assign({}, target.info, { tracks: before });
    // Songs that exist nowhere else cannot be brought back by restore.
    const elsewhere = {};
    const all = M.playlists;
    for (let i = 0; i < all.length; i++) {
      if (all[i].persistentID() === target.info.persistentID) continue;
      ids(all[i]).forEach(id => elsewhere[id] = true);
    }
    const onlyHere = matches.filter(r => !elsewhere[r.persistentID]);
    if (!a.confirm) return { preview: true, playlist: target.info.name, wouldRemove: matches, onlyInThisPlaylist: onlyHere };
    // Highest position first so earlier positions stay valid.
    for (let i = before.length - 1; i >= 0; i--) {
      if (wanted.indexOf(before[i].persistentID) < 0) continue;
      const t = target.p.tracks[i];
      if (t.persistentID() !== before[i].persistentID) throw new Error("Playlist changed during removal; stopped");
      M.delete(t);
    }
    return { playlist: target.info.name, removed: matches, trackCount: target.p.tracks.length, snapshot: snapshot };
  },

  delete_from_library(a) {
    const outside = a.ids.filter(id => !inLibrary(id));
    if (outside.length) throw new Error("Not in the library: " + outside.join(", "));
    const found = a.ids.map(id => OPS.get_track({ id: id }));
    if (!a.confirm) return { preview: true, wouldDeleteFromLibrary: found };
    a.ids.forEach(id => M.delete(library().tracks.whose({ persistentID: id })[0]));
    delay(2);
    const still = found.filter(t => inLibrary(t.persistentID));
    return {
      deleted: found.filter(t => still.indexOf(t) < 0),
      stillInLibrary: still,
      note: still.length ? "Music may be showing a confirmation dialog. Answer it, then search again." : undefined
    };
  },

  import_files(a) {
    const target = a.playlist ? editablePlaylist(a.playlist) : null;
    const results = a.paths.map(path => {
      const added = M.add([Path(path)], { to: library() });
      if (!added) return { path: path, error: "Music did not import this file" };
      const t = Array.isArray(added) ? added[0] : added;
      const id = t.persistentID();
      if (target) M.duplicate(trackByID(id), { to: target.p });
      return { path: path, persistentID: id, name: t.name() };
    });
    return { imported: results };
  },

  update_track(a) {
    const t = trackByID(a.id);
    const keys = Object.keys(a.fields || {});
    if (!keys.length) throw new Error("No fields given");
    const bad = keys.filter(k => EDITABLE.indexOf(k) < 0);
    if (bad.length) throw new Error("Not editable: " + bad.join(", ") + ". Editable: " + EDITABLE.join(", "));
    const before = {};
    keys.forEach(k => before[k] = t[k]());
    keys.forEach(k => t[k] = a.fields[k]);
    const after = {};
    keys.forEach(k => after[k] = trackByID(a.id)[k]());
    return { persistentID: a.id, before: before, after: after };
  },

  now_playing() {
    const out = {
      state: M.playerState(), volume: M.soundVolume(),
      shuffle: M.shuffleEnabled(), repeat: M.songRepeat(),
      shuffleMode: attempt(() => M.shuffleMode(), null), mute: M.mute()
    };
    if (out.state !== "stopped") {
      const t = M.currentTrack;
      out.track = {};
      BRIEF.forEach(p => out.track[p] = attempt(() => t[p](), null));
      out.position = attempt(() => M.playerPosition(), null);
    }
    return out;
  },

  browse(a) {
    const rows = table(library().tracks, BRIEF.concat(["albumArtist", "genre", "year", "playedCount",
      "playedDate", "dateAdded", "skippedCount", "rating", "favorited", "disliked", "cloudStatus"]));
    const view = a.view || "recently_added";
    const by = (k) => rows.filter(r => r[k]).sort((x, y) => (y[k] > x[k] ? 1 : y[k] < x[k] ? -1 : 0));
    let hits;
    if (view === "recently_added") hits = by("dateAdded");
    else if (view === "recently_played") hits = by("playedDate");
    else if (view === "most_played") hits = by("playedCount");
    else if (view === "most_skipped") hits = by("skippedCount");
    else if (view === "top_rated") hits = by("rating");
    else if (view === "favorites") hits = rows.filter(r => r.favorited);
    else if (view === "disliked") hits = rows.filter(r => r.disliked);
    else if (view === "never_played") hits = rows.filter(r => !r.playedCount);
    else if (view === "duplicates") {
      const seen = {};
      rows.forEach(r => {
        const k = (r.name + "\u0000" + r.artist).toLowerCase();
        (seen[k] = seen[k] || []).push(r);
      });
      hits = [].concat.apply([], Object.keys(seen).filter(k => seen[k].length > 1).map(k => seen[k]));
    } else if (["artists", "albums", "genres"].indexOf(view) >= 0) {
      const counts = {};
      rows.forEach(r => {
        const k = view === "artists" ? r.artist : view === "genres" ? r.genre :
          r.album + " | " + (r.albumArtist || r.artist);
        counts[k] = (counts[k] || 0) + 1;
      });
      const groups = Object.keys(counts).map(k => ({ name: k, songs: counts[k] })).sort((x, y) => y.songs - x.songs);
      return { total: groups.length, groups: groups.slice(0, a.limit || 50) };
    } else throw new Error("Unknown view " + view);
    return { total: hits.length, tracks: hits.slice(0, a.limit || 50) };
  },

  copy_playlist(a) {
    const src = findPlaylist(a.playlist);
    const rows = table(src.tracks, BRIEF.concat(["albumArtist", "year", "dateAdded", "playedCount", "trackNumber"]));
    if (a.sort_by) {
      rows.sort((x, y) => {
        const p = x[a.sort_by], q = y[a.sort_by];
        if (typeof p === "string") return p.localeCompare(q);
        return p > q ? 1 : p < q ? -1 : 0;
      });
    }
    if (a.reverse) rows.reverse();
    if (a.shuffle) for (let i = rows.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1)), t = rows[i]; rows[i] = rows[j]; rows[j] = t;
    }
    let order = rows.map(r => r.persistentID);
    if (a.dedupe) order = order.filter((v, i, all) => all.indexOf(v) === i);
    const made = OPS.create_playlist({ name: a.name });
    const target = findPlaylist(made.persistentID);
    order.forEach(id => M.duplicate(trackByID(id), { to: target }));
    return { playlist: made, trackCount: target.tracks.length };
  },

  move_playlist(a) {
    const p = findPlaylist(a.playlist);
    const folder = findPlaylist(a.folder);
    if (folder.class() !== "folderPlaylist") throw new Error("'" + a.folder + "' is not a folder");
    if (!/^(user|folder)Playlist$/.test(p.class())) throw new Error("This playlist cannot be moved");
    const id = p.persistentID();
    M.move(p, { to: folder });
    return playlistInfo(findPlaylist(id));
  },

  airplay(a) {
    const list = () => {
      const d = M.airplayDevices, out = [];
      for (let i = 0; i < d.length; i++) out.push({
        name: d[i].name(), kind: d[i].kind(), available: d[i].available(),
        selected: d[i].selected(), volume: d[i].soundVolume()
      });
      return out;
    };
    const pick = name => {
      const m = M.airplayDevices.whose({ name: name });
      if (!m.length) throw new Error("No AirPlay device named " + name);
      return m[0];
    };
    if (a.devices && a.devices.length) {
      const wanted = a.devices.map(pick);   // resolve all names before changing anything
      wanted.forEach(d => d.selected = true);
      const all = M.airplayDevices;
      for (let i = 0; i < all.length; i++)
        if (all[i].selected() && a.devices.indexOf(all[i].name()) < 0) all[i].selected = false;
    }
    if (a.volume !== undefined && a.volume !== null) {
      if (!a.device) throw new Error("device is required to set its volume");
      pick(a.device).soundVolume = a.volume;
    }
    return list();
  },

  equalizer() {
    return {
      enabled: M.eqEnabled(), current: attempt(() => M.currentEqPreset.name(), null),
      presets: M.eqPresets.name()
    };
  },

  download(a) {
    a.ids.map(trackByID).forEach(t => M.download(t));
    return { requested: a.ids };
  },

  reveal(a) {
    if (!a.id && !a.playlist) throw new Error("Give a song ID or a playlist");
    const item = a.id ? trackByID(a.id) : findPlaylist(a.playlist);
    M.reveal(item);
    M.activate();
    return { shown: item.name() };
  },

  selection() {
    const s = M.selection();
    return s.map(t => ({ persistentID: t.persistentID(), name: t.name(), artist: attempt(() => t.artist(), null) }));
  },

  open_stream(a) {
    if (!/^https?:\/\//.test(a.url)) throw new Error("Only http and https stream links");
    M.openLocation(a.url);
    return { opened: a.url };
  },

  playback(a) {
    if (a.mute !== undefined && a.mute !== null) M.mute = a.mute;
    if (a.volume !== undefined && a.volume !== null) M.soundVolume = a.volume;
    if (a.shuffle !== undefined && a.shuffle !== null) M.shuffleEnabled = a.shuffle;
    if (a.repeat) M.songRepeat = a.repeat;
    if (a.shuffle_mode) M.shuffleMode = a.shuffle_mode;
    switch (a.action) {
      case "play":
        if (a.id) trackByID(a.id).play();
        else if (a.playlist) findPlaylist(a.playlist).play();
        else M.play();
        break;
      case "pause": M.pause(); break;
      case "toggle": M.playpause(); break;
      case "stop": M.stop(); break;
      case "next": M.nextTrack(); break;
      case "previous": M.previousTrack(); break;
      case "restart": M.backTrack(); break;
      case "fast_forward": M.fastForward(); break;
      case "rewind": M.rewind(); break;
      case "resume": M.resume(); break;
      case undefined: case null: break;
      default: throw new Error("Unknown action " + a.action);
    }
    if (a.position !== undefined && a.position !== null) M.playerPosition = a.position;
    delay(0.5);
    return OPS.now_playing();
  }
};

function run(argv) {
  try {
    const a = JSON.parse(argv[0]);
    if (!OPS[a.op]) throw new Error("Unknown op " + a.op);
    return JSON.stringify({ ok: true, result: OPS[a.op](a) });
  } catch (e) {
    return JSON.stringify({ ok: false, error: String(e.message || e) });
  }
}
