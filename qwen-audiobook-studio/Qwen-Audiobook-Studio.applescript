property studioDir : "/Users/elenadymova/Documents/New project/Qwen-Audiobook-Studio"
property pythonPath : "/Users/elenadymova/Documents/New project/qwen3-tts-0.6b-customvoice-mlx-book-audition-2026-08-16/.venv/bin/python"

on splitLine(theLine)
	set oldTID to AppleScript's text item delimiters
	set AppleScript's text item delimiters to tab
	set parts to text items of theLine
	set AppleScript's text item delimiters to oldTID
	return parts
end splitLine

on labelsFromLines(theLines)
	set outLabels to {}
	repeat with oneLine in theLines
		set parts to my splitLine(contents of oneLine)
		if (count of parts) > 1 then
			set end of outLabels to item 2 of parts
		else
			set end of outLabels to item 1 of parts
		end if
	end repeat
	return outLabels
end labelsFromLines

on chosenIndex(labelsList, chosenLabel)
	repeat with i from 1 to count of labelsList
		if item i of labelsList is chosenLabel then return i
	end repeat
	return 1
end chosenIndex

on run
	try
		do shell script "/bin/test -x " & quoted form of pythonPath
		do shell script "/bin/test -f " & quoted form of (studioDir & "/studio_app_runner.py")
		
		set bridge to studioDir & "/studio_app_runner.py"
		set baseCmd to quoted form of pythonPath & " " & quoted form of bridge
		
		-- BOOK
		set booksRaw to do shell script baseCmd & " --list-books"
		if booksRaw is "" then error "В студии нет подготовленных книг."
		set bookLines to paragraphs of booksRaw
		set bookLabels to my labelsFromLines(bookLines)
		set bookPick to choose from list bookLabels with title "Qwen Audiobook Studio" with prompt "Выберите книгу" default items {item 1 of bookLabels} OK button name "Дальше" cancel button name "Отмена"
		if bookPick is false then return
		set bookLabel to item 1 of bookPick
		set bookIndex to my chosenIndex(bookLabels, bookLabel)
		set bookParts to my splitLine(item bookIndex of bookLines)
		set bookProfile to item 1 of bookParts
		
		-- JOB
		set jobsRaw to do shell script baseCmd & " --list-jobs --book " & quoted form of bookProfile
		set jobLines to paragraphs of jobsRaw
		set jobLabels to my labelsFromLines(jobLines)
		set jobPick to choose from list jobLabels with title "Qwen Audiobook Studio" with prompt "Что генерировать" default items {item 1 of jobLabels} OK button name "Дальше" cancel button name "Отмена"
		if jobPick is false then return
		set jobLabel to item 1 of jobPick
		set jobIndex to my chosenIndex(jobLabels, jobLabel)
		set jobParts to my splitLine(item jobIndex of jobLines)
		set jobId to item 1 of jobParts
		
		-- VOICE
		set voicesRaw to do shell script baseCmd & " --list-voices"
		set voiceLines to paragraphs of voicesRaw
		set voiceLabels to my labelsFromLines(voiceLines)
		set defaultSpeaker to do shell script baseCmd & " --default-speaker --book " & quoted form of bookProfile
		set defaultVoiceLabel to item 1 of voiceLabels
		repeat with i from 1 to count of voiceLines
			set vp to my splitLine(item i of voiceLines)
			if item 1 of vp is defaultSpeaker then set defaultVoiceLabel to item i of voiceLabels
		end repeat
		set voicePick to choose from list voiceLabels with title "Qwen Audiobook Studio" with prompt "Выберите диктора" default items {defaultVoiceLabel} OK button name "Дальше" cancel button name "Отмена"
		if voicePick is false then return
		set voiceLabel to item 1 of voicePick
		set voiceIndex to my chosenIndex(voiceLabels, voiceLabel)
		set voiceParts to my splitLine(item voiceIndex of voiceLines)
		set speakerId to item 1 of voiceParts
		
		set confirmText to "Книга: " & bookLabel & return & "Режим: " & jobLabel & return & "Диктор: " & speakerId & return & return & "Старые WAV не перезаписываются. Мастер книги не изменяется."
		set answer to display dialog confirmText with title "Запустить генерацию?" buttons {"Отмена", "Запустить"} default button "Запустить" cancel button "Отмена" with icon note
		if button returned of answer is not "Запустить" then return
		
		-- Start fully in background: no Terminal window.
		do shell script "/bin/mkdir -p " & quoted form of (studioDir & "/logs")
		set stamp to do shell script "/bin/date +%Y%m%d-%H%M%S"
		set logFile to studioDir & "/logs/app-" & stamp & ".log"
		set runCmd to "/usr/bin/nohup " & quoted form of pythonPath & " " & quoted form of bridge & " --run --book " & quoted form of bookProfile & " --job " & quoted form of jobId & " --speaker " & quoted form of speakerId & " > " & quoted form of logFile & " 2>&1 < /dev/null &"
		do shell script runCmd
		
		display notification "После завершения откроется папка с готовым WAV." with title "Qwen Audiobook Studio" subtitle (bookLabel & " — " & speakerId)
		display dialog "Генерация запущена.\n\nTerminal открывать не нужно. После завершения студия сама откроет папку с результатом и покажет уведомление." with title "Qwen Audiobook Studio" buttons {"OK"} default button "OK" with icon note
		
	on error errMsg number errNum
		if errNum is -128 then return
		display dialog "Не удалось запустить студию.\n\n" & errMsg with title "Qwen Audiobook Studio — ошибка" buttons {"OK"} default button "OK" with icon stop
	end try
end run
