# pyami_asterisk (совместимый форк)

![tests](https://github.com/HSMM/pyami_asterisk/actions/workflows/tests.yml/badge.svg)

Asyncio-клиент для Asterisk Manager Interface (AMI). Это совместимый форк
[denisstreltsov/pyami_asterisk](https://github.com/streltsovdenis/pyami_asterisk) Дениса Стрельцова (MIT);
последний релиз оригинала - 1.5.2. English version: [README.md](README.md).

Публичный API версии 1.5.2 и закрытый `_send_action(action, callback)` продолжают работать; новое поведение
добавляется или включается по желанию (см. [ADR 1](docs/adr/0001-compatible-fork.md)).

## Что исправляет форк

В планах, ведутся задачами в трекере:

- разбор и запись пакетов AMI
- вход: таймаут, падение при оборванном входе, различие отказа во входе и потери соединения
- переподключение: один цикл, без рекурсии, ограниченные паузы, без утечек сокетов
- действия с ожидаемым ответом и без потерянных обратных вызовов
- жизненный цикл внутри работающего цикла событий, подменяемое время, упорядоченные события
- релиз 1.6.0

Уже сделано: современная упаковка, CI и поддельный AMI-сервер для тестов.

## Установка

Тега `v1.6.0` пока нет; до релиза ставьте из репозитория:

```bash
pip install "pyami-asterisk @ git+https://github.com/HSMM/pyami_asterisk@v1.6.0"
```

## Разработка

```bash
uv venv --python 3.12 .venv
uv pip install -e . --group dev
.venv/bin/python -m pytest -q
```

## Использование

Примеры использования те же, что в оригинале, и приведены в [README.md](README.md#usage) (код не меняется).

## Авторство

Основано на [denisstreltsov/pyami_asterisk](https://github.com/streltsovdenis/pyami_asterisk) Дениса Стрельцова (MIT).
