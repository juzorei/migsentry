# migsentry

[English](README.md) | [Русский](README.ru.md)

Скилл и CLI для ревью миграций БД: ловят операции, которые блокируют таблицы, переписывают данные или ломают работающее приложение — до продакшена.

Миграция — такой же артефакт деплоя, как код, только её баги блокируют продакшен-таблицы. `migsentry` сканирует SQL миграций из любого источника (Alembic autogenerate, Django `sqlmigrate`, Prisma, рукописный) и помечает опасные классы — с пояснением *почему* под конкретный движок и рецептом expand/contract — *как исправить*:

```text
$ migsentry scan migrations/versions/
== migrations/versions/0007_rename.sql: 3 checked, 0 skipped
  [DANGER] L1    rename-column on name
          ALTER TABLE users RENAME COLUMN name TO full_name;
          why: A rename moves the schema and code in one step only if they deploy together — they never do.
          fix: Expand/contract: add the new column, dual-write, backfill, move readers, then drop the old name.
  -> 3 finding(s): 2 danger, 1 info
```

Код выхода 1 при любой danger-находке — можно ставить в CI gate. Известно-безопасные операции помечаются директивой `-- migsentry: no-check` на конкретном statement, а не тихим пропуском файла.

## Что в репозитории

- **[skills/migration-safety-review](skills/migration-safety-review)** — процесс ревью для агентов: сначала скан, затем разбор каждого класса вердиктов (семантика блокировок по движкам, CONCURRENTLY и его транзакционные нюансы, NOT VALID/VALIDATE для внешних ключей), паттерн expand/contract как ответ почти на каждый danger, чеклист поверх сканера (autogenerate сравнивает модели, а не намерения; батчинг backfill; честность про необратимость) и формат отчёта, где ни одна danger-находка не остаётся без объяснения.
- **tools/migsentry** — CLI ([README](tools/migsentry/README.md)): вердикты danger/warn/info, пояснения под движок, `--json`, директивы пропуска, только stdlib.

## Установка

```bash
pip install migsentry
npx skills add juzorei/migsentry
```

## Рамки

Ревью миграций, которыми ты владеешь или уполномочен менять. Советы исходят из того, что базу можно бэкапить.

Лицензия MIT.
