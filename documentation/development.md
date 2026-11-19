# Разработка

## Что нужно

Ничего не ставится глобально: тулчейны лежат в корне проекта, пути задаёт `env.sh` (`source env.sh`).

| Путь | Что | Откуда |
|---|---|---|
| `../__shared-third-party__/jdk/` | JDK 17+ (`javac`, `keytool`) | любой OpenJDK |
| `../__shared-third-party__/android-sdk/` | build-tools **34.0.0** (`aapt2`, `d8`, `zipalign`, `apksigner`), platform **android-34**, platform-tools (`adb`) | Android SDK command-line tools |
| `../__shared-third-party__/ndk/` | Android NDK **r27c** | developer.android.com |
| `../__shared-third-party__/pyandroid/` | распакованный `python-3.14.0-aarch64-linux-android.tar.gz` (`prefix/`) | python.org (официальная сборка для Android) |
| `../__shared-third-party__/tools/smali/` | `smali`, `smali-baksmali`, `smali-dexlib2`, `smali-util` **3.0.10**, `guava-31.1-android`, `failureaccess`, `antlr-runtime-3.5.2`, `jsr305` | Google Maven / Maven Central (`apktool.jar` не годится: урезан) |
| `bridge/build/wheels/` | `starlette`, `uvicorn`, `h11`, `anyio`, `click`, `idna`, `sniffio`, `typing_extensions` — чистые колёса `py3-none-any` | PyPI |
| `.venv/` | Python 3.8+ для сервера на ПК и инструментов: `pip install -r server/requirements.txt` | — |
| `gamebin/latest-from-google-play-6.0.12a/apks/` | оригинальные `base.apk`, `split_config.arm64_v8a.apk` (или `GAME_APKS=<папка>`) | ваша игра из Play |
| `server/data/` | данные сервера (`server-data/` архива кэша) | см. ниже |
| `gamebin/latest-from-google-play-6.0.12a/device_data*`, `external_files` | снимок установки из Play: приватная папка игры и `Android/data/<пакет>/files` (источник архива кэша; `CACHE_PRIVATE`, `CACHE_EXTERNAL`, `CACHE_EXTRA`) | копия с телефона (root или `run-as` debuggable-сборки) |

`smali` под API 35 пишет dex 041 с неверным заголовком, поэтому оверлей собирается под API 34 (dex 039).

## Сборка

```sh
tools/build_mc5trace.sh    # mc5trace/*.c -> work/mc5trace/{libmc5net.so, libmc5trace.so, wrap-*.sh}
bridge/build_apk.sh        # мост A для себя: bridge/MC5-Bridge-debug.apk (иконка игры, libmc5trace, server/data внутри)
RELEASE=1 bridge/build_apk.sh   # мост A релизный: bridge/MC5-Bridge-<версия>.apk, ключ bridge/build/release.keystore (+ release.pass)
tools/build_full.sh        # игра B на ПК: work/full/MC5-full.apk (ключ work/patched-apk.key); SKIP_BASE=1 — без пересборки моста
tools/build_debug.sh       # «MC5 Debug»: work/full/MC5-debug.apk (ключ work/debug-apk.key)
tools/make_release.sh      # release/<версия>/ и release/cache/ (архив кэша для игроков: tools/mk_cache_zip.py)
tools/build_ptrace_log.sh  # work/ptrace_log, work/campdump (отладка на телефоне)
```

Версия моста — `versionName` в `bridge/AndroidManifest.xml`. **Релизный ключ** (`bridge/build/release.keystore`, `release.pass`)
создаётся при первой сборке; храните копию: без него новая версия моста не встанет поверх старой.

Поставить игру B с ПК без потери данных: `tools/adb install -r work/full/MC5-full.apk` (ключ `work/patched-apk.key` должен совпадать
с ключом телефона `BridgeGames/<пакет>/patched-apk.key`, иначе `INSTALL_FAILED_UPDATE_INCOMPATIBLE`).

## Данные сервера

`server/data/` (или `--data <папка>`, `MC5_DATA`) — справочные данные Gameloft, в репозиторий не входят:

| Файл | Откуда |
|---|---|
| `ah/crm.json`, `ah/events.json`, `ah/config.bin`, `ah/new_profile.json`, `ah/meta.json`, `iris/*`, `ads_config.json` | из записи сессии: `tools/mk_seed_from_trace.py work/real/<запись>` (`--iris-only` — только картинки Iris другой записи) |
| `ah/levels_07.json` | зашифрованные блоки уровней кампании — ответы настоящего сервера на кадр `06` из записи (снимались разовым скриптом: `{уровень: hex}`) |
| `ah/campaign.json` | из памяти клиента: `tools/mk_campaign_json.py campdump.txt xp_dump.txt server/data/ah/campaign.json` (см. «Отладка») |

Обязательные файлы перечислены в `mc5server.DATA_FILES`: без них сервер пишет `NO SERVER DATA … missing …` и останавливается.
Готовый набор — папка `server-data/` архива кэша `MC5-cache-6.0.12a.zip`.

### Архив кэша

`tools/mk_cache_zip.py` собирает архив для игроков из снимка установки из Play: паки `files/assetpacks`, файлы `didomi_*` и четыре файла
согласия Didomi (после патча `didomi.spec` не обязательны, оставлены как проверенный набор) из `shared_prefs` (в `<пакет>_preferences.xml` скрипт допускает только ключи Didomi/IAB, иначе останавливается), главы `bald/`
(незавершённые `temp_*` — ошибка), `iris_*_cache.bin`, `compliancy.bin`, `dcsbin`, `InsTime`, плюс `server/data` как `server-data/`.
Записи без сжатия (паки и главы уже сжаты), архив ~2,2 ГБ с Zip64; на GitHub (лимит 2 ГБ на файл) он не помещается — выкладывается отдельно.

## Сервер на ПК

```sh
tools/run_servers.sh [--data <папка>] [--host 0.0.0.0]   # один процесс: HTTP 18080, HTTPS 18443, alert 33508, AH 33600; журнал work/server_run.log
tools/reverse_all.sh                                       # держит adb reverse на всех телефонах (пробросы слетают при переподключении USB)
```

Игра на телефоне ходит на `127.0.0.1`: с `adb reverse` она попадает на ПК (порты моста на телефоне при этом должны быть свободны:
остановите игру B). Для режима «Подключаться к другому серверу» сервер запускают с `--host 0.0.0.0`; WSL2 для этого не годится
(`localhostForwarding` не открывает порты в сеть) — запускайте сервер в Windows. Состояние — `work/state/mc5_state.json` (`--state`).
Сервер сохраняет любые ключи состояния: не кладите туда тестовые поля.

| Переменная | Что |
|---|---|
| `MC5_STATE`, `MC5_DATA` | путь состояния и данных (то же, что `--state`, `--data`) |
| `MC5_STATE_MIRROR` | куда копировать состояние (мост: `BridgeGames/<пакет>/mc5_state.json`), не чаще раза в 10 с |
| `MC5_UVICORN_LOG` | уровень журнала uvicorn (`debug` — подробно) |
| `MC5_DIDOMI=on` | оставить в CRM окно согласий Didomi (по умолчанию убрано) |
| `MC5_PUBLIC`, `MC5_PUBLIC_TLS` | адреса, которые сервер сообщает клиенту (по умолчанию `127.0.0.1:18080` / `:18443`) |
| `MC5_UPSTREAM`, `MC5_TRACE`, `MC5_SOCKS` | режим записи (ниже); `MC5_SOCKS_TCP=direct` — сырые сокеты мимо прокси (диагностика) |

## Режим записи

Как получен протокол: сервер пересылает трафик игры на настоящие серверы Gameloft и пишет всё целиком. Работает, пока серверы
Gameloft живы; учётку могут забанить (эталонную забанили на 7 дней 25.10.2026).

```sh
MC5_UPSTREAM=1 MC5_TRACE=work/real/<запись> MC5_SOCKS=<host:port SOCKS5> tools/run_servers.sh
```

- На телефоне — «MC5 Debug» (`libmc5trace.so` с `MC5_REDIRECT=1`): каждое имя Gameloft получает свой адрес `127.10.x.y`; HTTP(S) идёт на
  сервер ПК, остальные TCP — через туннель :33698, UDP боя — через туннель :33699 (оба по `adb reverse`), так что записываются и адреса
  из двоичных протоколов (лобби → контроллер матча).
- `server/mc5proxy.py`: маршрутизация по пути (Janus, Osiris, `sessions`, Anubis, GDID — на настоящие хосты), пул relay-портов
  33710–33809 для адресов из ответов, TLS терминируется у нас, повтор при обрыве прокси.
- Запись: `http.jsonl` (запросы и ответы целиком), `tcp.jsonl` (потоки `alert`, AH, чата, туннелей и `udp:<порт>` в hex), `relays.json`.
- `tools/import_from_trace.py <запись>` переносит записанного игрока на свой сервер; `tools/udp_decode.py <tcp.jsonl> [--stats]` —
  разбор UDP боя.

## Отладка

- **Журналы:** на телефоне — `BridgeGames/<пакет>/mc5.log` (установщик и мост) и `server.log` (сервер); экран моста → «Показать журнал
  сервера» или кнопка в уведомлении; на ПК — `work/server_run.log`;
  все кадры AH — `ah_frames.jsonl` рядом с состоянием; logcat: `python` (сервер в мосте), `mc5bridge` (мост), `mc5trace` («MC5 Debug»).
  Буфер logcat у некоторых прошивок вмещает меньше минуты: `adb logcat -G 16M`.
- **Данные B без root:** B — debuggable, поэтому `adb shell run-as com.gameloft.android.ANMP.GloftM5HM …` читает и пишет его папку;
  править состояние — только при остановленной игре (`am force-stop`), файлы — через `/data/local/tmp`.
- **`ptrace_log`** (`tools/ptrace_log.c`): точки останова в `libMC5.so`, печать строки (`std::string`, `:p` — `char*`) или 2 КБ памяти
  (`:x`) по регистру. Без root: скопировать в папку B и запускать через `run-as` (`process_vm_readv` + `PTRACE_POKEDATA`):

  ```sh
  adb push work/ptrace_log /data/local/tmp/ && adb shell run-as <пакет> cp /data/local/tmp/ptrace_log .
  adb shell run-as <пакет> ./ptrace_log $(adb shell pidof <пакет>) libMC5.so 4fcc88:0:p    # все строки, которые клиент хэширует FNV-1a
  ```

  Полезные адреса (6.0.12a): `0x4fcc88` и `0x506218` — FNV-1a (имена id в кадрах), `0xc49c78` — журнал IAP-библиотеки (`:1`),
  `0x798b40` — таблица опыта (`:0:x`), `0x5c2d30` — узел миссии (`:0:x`).
- **`campdump`** (`tools/campdump.c`): таблица кампании из памяти работающей игры (главы → локации → миссии, `node`);
  `run-as <пакет> ./campdump <pid> > campdump.txt`, затем `tools/mk_campaign_json.py`.
- **Перед разбором кода нативки — журнал** (`ptrace_log`): статический разбор без журнала долгий.

## Форматы данных игры

- Архивы `.gla2`/`.dcmp`: заголовок 16 байт (`d0 ee a8 9a`), данные, индекс в конце (Android: записи по 24 байта, 32-битный хэш;
  iOS: 22 байта, 64-битный хэш). `flags=8` — LZ4-блок, `0` — как есть, `1` — шифр (XOR с позиционной гаммой; только `strings`,
  `options`, `levels2`, один файл `sounds`; клиент читает их сам). Инструмент: `tools/gla.c` (`check`, `list`, `sums`, `extract`).
- Главы (BALD, внешняя папка игры `bald/`): `bald___index___.txt` (номер выпуска, 244), `bald___version___.txt` (6.0.12a),
  `bald___toc___.txt` (52 ассета `bald_android_astc_h_<архив>_gla2_<ревизия>`), `bald___hashes___.txt` (md5 чанков по 2 МБ).
- Паки (`files/assetpacks/assetPack_HighSlow0..4/601213/601213/assets/`): 72 архива `.gla2` с ASTC-текстурами, ~1,4 ГБ.

## Особенности окружения (WSL + Windows adb)

- `tools/adb` под WSL вызывает `adb.exe` Windows: пути для `push`/`install` — через `wslpath -w`, вывод с `\r\n`;
  `ANDROID_SERIAL` он не читает — с двумя телефонами всегда `-s <serial>`.
- WSL не видит `adb forward` Windows: проверять порты на телефоне через `adb shell … nc`.
- `adb shell appops`/`pm grant` для «доступа ко всем файлам» и `pm clear` на новых Android запрещены: разрешения выдаёт игрок.
