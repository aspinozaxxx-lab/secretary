# Changelog

## 0.4.0

- Proekt pereveden v headless Ubuntu/systemd rezhim bez Windows tray/exe sloya.
- Udalena PySide6/PyInstaller zavisimost i Windows build/deploy/restart scripts.
- Dobavleny systemd unit i server bootstrap/deploy scripts dlya /opt/secretary-bot.
- Dobavlen GitHub Actions workflow dlya test, SSH deploy i restart service po push v main.
- README obnovlen pod Ubuntu runtime, systemd service, GitHub Secrets i proverku Telegram komand.

## 0.3.1

- Dobavlena registratsiya Telegram menu komand cherez setMyCommands pri starte bota.
- Dobavleny TelegramClient methods set_my_commands, get_my_commands i delete_my_commands.
- Dobavlena owner-only komanda /setcommands dlya prinuditelnogo obnovleniya menu komand.
- Obnovleny /help, /status i README po menu komand Telegram.

## 0.3.0

- Dobavlen polnyy lokalnyy arhiv perepiski po chatam v chat_archive s messages.jsonl, messages.md i chats_index.json.
- Codex prompt teper vklyuchaet puti k lokalnomu arhivu i indeksu chatov dlya read-only dostupa.
- Dobavleny diagnosticheskie sobytiya notification sending/sent/failed i komandy /testnotify, /testdecision.
- Dobavlen scheduled mini-summary po chatam s komandoy /summary i hraneniem last_summary_sent v state.json.
- Obnovleny config.example.yaml, README i deploy script: chat_archive ne kommittitsya i ne peretiraetsya pri deploy.

## 0.2.3

- Dobavlen batch-analiz novyh Telegram-soobscheniy po chatam s limitami po kolichestvu, dline i vremeni.
- Dobavlen dvuhshagovyy dozapros lokalnogo konteksta Codex-om dlya batch-klassifikatsii.
- Uvelichen rolling history limit po umolchaniyu do 500 soobscheniy na chat.
- Dobavlen skrytyy zapusk subprocess Codex na Windows, chtoby iz tray prilozheniya ne vsplyvalo konsolnoe okno.
- Obnovleny README i config.example.yaml po batch-analizu, lokalnoy istorii i kontekstu.

## 0.2.2

- Ispravlen zapusk Codex iz exe runtime-papki bez git repo cherez --skip-git-repo-check.
- Dobavleno bolee poleznoe logirovanie stderr pri Codex exit code.
- Telegram long polling read timeout perenesen iz error-sobytiya v debug, chtoby ne pomechat tray kak oshibku pri obychnom timeout.
- README dopolnen poyasneniem po PyInstaller one-folder i papke _internal.

## 0.2.1

- Ispravleno tray-povedenie: start skrytym v tray, close/minimize pryachet okno, double click otkryvaet ili skryvaet okno.
- Uskoreno zavershenie polling za schet korotkogo getUpdates timeout i preryvaemyh pauz.
- Utochnen tray exit: realnyy vyhod tolko cherez punkt menu Vyhod.
- Usilen deploy.ps1: obnovlyaet tolko app bundle i yavno sohranyaet config.yaml, context.md, state.json i logs.
- Obnovlen README po tray-povedeniyu i runtime deploy safety.

## 0.2.0

- Dobavlen etap desktop MVP: PySide6 tray app s oknom sobytiy i upravleniem start/stop/restart.
- Dobavlen vnutrenniy event bus dlya system, error, incoming, outgoing i decision sobytiy.
- Dobavlen BotRunner dlya zapuska polling v otdelnom thread bez blokirovki GUI.
- Dobavlen tray_main.py dlya GUI-zapuska pri sohranenii konsolnogo main.py.
- Dobavleny PyInstaller spec i PowerShell scripts build/deploy/restart dlya SecretaryBot.exe.
- Obnovlen README po tray-rezhimu, lokalnoy sborke exe i deploy v E:\Projects\secretary-exe.

## 0.1.3

- Dobavlena diagnostika starta: Python version, project root, config, Codex command i Telegram webhook status.
- Dobavlena ponyatnaya obrabotka Telegram 409 Conflict bez postoyannogo shuma v logah.
- Dobavlena proverka i udalenie webhook pri starte, esli webhook byl ustanovlen.
- Uluchshen zapusk Codex na Windows: podderzhka polnogo puti k codex.cmd/codex.exe i diagnostika WinError 2.
- Obnovleny README i config.example.yaml po nastroyke codex.command i 409 Conflict.

## 0.1.2

- Dobavlen rezhim lichnogo sekretarya dlya private-chata s vladeltsem.
- Dobavleny nastroyki user.telegram_user_id i secretary.*.
- Dobavlen otvet Codex na vopros polzovatelya po context.md i srezam rolling history rabochih chatov.
- Obnovlen /status: pokazivaet vklyuchen li lichnyy sekretar i zadan li owner user_id.
- Obnovleny README i context.example.md dlya novogo private-rezhima.

## 0.1.1

- Dobavleno avtoobnaruzhenie chatov i obnovlenie ih metadannyh v state.json pri kazhdom update.
- Dobavlena komanda /chats dlya prosmotra poslednih izvestnyh chatov.
- Obnovlen /status: pokazivaet kolichestvo chatov i rezhim dostupa.
- Utochnena logika allowed_chat_ids: pustoy spisok oznachaet vse chaty, zapolnennyy spisok vklyuchaet whitelist.
- Obnovleny config.example.yaml i README dlya nastroyki bez predvaritelnogo znaniya chat_id.

## 0.1.0

- Dobavlen lokalnyy konsolnyy Telegram Secretary Bot dlya Windows.
- Dobavlen long polling cherez Telegram Bot API bez webhook i vneshnego IP.
- Dobavleny lokalnye pravila resheniya i integratsiya s Codex CLI v read-only non-interactive rezhime.
- Dobavleno hranenie offset, state.json i korotkoy istorii chatov.
- Dobavleny sluzhebnye komandy /ping, /status, /help, /reload i /whoami.
- Dobavleny shablony config.example.yaml i context.example.md.
- Dobavleny README, run.bat, requirements.txt i .gitignore dlya sekretov i lokalnyh dannyh.
