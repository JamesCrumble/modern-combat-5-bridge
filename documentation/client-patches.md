# Правки клиента

Все правки применяются патчером к файлам игрока (`bridge/patch/`, [architecture.md](architecture.md#патчер)). Клиент — Google Play
**6.0.12a** (`versionCode 601213`); другую версию патчер не примет: SHA-256 `libMC5.so` сверяется с `native.spec`, каждая байтовая
правка проверяет исходные байты, каждая правка dex — что якорь найден.

## Зачем вообще править клиент

Без root нельзя ни подменить адреса средствами системы, ни добавить свой CA (Android 7+ не доверяет пользовательским сертификатам
в приложениях). Каждый адрес, который клиент берёт не у нашего сервера, кончается либо обращением к Gameloft, либо «Failed to
connect» без сети. Поэтому: проверки сертификата и сети отключены в клиенте, зашитые адреса заменены, остальное ловит
`libmc5net.so` на уровне `getaddrinfo`/`connect`.

## `libMC5.so` (`bridge/patch/native.spec`)

| Правка | Где | Зачем |
|---|---|---|
| строка `https://eve.gameloft.com` → `http://127.0.0.1:18080` | точка входа Gaia (Eve) | первый запрос клиента идёт на наш сервер |
| `TLS_NOVERIFY`: `X509_verify_cert` (0x11908b8) → `return 1`; ветка `app_verify_callback` в `ssl_verify_cert_chain` (0x10fc644) → всегда `X509_verify_cert` | статический OpenSSL 1.1.1 клиента (им пользуются и libcurl, и asio-сокет `alert`) | клиент принимает самоподписанный сертификат сервера; имя хоста curl по-прежнему сверяет с SAN, поэтому в сертификате `127.0.0.1` и `*.gameloft.com` |
| `IAP_NOVERIFY`: функция проверки подписи ответа e-commerce (0xd05648) → `return 0` («подпись верна») | нативная IAP-библиотека клиента | ответ магазина требует заголовок `X-InApp-Hash` (MD5 тела + секрет Gameloft); подделать его нельзя |

Строки, которые остаются в клиенте (`sink.gameloft.com`, адреса из ответов, второй источник Eve), перехватывает `libmc5net.so`.

## Манифест (`bridge/patch/manifest_add.txt`, `Axml.java`)

- arm64-split вклеивается в `base.apk`, `requiredSplitTypes` очищается: B ставится одним файлом.
- `extractNativeLibs=true` и `debuggable=true`: Android выполняет `lib/arm64-v8a/wrap.sh` только у debuggable-приложений, а
  `wrap.sh` должен лежать на диске.
- Добавлены права (сеть, служба переднего плана, уведомления, доступ ко всем файлам), служба `ServerService`
  (`foregroundServiceType=specialUse`, `0x40000000`), экран `SettingsActivity` (LAUNCHER). У `MainActivity` игры LAUNCHER снят:
  игру запускает мост явным интентом на `MainActivity` (не `GameInstaller`: тот вызывается из неё).
- `usesCleartextTraffic`: Java-часть клиента ходит к нашему серверу по HTTP.
- «MC5 Debug» — `manifest_debug.txt`: то же, другое имя экрана.

## Java-часть (`classes4.dex`, `bridge/patch/dex/*.spec`)

| Файл | Класс / метод | Что делает правка | Почему |
|---|---|---|---|
| `assets.spec` | `installer/AssetsManagerPlugin`: `getAbsoluteAssetPath`, `isDownloadCompleted`, `onPluginStart`, `onPreNativePause/Resume`, `openWifiConfirmation` | паки — локальные файлы `files/assetpacks/<пак>/601213/601213/assets`, «скачано» всегда да, Play Core (`AssetPackManager`) не создаётся | Play Asset Delivery отвечает `-13` («Unrecognized installation») приложению с чужой подписью, а без сети — `-6` |
| `net.spec` | `UtilsNetworkStateReceiver.CheckConnectionType/hasConnectivity`, `SUtils.hasConnectivity`, `AndroidUtils.initCheckConnectionType`, `AdsUtils.GetConnectivityType`, `Device.IsWifiEnable`, `GameInstaller.V/n` | клиент всегда «онлайн по Wi-Fi»; проверка интернета установщиком (GET `https://www.google.com`) всегда успешна | сервер на `127.0.0.1` для Android — не сеть: без этого нативная часть вообще не идёт в сеть, а установщик показывает «download could not be completed» |
| `hosts.spec` | `PushNotification/RemoteImageManager`, `installer/GlotImp/b` | Eve картинок push и телеметрия установщика (`etsv2`) → `http://127.0.0.1:18080` | Java не доверяет самоподписанному сертификату, поэтому HTTP |
| `iap.spec` | `iab/GMPUtils$a..e` (`a(Bundle)`), `iab/s` | пять задач Google Play Billing (старт, описания товаров, покупка, расход, купленное) сначала вызывают `mc5.Store.run`; `s.v` принимает подпись-маркер `MC5LOCAL` | магазин кредитов без Google: каталог и заказы — наш сервер ([protocol.md](protocol.md#магазин-кредитов-без-google)) |
| `didomi.spec` | `didomiwrapper/DidomiWrapper`: `StartDidomi`, `IsReady`, `ShouldConsentBeCollected`, `IsNoticeVisible`, `IsPreferencesVisible`, `SetupUI`, `Show*`/`Hide*`; класс `mc5/DidomiReady` | SDK согласий не запускается: `StartDidomi` сразу сообщает нативной части «готово» (`NativeOnReady` через главный поток, как колбэк SDK), согласие «не нужно», окна «не видны», показ — пустой | SDK Didomi грузит конфиг и веб-окно с `sdk.privacy-center.org`; без сети новый игрок навсегда вставал на загрузке первой миссии (~88 %) |
| `trace.spec` | `installer/GameInstaller` (только «MC5 Debug») | состояния установщика в logcat (тег `mc5trace`) со стеком; класс `mc5/T` | логи Java-слоя Gameloft вырезаны ProGuard |

`mc5.Store` (`bridge/src/mc5/Store.java`) — наш класс в dex моста: говорит со слоем Gameloft через рефлексию (ключи Bundle `a4`
статус, `a7` JSON покупки, `a8` подпись, `b1` товары, `b3` тип), а с сервером — по HTTP (`/iap/products`, `/iap/order`, `/iap/owned`).

## Библиотека сети (`mc5trace/`)

`libmc5net.so` (игра) и `libmc5trace.so` («MC5 Debug») собираются из одних исходников (`tools/build_mc5trace.sh`):

| Часть | Что |
|---|---|
| `00_head.c`, `40_init.c` | общая часть, старт (журнал включается только после конструктора: на Android 16 libc вызывает `access()` ещё внутри `malloc`) |
| `05_names.c`, `10_net.c` | `getaddrinfo`/`gethostbyname`/`connect`: хосты Gameloft → `127.0.0.1` (игра); в отладке — свой адрес `127.10.x.y` на каждое имя и туннели на ПК |
| `15_udp.c` | только отладка: UDP боя на ПК через TCP-туннель (`adb reverse` носит только TCP) |
| `20_file.c`, `25_openat.c` | только отладка: файлы, которые клиент не смог открыть |
| `30_iris.c` | только отладка: логгер `[IRISCfgProvider]` (`0x1386098`), у которого в релизе нет приёмника |

## Окно согласий Didomi

Две меры с двух сторон. Сервер отдаёт в CRM `didomi_type: []` (без экрана возраста и согласия; `MC5_DIDOMI=on` — как в записи), а
`didomi.spec` выключает сам SDK: без этого патча чистая установка без сети не проходила загрузку первой миссии, даже с файлами согласия
из установки Play (кэш `files/didomi_*`, `shared_prefs/DIDOMI_*`, ключи `Didomi_*`/`IABTCF_*`). Эти файлы в архиве кэша остались —
с ними установка проверена, но после патча они не обязательны.

## Чего правки не делают

- Лицензия и Play Integrity: серверы Gameloft их не проверяли, клиент сам обращается к SafetyNet, без сети это ни на что не влияет.
- Шифрованные архивы (`strings`, `options`, `levels2`): клиент читает их сам, правки не нужны.
