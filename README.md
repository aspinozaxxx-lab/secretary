# Telegram Secretary Bot

Локальное консольное Windows-приложение, которое читает сообщения Telegram-бота через long polling, анализирует их локальным Codex CLI и уведомляет пользователя, если сообщение требует внимания.

Webhook, внешний IP и облачный backend не используются.

## Требования

- Windows
- Python 3.11+
- Авторизованный Codex CLI
- Telegram bot token от BotFather

## Установка зависимостей

```powershell
cd E:\Projects\secretary
python -m pip install -r requirements.txt
```

## Создание Telegram-бота

1. Откройте чат с `@BotFather`.
2. Выполните `/newbot`.
3. Задайте имя и username бота.
4. Сохраните token, который выдаст BotFather.
5. Для рабочих групп отключите privacy mode:

```text
/setprivacy
```

Выберите бота и установите `Disable`.

## Настройка

Скопируйте шаблоны:

```powershell
copy config.example.yaml config.yaml
copy context.example.md context.md
```

Заполните `config.yaml`:

- `telegram.bot_token` — token от BotFather.
- `telegram.bot_username` — username бота без `@`.
- `telegram.notify_chat_id` или `telegram.notify_user_id` — куда отправлять уведомления.
- `telegram.allowed_chat_ids` — опциональный whitelist. Пустой список означает, что бот принимает все чаты, куда его добавили. Заполненный список ограничивает обработку только указанными `chat_id`.
- `user.telegram_user_id` — numeric Telegram user id владельца. Надежнее заполнить его после `/whoami`.
- `user.telegram_usernames` — ваши Telegram usernames без `@`.
- `user.full_name` — ваше ФИО.
- `user.aliases` — имена, никнеймы и варианты обращения.
- `user.context_file` — обычно `context.md`.
- `codex.command` — обычно `codex`, если команда доступна в PATH. На Windows можно указать полный путь к `codex.cmd` или `codex.exe`, например `C:\Users\<user>\AppData\Roaming\npm\codex.cmd`.
- `codex.timeout_seconds` — timeout классификации.
- `decision.min_confidence_to_notify` — минимальная уверенность для уведомления.
- `decision.batch_enabled` — включает анализ новых сообщений пачками.
- `decision.batch_max_messages` — максимум сообщений в одной пачке.
- `decision.batch_max_chars` — максимум суммарного текста пачки для prompt.
- `decision.batch_max_age_seconds` — максимальный разрыв по времени внутри пачки.
- `storage.state_file` — обычно `state.json`.
- `storage.history_max_messages_per_chat` — сколько последних сообщений хранить по каждому чату для контекста.
- `logging.file` — файл логов.
- `secretary.enable_private_assistant` — включает ответы секретаря в личном чате с владельцем.
- `secretary.max_context_messages` — сколько последних сообщений передавать Codex для ответа.
- `secretary.max_answer_chars` — максимальная длина ответа в Telegram.

Заполните `context.md`: роли, проекты, зоны ответственности, приоритеты и примеры сообщений.

`config.yaml`, `context.md`, `.env`, `state.json` и `logs/` не коммитятся.

## Авторизация Codex CLI

Проверьте, что команда доступна:

```powershell
codex --version
```

Если Codex не авторизован, выполните:

```powershell
codex login
```

Для классификации приложение вызывает Codex в безопасном non-interactive режиме:

```powershell
codex exec --sandbox read-only --ephemeral --cd E:\Projects\secretary -
```

На Windows приложение старается запускать Codex без всплывающего консольного окна. Если `codex.command` указывает на `codex.cmd`, его можно оставить как команду из `PATH` или указать полный путь.

## Запуск

### Консольный режим

```powershell
cd E:\Projects\secretary
run.bat
```

Остановка: `Ctrl+C`.

### Tray-режим из исходников

```powershell
cd E:\Projects\secretary
python -m pip install -r requirements.txt
python tray_main.py
```

Приложение стартует скрытым в системном трее. Окно логов открывается через пункт меню `Открыть окно` или двойным кликом по иконке в трее. Повторный двойной клик скрывает окно.

Крестик окна и сворачивание не завершают приложение: окно скрывается в трей и не остается в панели задач. Реальное завершение выполняется только через пункт tray-меню `Выход`.

В меню доступны запуск, остановка, перезапуск бота, открытие `config.yaml`, `context.md`, папки логов и окна событий.

Окно событий показывает входящие, исходящие, системные, ошибочные и decision-события: время, тип, чат, автора, текст и решение.

## Сборка Windows exe

Сборка выполняется через PyInstaller в one-folder режиме:

```powershell
cd E:\Projects\secretary
.\scripts\build.ps1
```

Итоговый файл:

```text
dist\SecretaryBot\SecretaryBot.exe
```

Сборка сейчас one-folder: запускать нужно `SecretaryBot.exe`, а папка `_internal` должна лежать рядом. Удалять `_internal` нельзя, там находятся Python runtime, PySide6 и зависимости. One-file сборка без `_internal` возможна отдельной настройкой PyInstaller, но для PySide6 она обычно стартует медленнее и распаковывается во временную папку.

Реальный `config.yaml` не вшивается в exe. При запуске exe ищет `config.yaml` рядом с `SecretaryBot.exe`.

## Deploy в runtime-папку

Deploy-каталог:

```text
E:\Projects\secretary-exe
```

Команда:

```powershell
cd E:\Projects\secretary
.\scripts\deploy.ps1
```

Deploy обновляет app bundle (`SecretaryBot.exe` и `_internal`) и копирует `README.md`, `config.example.yaml`, `context.example.md`. Он не перетирает:

- `config.yaml`
- `context.md`
- `state.json`
- `logs`

Если `config.yaml` или `context.md` отсутствуют в runtime-папке, они создаются из example-файлов.

## Restart deployed exe

```powershell
cd E:\Projects\secretary
.\scripts\restart.ps1
```

Скрипт ищет и перезапускает только `SecretaryBot.exe`, запущенный из `E:\Projects\secretary-exe`.

## Добавление в чат и обнаружение chat_id

1. Добавьте бота в рабочую группу.
2. Если бот должен видеть все сообщения, убедитесь, что privacy mode отключен.
3. `telegram.allowed_chat_ids` можно оставить пустым: бот сам увидит чаты через long polling и сохранит их в `state.json`.
4. В любом чате с ботом отправьте:

```text
/chats
```

или:

```text
/whoami
```

5. Возьмите нужные `chat_id` из ответа.
6. Если нужно ограничить обработку, перенесите нужные id в `telegram.allowed_chat_ids` и выполните `/reload`.

## Режим личного секретаря

В private-чате с владельцем обычный текст без `/` считается вопросом секретарю. В рабочих группах бот не отвечает содержательно на обычные сообщения: он только читает, анализирует, уведомляет и отвечает на служебные команды.

Для надежной настройки владельца:

1. Напишите боту в личном чате:

```text
/whoami
```

2. Скопируйте numeric `user_id` в `user.telegram_user_id`.
3. Выполните `/reload` или перезапустите `run.bat`.

Если `user.telegram_user_id` не задан, бот временно считает владельцем пользователя с username из `user.telegram_usernames`. Это менее надежно, поэтому лучше заполнить numeric `user_id`.

После настройки можно писать в личный чат вопросы вроде:

```text
Что важного было сегодня по проекту NSPD?
```

Бот передаст Codex `context.md`, вопрос и подготовленный срез rolling history из известных рабочих чатов. Бот знает только сообщения, которые видел после запуска или после добавления в чат. Telegram Bot API не позволяет получить старую историю задним числом.

В режиме личного секретаря Codex не делает интерактивные запросы к боту за дополнительными данными. Вместо этого бот заранее передает релевантный срез истории: сначала пытается отфильтровать сообщения по ключевым словам вопроса, а если совпадений мало, добавляет последние сообщения из всех известных рабочих чатов.

## Команды бота

- `/ping` — проверка связи.
- `/status` — offset, количество известных чатов, режим доступа и путь к конфигу.
- `/chats` — последние известные боту чаты с `chat_id`, типом, названием и временем последнего сообщения.
- `/help` — краткая справка.
- `/reload` — перечитать `config.yaml` и `context.md` без перезапуска.
- `/whoami` — показать `chat_id`, `chat_type`, `user_id`, `username`.
- `/testnotify` — проверить отправку тестового уведомления владельцу.
- `/testdecision` — проверить путь `decision -> notifier -> Telegram`.
- `/summary` — вручную отправить mini-summary по известным чатам.
- `/setcommands` — принудительно обновить меню команд Telegram.

## Меню команд Telegram

При старте бот автоматически регистрирует меню команд Telegram через `setMyCommands`. В меню доступны:

- `/ping`
- `/status`
- `/chats`
- `/whoami`
- `/summary`
- `/testnotify`
- `/testdecision`
- `/reload`
- `/help`

Если меню не появилось или Telegram-клиент показывает старый список, отправьте боту:

```text
/setcommands
```

Иногда Telegram-клиенту нужно закрыть и снова открыть чат или перезапустить приложение, чтобы меню обновилось.

## Как принимается решение

Сначала применяются локальные правила:

- прямое упоминание username пользователя — уведомить сразу;
- reply на сообщение пользователя — уведомить сразу;
- служебные команды обрабатываются локально.

Остальные текстовые сообщения отправляются в Codex CLI. Если Telegram вернул несколько новых сообщений за один polling-запрос, бот сначала сохраняет их в `state.json`, затем группирует по чатам и анализирует пачками. Это снижает количество отдельных запусков Codex после паузы или при активном потоке сообщений.

По умолчанию одна пачка ограничена:

- 30 сообщениями;
- 12000 символами текста;
- 90 секундами между первым и последним сообщением.

Codex возвращает строгий JSON с решениями по `message_id`, общей сводкой пачки и, если контекста не хватает, может один раз запросить дополнительную локальную историю:

```json
{
  "need_more_context": true,
  "context_request": {
    "chat_id": -100123,
    "before_message_id": 456,
    "limit": 50,
    "keywords": ["сроки"]
  }
}
```

Бот не читает Telegram history задним числом: Telegram Bot API этого не позволяет. Для дозапроса используется только rolling history, которую бот уже видел и сохранил локально. Повторный запрос контекста разрешен только один раз на пачку, чтобы не зациклить обработку.

Медиа без текста не анализируется, но факт вложения пишется в лог.

## Локальный архив чатов

Бот сохраняет всю видимую ему переписку в runtime-папке рядом с `config.yaml`, `state.json` и `logs`.

Для exe это обычно:

```text
E:\Projects\secretary-exe\chat_archive
```

Структура:

```text
chat_archive/
  chats_index.json
  <chat_id>_<safe_title>/
    messages.jsonl
    messages.md
```

`messages.jsonl` содержит машинно-читаемые записи сообщений: `update_id`, `message_id`, дату, чат, автора, текст, reply, mentions/entities и сведения о вложениях. `messages.md` содержит читаемый лог.

Архивируются только сообщения, которые бот реально увидел через Telegram Bot API после запуска или добавления в чат. Старую историю Telegram до добавления бота получить нельзя.

`chat_archive/` является runtime-данными, не коммитится и не перетирается deploy-скриптом.

## Codex и архив

Codex запускается в read-only sandbox из runtime-папки, поэтому при exe-запуске видит:

- `context.md`
- `state.json`
- `chat_archive/chats_index.json`
- `chat_archive/.../messages.md`
- `chat_archive/.../messages.jsonl`

В prompt передаются пути к архиву и индексам чатов. Если Codex сможет прочитать файлы через read-only sandbox, он использует их как дополнительный контекст. Если чтение файлов недоступно, бот все равно передает срез rolling history в prompt.

## Проверка proactive notifications

Для проверки, что бот может сам инициировать сообщения, используйте команды владельца:

```text
/testnotify
/testdecision
```

`/testnotify` отправляет тестовое уведомление в `telegram.notify_chat_id` или `telegram.notify_user_id`.

`/testdecision` создает локальное decision-событие `notify=true` и прогоняет тот же путь, что обычное важное сообщение: `decision -> notifier -> Telegram`.

Если target не задан, бот ответит, что нужно заполнить `notify_chat_id` или `notify_user_id`.

## Scheduled mini-summary

Если `summary.enabled: true`, бот автоматически отправляет mini-summary по известным чатам в указанное время:

```yaml
summary:
  enabled: true
  times:
    - "13:00"
    - "18:00"
  timezone: "Europe/Moscow"
  lookback_hours: 6
  max_messages: 200
```

Summary отправляется в `summary.target_chat_id`, если он задан. Иначе используется `telegram.notify_chat_id`, затем `telegram.notify_user_id`.

Чтобы вручную запустить summary:

```text
/summary
```

Бот хранит в `state.json`, какие scheduled summary уже были отправлены за дату, чтобы не отправлять одно и то же расписание несколько раз.

## Типовые проблемы

### Бот не видит сообщения в группе

Проверьте privacy mode у BotFather: `/setprivacy` -> `Disable`.

### Уведомления не приходят

Проверьте `telegram.notify_chat_id` или `telegram.notify_user_id`. Получить значения можно через `/whoami`.

### Чат игнорируется

Если `telegram.allowed_chat_ids` заполнен, бот игнорирует все чаты вне списка. Если список пустой, бот принимает все чаты, куда его добавили.

### Codex timeout или мусор вместо JSON

Проверьте `codex --version`, авторизацию `codex login` и увеличьте `codex.timeout_seconds`.

### Codex не найден на Windows

Если в логах есть `Не найдена команда Codex`, укажите полный путь в `codex.command`. Если Codex установлен через npm, чаще всего это `codex.cmd` в `%APPDATA%\npm`, например:

```yaml
codex:
  command: "C:\\Users\\<user>\\AppData\\Roaming\\npm\\codex.cmd"
```

Проверить путь можно командой:

```powershell
where.exe codex
```

### Telegram 409 Conflict

Ошибка `409 Conflict` означает, что для этого bot token уже активен другой `getUpdates` polling или webhook. Остановите другие экземпляры бота и проверьте, что webhook не установлен. При старте приложение само проверяет `getWebhookInfo` и удаляет webhook, если он задан.
