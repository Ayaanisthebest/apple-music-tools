-- usage: artwork.applescript get|set TRACK_ID FILE
on run argv
	set {mode, theID, thePath} to {item 1 of argv, item 2 of argv, item 3 of argv}
	tell application "Music"
		set found to (every track of library playlist 1 whose persistent ID is theID)
		if found is {} then error "No song in the library has ID " & theID
		set t to item 1 of found
		if mode is "get" then
			if (count of artworks of t) is 0 then error "This song has no artwork"
			set d to raw data of artwork 1 of t
		else
			set data of artwork 1 of t to (read (POSIX file thePath) as picture)
			return "set"
		end if
	end tell
	set f to open for access (POSIX file thePath) with write permission
	write d to f
	close access f
	return "saved"
end run
