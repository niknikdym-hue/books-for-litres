property workspaceRelativePath : "Documents/New project/Audiobook-Studio"
property studioDir : ""
property pythonPath : ""

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

on runQwen(baseCmd)
	set booksRaw to do shell script baseCmd & " --list-books"
	if booksRaw is "" then error "В студии нет подготовленных книг."
	set bookLines to paragraphs of booksRaw
	set bookLabels to my labelsFromLines(bookLines)
	set bookPick to choose from list bookLabels with title "Audiobook Studio — Qwen" with prompt "Выберите книгу" default items {item 1 of bookLabels} OK button name "Дальше" cancel button name "Отмена"
	if bookPick is false then return
	set bookLabel to item 1 of bookPick
	set bookIndex to my chosenIndex(bookLabels, bookLabel)
	set bookParts to my splitLine(item bookIndex of bookLines)
	set bookProfile to item 1 of bookParts

	set jobsRaw to do shell script baseCmd & " --list-jobs --book " & quoted form of bookProfile
	set jobLines to paragraphs of jobsRaw
	set jobLabels to my labelsFromLines(jobLines)
	set jobPick to choose from list jobLabels with title "Audiobook Studio — Qwen" with prompt "Что генерировать" default items {item 1 of jobLabels} OK button name "Дальше" cancel button name "Отмена"
	if jobPick is false then return
	set jobLabel to item 1 of jobPick
	set jobIndex to my chosenIndex(jobLabels, jobLabel)
	set jobParts to my splitLine(item jobIndex of jobLines)
	set jobId to item 1 of jobParts

	set voicesRaw to do shell script baseCmd & " --list-voices --engine qwen"
	set voiceLines to paragraphs of voicesRaw
	set voiceLabels to my labelsFromLines(voiceLines)
	set defaultSpeaker to do shell script baseCmd & " --default-speaker --book " & quoted form of bookProfile
	set defaultVoiceLabel to item 1 of voiceLabels
	repeat with i from 1 to count of voiceLines
		set voiceParts to my splitLine(item i of voiceLines)
		if item 1 of voiceParts is defaultSpeaker then set defaultVoiceLabel to item i of voiceLabels
	end repeat
	set voicePick to choose from list voiceLabels with title "Audiobook Studio — Qwen" with prompt "Выберите диктора" default items {defaultVoiceLabel} OK button name "Дальше" cancel button name "Отмена"
	if voicePick is false then return
	set voiceLabel to item 1 of voicePick
	set voiceIndex to my chosenIndex(voiceLabels, voiceLabel)
	set voiceParts to my splitLine(item voiceIndex of voiceLines)
	set speakerId to item 1 of voiceParts

	set confirmText to "Движок: Qwen — локально" & return & "Книга: " & bookLabel & return & "Режим: " & jobLabel & return & "Диктор: " & speakerId & return & return & "Старые WAV не перезаписываются. Мастер книги не изменяется."
	set answer to display dialog confirmText with title "Запустить генерацию?" buttons {"Отмена", "Запустить"} default button "Запустить" cancel button "Отмена" with icon note
	if button returned of answer is not "Запустить" then return

	do shell script "/bin/mkdir -p " & quoted form of (studioDir & "/logs")
	set stamp to do shell script "/bin/date +%Y%m%d-%H%M%S"
	set logFile to studioDir & "/logs/app-qwen-" & stamp & ".log"
	set runCmd to "/usr/bin/nohup " & quoted form of pythonPath & " " & quoted form of (studioDir & "/audiobook_studio_app_runner.py") & " --run-qwen --book " & quoted form of bookProfile & " --job " & quoted form of jobId & " --speaker " & quoted form of speakerId & " > " & quoted form of logFile & " 2>&1 < /dev/null &"
	do shell script runCmd

	display notification "После завершения откроется папка с готовым WAV." with title "Audiobook Studio — Qwen" subtitle (bookLabel & " — " & speakerId)
	display dialog "Генерация запущена.\n\nTerminal открывать не нужно. После завершения студия сама откроет папку с результатом и покажет уведомление." with title "Audiobook Studio — Qwen" buttons {"OK"} default button "OK" with icon note
end runQwen

on runYandex(baseCmd)
	set estimateRaw to do shell script baseCmd & " --yandex-estimate-demo --format tsv"
	set estimateParts to my splitLine(estimateRaw)
	if (count of estimateParts) is not 7 then error "Universal bridge вернул некорректную оценку Yandex demo."

	set engineLabel to item 1 of estimateParts
	set voiceLabel to item 2 of estimateParts
	set roleLabel to item 3 of estimateParts
	set speedLabel to item 4 of estimateParts
	set characterCount to item 5 of estimateParts
	set segmentCount to item 6 of estimateParts
	set billingUnits to item 7 of estimateParts

	set confirmText to "Engine: " & engineLabel & return & "Voice: " & voiceLabel & return & "Role: " & roleLabel & return & "Speed: " & speedLabel & return & "Символов demo: " & characterCount & return & "Сегментов: " & segmentCount & return & "Estimated billing units: " & billingUnits & return & return & "ВНИМАНИЕ: кнопка «Синтезировать тест» отправит реальные платные запросы в Yandex SpeechKit."
	set answer to display dialog confirmText with title "Audiobook Studio — Yandex demo" buttons {"Синтезировать тест", "Отмена"} default button "Отмена" cancel button "Отмена" with icon caution
	if button returned of answer is not "Синтезировать тест" then return

	do shell script "/bin/mkdir -p " & quoted form of (studioDir & "/logs")
	set stamp to do shell script "/bin/date +%Y%m%d-%H%M%S"
	set logFile to studioDir & "/logs/app-yandex-" & stamp & ".log"
	set runCmd to "/usr/bin/nohup " & quoted form of pythonPath & " " & quoted form of (studioDir & "/audiobook_studio_app_runner.py") & " --run-yandex-demo > " & quoted form of logFile & " 2>&1 < /dev/null &"
	do shell script runCmd

	display notification "Короткий demo-тест запущен в фоне." with title "Audiobook Studio — Yandex" subtitle (voiceLabel & " " & roleLabel & " " & speedLabel)
	display dialog "Demo-синтез запущен.\n\nTerminal открывать не нужно. Технический лог: " & logFile with title "Audiobook Studio — Yandex" buttons {"OK"} default button "OK" with icon note
end runYandex

on run
	try
		set workspaceDir to (POSIX path of (path to home folder)) & workspaceRelativePath
		set my studioDir to workspaceDir & "/runtime/studio-workspace"
		set my pythonPath to workspaceDir & "/engines/qwen-mlx/.venv/bin/python"
		do shell script "/bin/test -x " & quoted form of pythonPath
		do shell script "/bin/test -f " & quoted form of (studioDir & "/audiobook_studio_app_runner.py")

		set bridge to studioDir & "/audiobook_studio_app_runner.py"
		set baseCmd to quoted form of pythonPath & " " & quoted form of bridge
		set enginesRaw to do shell script baseCmd & " --list-engines"
		if enginesRaw is "" then error "Universal bridge не вернул список движков."
		set engineLines to paragraphs of enginesRaw
		set engineLabels to my labelsFromLines(engineLines)
		set enginePick to choose from list engineLabels with title "Audiobook Studio" with prompt "Выберите движок" default items {item 1 of engineLabels} OK button name "Дальше" cancel button name "Отмена"
		if enginePick is false then return
		set engineLabel to item 1 of enginePick
		set engineIndex to my chosenIndex(engineLabels, engineLabel)
		set engineParts to my splitLine(item engineIndex of engineLines)
		set engineId to item 1 of engineParts

		if engineId is "qwen" then
			my runQwen(baseCmd)
		else if engineId is "yandex" then
			my runYandex(baseCmd)
		else
			error "Неизвестный движок: " & engineId
		end if
	on error errMsg number errNum
		if errNum is -128 then return
		display dialog "Не удалось запустить студию.\n\n" & errMsg with title "Audiobook Studio — ошибка" buttons {"OK"} default button "OK" with icon stop
	end try
end run
