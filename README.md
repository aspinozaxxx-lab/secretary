# Telegram Secretary Bot

Headless Telegram-бот для Ubuntu server. Бот работает через Telegram Bot API long polling, анализирует сообщения через локальный Codex CLI, ведет локальный архив переписки и уведомляет владельца, если сообщение требует внимания.

Webhook, внешний IP и облачный backend не используются. Основной режим запуска - systemd service.

## Структура на сервере

```text
/opt/secretary-bot/
  app/
  venv/
  runtime/
    config.yaml
    context.md
    state.json
    logs/
    chat_archive/
    chat_history.sqlite3
    media/
```

- `app/` - код приложения, обновляется при deploy.
- `venv/` - Python virtual environment.
- `runtime/` - пользовательские и рабочие данные, не перетираются при deploy.
- `runtime/config.yaml` - реальные настройки и Telegram token.
- `runtime/context.md` - пользовательский контекст для Codex.
- `runtime/state.json` - offset, известные чаты, rolling history и служебное состояние.
- `runtime/logs/` - файловые логи.
- `runtime/chat_archive/` - локальный архив видимых боту сообщений.
- `runtime/chat_history.sqlite3` - SQLite-база истории чатов.
- `runtime/media/` - вложения и картинки, импортированные из Telegram export.

## Требования

- Ubuntu 24.04 или совместимая версия.
- Python 3.11+.
- `python3-venv`, `python3-pip`, `git`, `curl`.
- Node.js/npm для Codex CLI.
- Авторизованный Codex CLI на сервере.
- Telegram bot token от BotFather.

## Создание Telegram-бота

1. Откройте чат с `@BotFather`.
2. Выполните `/newbot`.
3. Задайте имя и username бота.
4. Сохраните token.
5. Для рабочих групп отключите privacy mode:

```text
/setprivacy
```

Выберите бота и установите `Disable`.

## Настройка runtime

После первого deploy на сервере появятся шаблоны:

```text
/opt/secretary-bot/runtime/config.yaml
/opt/secretary-bot/runtime/context.md
```

Заполните `config.yaml`:

- `telegram.bot_token` - token от BotFather.
- `telegram.bot_username` - username бота без `@`.
- `telegram.notify_chat_id` или `telegram.notify_user_id` - куда отправлять уведомления.
- `telegram.allowed_chat_ids` - опциональный whitelist. Пустой список означает все чаты, куда добавили бота.
- `user.telegram_user_id` - numeric Telegram user id владельца, надежнее получить через `/whoami`.
- `user.telegram_usernames` - usernames владельца без `@`.
- `user.full_name` - ФИО владельца.
- `user.aliases` - имена, никнеймы и варианты обращения.
- `user.context_file` - обычно `context.md`.
- `codex.command` - обычно `codex`, если CLI доступен в `PATH`.
- `codex.timeout_seconds` - timeout вызова Codex.
- `decision.*` - правила и batch-анализ.
- `storage.state_file` - обычно `state.json`.
- `logging.file` - обычно `logs/secretary.log`.
- `context_management.*` - управление `context.md` через Telegram.
- `archive.*` - локальный архив переписки.
- `database.*` - SQLite-база истории и папка media.
- `telegram_export.import_dir` - опциональный путь для CLI-импорта Telegram export.
- `summary.*` - scheduled mini-summary.

Заполните `context.md`: роли, проекты, зоны ответственности, темы, которые вас касаются, и примеры важных/неважных сообщений.

`config.yaml`, `context.md`, `.env`, `state.json`, `logs/`, `chat_archive/`, `chat_history.sqlite3`, `media/` и выгрузки `Download/` не коммитятся.

## Runtime paths

Все относительные пути в `config.yaml` считаются от папки самого конфига. Для серверного запуска:

```text
/opt/secretary-bot/runtime/config.yaml
```

значит:

- `context.md` -> `/opt/secretary-bot/runtime/context.md`
- `state.json` -> `/opt/secretary-bot/runtime/state.json`
- `logs/secretary.log` -> `/opt/secretary-bot/runtime/logs/secretary.log`
- `chat_archive` -> `/opt/secretary-bot/runtime/chat_archive`
- `chat_history.sqlite3` -> `/opt/secretary-bot/runtime/chat_history.sqlite3`
- `media` -> `/opt/secretary-bot/runtime/media`

Codex запускается из runtime-папки, поэтому в read-only режиме видит `context.md`, `state.json`, `chat_archive/`, `chat_history.sqlite3` и `media/`. Основной путь все равно безопасный: бот сам делает SQLite-выборки и передает Codex только релевантный срез.

## Systemd service

Unit-файл находится в репозитории:

```text
deploy/systemd/secretary-bot.service
```

Команда запуска:

```text
/opt/secretary-bot/venv/bin/python /opt/secretary-bot/app/main.py --config /opt/secretary-bot/runtime/config.yaml
```

Проверить службу:

```bash
systemctl status secretary-bot.service --no-pager
```

Смотреть логи:

```bash
journalctl -u secretary-bot.service -f
```

Перезапустить:

```bash
systemctl restart secretary-bot.service
```

## Первый deploy вручную

Обычно deploy выполняет GitHub Actions. Для ручной проверки можно зайти на сервер:

```bash
ssh root@82.24.195.19
```

И выполнить deploy-скрипты из release-папки:

```text
deploy/server/bootstrap.sh
deploy/server/deploy.sh
```

`bootstrap.sh` создает `/opt/secretary-bot`, ставит системные зависимости, создает venv, ставит Codex CLI, копирует systemd unit и создает `config.yaml/context.md` из example только если их нет.

`deploy.sh` обновляет только `/opt/secretary-bot/app`, ставит Python dependencies, обновляет unit и перезапускает service. Runtime не удаляется и не копируется из release. База `chat_history.sqlite3` и `media/` не перетираются.

## GitHub Actions deploy

Workflow:

```text
.github/workflows/deploy.yml
```

Триггеры:

- push в `main`;
- ручной запуск `workflow_dispatch`.

Jobs:

- `test` - установка dependencies, `compileall`, `main.py --help`, import основных модулей.
- `deploy` - загрузка release на сервер, bootstrap/deploy, restart service.

Нужные GitHub Secrets:

- `SERVER_HOST`
- `SERVER_USER`
- `SERVER_PORT`
- `SERVER_SSH_KEY`

Telegram token не хранится в GitHub Secrets. Он должен быть только на сервере в:

```text
/opt/secretary-bot/runtime/config.yaml
```

Workflow не выводит `config.yaml` и не копирует runtime-файлы из репозитория.

## Codex CLI на сервере

Проверить:

```bash
which codex
codex --version
```

Если Codex CLI установлен, но не авторизован, выполните на сервере интерактивную авторизацию:

```bash
codex login
```

Если CLI отсутствует, `bootstrap.sh` попробует установить:

```bash
npm install -g @openai/codex
```

## Команды бота

- `/ping` - проверка связи.
- `/status` - состояние бота, offset, количество чатов, режим доступа, summary и меню команд.
- `/chats` - последние известные чаты.
- `/whoami` - показать `chat_id`, `chat_type`, `user_id`, `username`.
- `/summary` - отправить mini-summary вручную.
- `/context` - скачать текущий `context.md`.
- `/dbstatus` - показать состояние SQLite-базы истории.
- `/search текст` - поиск по истории чатов.
- `/importstatus` - показать статус последнего импорта Telegram export.
- `/testnotify` - проверить отправку тестового уведомления.
- `/testdecision` - проверить путь `decision -> notifier -> Telegram`.
- `/reload` - перечитать `config.yaml` и `context.md`.
- `/setcommands` - обновить меню команд Telegram.
- `/help` - справка.

При старте бот автоматически регистрирует меню команд Telegram через `setMyCommands`. Если меню не появилось, отправьте `/setcommands` владельцем.

## Управление context.md через Telegram

Команды и загрузка доступны только владельцу. Файлы принимаются только в private-чате с ботом.

Чтобы скачать текущий контекст, отправьте:

```text
/context
```

Бот отправит файл `context.md` с подписью:

```text
Текущий context.md. Отредактируй и отправь обратно файлом с именем context.md.
```

Чтобы обновить контекст:

1. Скачайте файл через `/context`.
2. Отредактируйте его локально.
3. Отправьте боту в личный чат именно document/file с именем `context.md`.

Бот проверяет:

- отправитель является владельцем;
- чат private;
- имя файла ровно `context.md`;
- размер не больше `context_management.max_upload_bytes`, по умолчанию `262144` байт;
- файл читается как UTF-8 или UTF-8 with BOM;
- текст не пустой.

Перед заменой старый файл сохраняется в:

```text
/opt/secretary-bot/runtime/context.backups/
```

Имя backup:

```text
context_YYYYMMDD_HHMMSS.md
```

После успешной загрузки бот перечитывает `config.yaml` и `context.md` без ручного рестарта. Если возникает ошибка, старый `context.md` остается на месте.

Через Telegram нельзя скачать или заменить `config.yaml`, `state.json`, `logs/` или `chat_archive/`.

## SQLite history database

Бот дополнительно хранит историю чатов в SQLite:

```text
/opt/secretary-bot/runtime/chat_history.sqlite3
/opt/secretary-bot/runtime/media
```

В базе есть таблицы:

- `chats` - известные чаты.
- `users` - отправители.
- `messages` - сообщения из Bot API и импортов.
- `attachments` - вложения и ссылки на файлы в `media/`.
- `message_fts` - полнотекстовый поиск, если SQLite собран с FTS5.

Если FTS5 недоступен, бот автоматически использует LIKE-поиск и не падает.

Новые сообщения, которые бот видит через Bot API, записываются в `state.json`, `chat_archive/` и SQLite. Telegram Bot API не позволяет получить старую историю до добавления бота, поэтому старые сообщения можно добавить только разовым импортом выгрузки Telegram.

Проверить базу на сервере:

```bash
/opt/secretary-bot/venv/bin/python /opt/secretary-bot/app/main.py db-status --config /opt/secretary-bot/runtime/config.yaml
```

## Import Telegram export

Поддерживается Telegram Desktop HTML export: папки `ChatExport_*`, файлы `messages.html`, `messages2.html`, папки `photos/`, `files/`, `video_files/` и похожие локальные вложения.

Импорт запускается CLI-командой, не через Telegram:

```bash
/opt/secretary-bot/venv/bin/python /opt/secretary-bot/app/main.py import-telegram-export \
  --config /opt/secretary-bot/runtime/config.yaml \
  --path /path/to/Telegram/Download
```

Импорт идемпотентный: повторный запуск не должен плодить дубли сообщений. Вложения копируются в `runtime/media/<chat_id>/...`, исходная выгрузка не удаляется.

После импорта `/summary` и личный режим секретаря используют SQLite-выборки. Codex получает:

- путь к базе;
- путь к media;
- целевые чаты, если их удалось определить по вопросу или текущему сообщению;
- последние и найденные сообщения;
- ссылки на вложения, если они есть в выборке.

## Локальный архив

Бот сохраняет только сообщения, которые реально видит через Bot API после запуска или добавления в чат. Старую историю Telegram получить нельзя.

Архив лежит тут:

```text
/opt/secretary-bot/runtime/chat_archive
```

Структура:

```text
chat_archive/
  chats_index.json
  <chat_id>_<safe_title>/
    messages.jsonl
    messages.md
```

Deploy не перетирает `chat_archive/`.

## Проверка после deploy

На сервере:

```bash
systemctl status secretary-bot.service --no-pager
journalctl -u secretary-bot.service -n 100 --no-pager
ls -la /opt/secretary-bot
ls -la /opt/secretary-bot/runtime
```

В Telegram:

```text
/ping
/status
/chats
/testnotify
/summary
```

Если service падает из-за missing config value, заполните `/opt/secretary-bot/runtime/config.yaml` и выполните:

```bash
systemctl restart secretary-bot.service
```
