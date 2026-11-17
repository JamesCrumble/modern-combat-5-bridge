# Сторонний код и происхождение данных

Код проекта (мост, патчер, сервер, инструменты) написан **JamesCrumble** и распространяется по GPL-3.0 (`LICENSE`).

## Библиотеки в APK моста

| Что | Откуда | Лицензия |
|---|---|---|
| CPython 3.14 для Android (`libpython3.14.so`, стандартная библиотека) | python.org | PSF License |
| OpenSSL 3.0 (`libssl_python.so`, `libcrypto_python.so`) | в составе CPython для Android | Apache-2.0 |
| Starlette, uvicorn, h11, anyio, click, idna, sniffio, typing_extensions | PyPI | BSD-3 / BSD-3 / MIT / MIT / BSD-3 / BSD-3 / MIT или Apache-2.0 / PSF |
| smali, baksmali, dexlib2 (3.0.10) | Google | BSD-3 |
| Guava, failureaccess | Google | Apache-2.0 |
| ANTLR runtime 3.5.2 | antlr.org | BSD-3 |
| apksig (`apksigner.jar`) | Android SDK build-tools | Apache-2.0 |

## Игра и данные Gameloft

Modern Combat 5, её файлы, код, графика и все данные — © Gameloft. В репозитории и в APK моста их нет: игрок использует свою копию игры,
а мост применяет к ней правки на телефоне по описаниям (`bridge/patch/`).

Справочные данные сервера (`server-data`: CRM, события, каталог предметов, картинки Iris, настройки рекламы, таблица глав и уровней)
получены записью трафика настоящих серверов Gameloft и чтением памяти клиента (`documentation/development.md`). Они распространяются отдельно от кода
(в архиве кэша `MC5-cache-6.0.12a.zip` вместе с паками и главами игры), принадлежат Gameloft и нужны только для совместимости с игрой, которую игрок уже имеет.
