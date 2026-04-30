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
```

- `app/` - код приложения, обновляется при deploy.
- `venv/` - Python virtual environment.
- `runtime/` - пользовательские и рабочие данные, не перетираются при deploy.
- `runtime/config.yaml` - реальные настройки и Telegram token.
- `runtime/context.md` - пользовательский контекст для Codex.
- `runtime/state.json` - offset, известные чаты, rolling history и служебное состояние.
- `runtime/logs/` - файловые логи.
- `runtime/chat_archive/` - локальный архив видимых боту сообщений.

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
- `archive.*` - локальный архив переписки.
- `summary.*` - scheduled mini-summary.

Заполните `context.md`: роли, проекты, зоны ответственности, темы, которые вас касаются, и примеры важных/неважных сообщений.

`config.yaml`, `context.md`, `.env`, `state.json`, `logs/` и `chat_archive/` не коммитятся.

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

Codex запускается из runtime-папки, поэтому в read-only режиме видит `context.md`, `state.json` и `chat_archive/`.

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

`deploy.sh` обновляет только `/opt/secretary-bot/app`, ставит Python dependencies, обновляет unit и перезапускает service. Runtime не удаляется и не копируется из release.

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
- `/testnotify` - проверить отправку тестового уведомления.
- `/testdecision` - проверить путь `decision -> notifier -> Telegram`.
- `/reload` - перечитать `config.yaml` и `context.md`.
- `/setcommands` - обновить меню команд Telegram.
- `/help` - справка.

При старте бот автоматически регистрирует меню команд Telegram через `setMyCommands`. Если меню не появилось, отправьте `/setcommands` владельцем.

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
