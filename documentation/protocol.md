# Протокол: что сервер отвечает клиенту

Клиент: `1924:56128:6.0.12a:android:googleplay`. Сервер — `server/mc5server.py` + `server/mc5/`.

**Принцип.** Протокол выведен из записей настоящего трафика (режим записи, [development](development.md#режим-записи)) и разбора
клиента. Записи задают *поведение*, а не готовые ответы: сервер строит ответы из своего состояния (учётки, токены, профиль, комнаты),
идентификаторы, токены, хэши, даты и адреса выдаёт свои. Из записи берётся только то, что настоящий сервер просто хранит:
каталоги, CRM, шаблоны событий, ассеты Iris (`server-data`).

## Порядок старта клиента

`sink has-conf-api` → Eve `datacenters`, `datacenters/<dc>/urls` → Pandora `locate?service=asset` → GDID `assign_global_id` →
Iris `HEAD GameOptions`, `bald…___index` → Pandora `auth` → Janus `authorize` → Janus `users/me` → Pandora `alert` →
Federation `POST sessions` (адрес игрового сервера) → Janus `encrypt_token` → Osiris `accounts/me`, Hermes, Osiris друзья/запросы →
Osiris `POST accounts/me name=SOLDIER_<n>` → Janus `authorize` (scope `tracking_bi`, `storage_ro`) → Iris события/видео/`game_object` →
`oct connectionstatus` → `iap check_limit`. Параллельно — TLS-сокет `alert` и TCP к игровому серверу AH.

## HTTP-сервисы (`server/mc5/gaia.py`)

Один процесс отвечает на HTTP :18080 и HTTPS :18443 (самоподписанный сертификат; клиент пропатчен). Имена заголовков ответа
пишутся с заглавной (`Date:`, `Content-Length:`, `Content-Type:`): **клиент ищет заголовки с учётом регистра**, uvicorn по
умолчанию пишет их строчными — отсюда были «вечные» таймеры и чат в CONNECTING.

| Сервис | Запрос | Ответ сервера |
|---|---|---|
| sink | `GET /has-conf-api` | 200, пустое тело, `x-ll-code: 204` |
| Eve | `GET /config/<client>/datacenters`, `…/datacenters/<dc>/urls`, `…/urls` | один ДЦ `eur`; все URL сервисов — этот сервер (Pandora и Federation — по HTTPS: с HTTP клиент их не вызывает) |
| Pandora | `GET [/<client>]/locate?service=X` | `text/plain` `host:port`; по TLS-запросу — TLS-адрес (схему Iris клиент берёт из URL Pandora); `alert` → :33508, `groupchat` → HTTPS-порт |
| GDID | `GET /assign_global_id/` | 19-значное число, одно на устройство (`hdidfv`) |
| Janus | `POST /authorize` | учётка создаётся при первом входе по credential (`anonymous:<b64>`), пароль запоминается; `access_token` своего формата, `token_type: gameloft_online`, `fed_id`, `scope` в каноническом порядке, `refresh_token`. С `access_token_only=1` — голая строка токена |
| Janus | `GET /users/me` | `account`, `credentials` — **массив строк** `тип:id` (объекты роняют клиент), `installations`, `alias` |
| Janus | `POST /encrypt_token`, `POST /games/mygame/alias` | обратимо зашифрованный токен (его проверяет наш AH); alias из 5 цифр |
| Federation | `POST /sessions/<client>/<credential>` | комната: `controller_host`/`controller_tcp_port` = наш AH, `room_id`, `encrypted_access_token` (scope `lobby`) |
| Anubis | `POST /rooms/<client>/automatch/quick_join_ah`, `quickplayany`, `quickplaynewplayer`; `GET /rooms/<client>` | комната с одним участником на нашем контроллере; список комнат `[]` |
| Osiris | `GET/POST /accounts/me`, `…/requests`, `…/connections/<kind>`; группы `/groups/…` (поиск, участники, стена) | профиль Osiris и кланы из состояния ([кланы](#кланы-и-чат)) |
| Hermes | `GET /messages/inbox/me`, `/messages/secured/me` | `[]` |
| Seshat | `POST /profiles/me/myprofile/consent` | проверка scope (`storage*`), без него 403, как у настоящего |
| Iris | `GET/HEAD /assets/<client>/<имя>[/metadata/hash]` | файл сам (без CDN), `asset-hash` и `ETag` = sha256 содержимого, 304 на `If-None-Match`; нет ассета — 404 |
| oct | `POST /connectionstatus` | `OK` |
| iap / ecomm | `GET /inapp_crm/index.php?action=check_limit`, `POST /` (`action=…`), `/iap/products`, `/iap/order`, `/iap/owned` | [магазин](#магазин-кредитов-без-google) |
| реклама a314 | `POST /un/index.hhh` | `event=init` — таблица мест (`ads_config.json`), свой `customID`; запрос баннера — «нет контента» |
| etsv2 | `POST /binary`, `POST /` | 200 (телеметрия) |
| чат | `/chat/…/subscribe`, `/v1/chat/…` | [чат](#кланы-и-чат) |
| прочее | любой путь | `{}` и запись в журнал (`UNKNOWN …`) |

Служебное: `GET /_mc5/ready` (мост ждёт его перед запуском игры), `GET /_mc5/log` (последние запросы).

### Токен Janus (`server/mc5/tokens.py`)

`<fed_id>,<scope>,<client_id>,<expiry>,<credential>,<device_id>,<dc>|<подпись>`: scope в каноническом порядке
(`leaderboard_ro lobby alert auth social chat session message`; неизвестное имя вроде `all` роняет клиент), срок 4 ч,
`refresh_token` — `refresh|…` на 35 суток. Подпись — HMAC сервера, клиент её не проверяет.

### Iris и главы (BALD)

Клиент спрашивает служебные файлы глав как `bald_android_astc_h___index` (`toc`, `hashes`, `version`); сервер отдаёт
`bald___index___.txt` и т.д. из папки глав (`--bald`; в мосте — папка самой игры `Android/data/<пакет>/files/bald`). Индекс — номер
выпуска (244). Если индекса нет (404), клиент повторяет запрос сотнями и считает главы нескачанными (PRELOAD).

### `alert` (:33508, `server/mc5/alert.py`)

TLS-сокет: `GET /alerts/me?…&content_type=event-stream` → `200`, `text/event-stream`, chunked, соединение держится. Событий нет
(в записях за 10 минут их тоже не было).

## Игровой сервер AH (:33600, `server/mc5/ah.py`, `ahproto.py`)

Сервер профиля игрока (`mc5AH_1924`), адрес приходит в Federation `sessions`.

**Рукопожатие** (строки JSON с `\n`): сервер `{"action":"create connection","success":"True","nonce":…}` → клиент
`{"access_token": <encrypted_access_token>, "action":"connect game", "room_id", "username": <credential>}` → сервер проверяет токен,
комнату и учётку → `{"slot":…,"success":true,"action":"connect game"}`.

**Кадры:** `тип (1) + длина (2, BE, с заголовком) + данные`; строка — `u16 BE длина + байты`; сжатое тело — `u32 BE длина + LZ4-блок`
(без кадра LZ4; `server/mc5/lz4.py`). Длина кадра 16-битная, поэтому CRM (~500 КБ JSON) сжимается.

**Сердцебиение задаёт сервер:** `1b` раз в секунду, клиент отвечает `1c` (мс с прошлого). Без него клиент через 60 с шлёт `14` и
проходит весь вход заново.

**id в кадрах `41`/`43`/`44`/`45`/`46`/`72`** — FNV-1a 32 (big-endian) от имени: предложения, кредита, поля профиля или причины
изменения (`general_stat_update`, `endmission`, `activity_reward`, `claim_event_milestone`, `pending_inventory_tr`…).

### Вход

- Первый вход: `01` + `I` → `4f` (время), `23` (статичный конфиг), `4a`, участие в событиях (`46 tournaments_sem`), `28` (события),
  `27` (полный профиль, у нового игрока — шаблон со своими `created`, `deviceId`, `country`); `t` → `70` (alias), `75` (флаги),
  `46 active_subs`, `3f` (CRM), `47` (ежедневные предложения), `28`; `50` + `0b` + `34` → `3d` (лига), `3e`, `28`.
- Повторный вход (профиль в кэше): `4f`, `23`, `37` (рейтинг), `3d`, `55` × N (места в событиях), `22`, `3e`.
- Клиент запрашивает полный профиль (`I`) и при обычном входе: сервер успевает применить изменения (например, открыть главу) до `27`.

### Кадры клиента

| Кадр | Что | Ответ сервера |
|---|---|---|
| `01` | вход: страна, язык, client_id, URL, device_id, модель | см. «Вход» |
| `49` `I` / `74` `t` | профиль / остальное | см. «Вход» |
| `16` | `00 10` — профиль в кэше; `00 0e`/`00 00` — вход в матч и выход; `01 <номер>` + JSON — сохранение лоадаута | `28` на `00 10`; лоадаут → `inventory.loadouts[номер]`, без ответа |
| `0b`, `50`, `34`, `19`, `21` | имя, credential, лиги, лиги из меню матча, обновление состояния | лиги/рейтинги/места, как при входе |
| `59`, `ad`, `52`, `1d` | возраст и пол, обучение, время, синхронизация | `52` → `4f`; `1d` → `4f` + `1e` |
| `10` | старт уровня `{"level","node"}` | `45 energy` + `10`; запоминается `current_mission` |
| `11` | результат миссии: заголовок, JSON статистики, двоичный хвост | см. «Кампания» |
| `96`, `06`, `a3` | конец миссии, данные уровня, следующий уровень | `27` профиль; `07` (зашифрованный блок уровня из записи или `u32 0`) |
| `41` | купить предложение (`u32 0`; аренда — другое значение) | `46` с тем же id или отказ `45` (статус 4 — не хватает валюты) |
| `43` | использовать кредит (пак, награда) | `46` с итогами |
| `81` | посмотрел пак | без ответа (`battlepacks_history.viewed`) |
| `44` | «оплачено, выдайте» (магазин) | `46` с итогами |
| `24` | обновить VIP-бусты | `46 {"boosts"}` — **только если набор постоянных бустов изменился** (иначе окно «Reached VIP level» при каждом входе) |
| `72` | забрать отложенную награду (`_pending_inv`) | `46 pending_inventory_tr` с бустом |
| `66` | случайный ещё не полученный killsign | `45 {"default_killsig_N":1}` |
| `48` | «клиент показал значение поля» (`_inventory_shadow.upd_<поле>`) | без ответа, сервер обновляет тень |
| `1a` | настройка/флаг профиля (`killsign`, `core`, …) | в `_settings`, без ответа |
| `64`, `7f` | забрать задачу Activities / веху | см. «События» |
| `76` | создать/изменить клан | `77` |
| `05` | выйти из комнаты | `1f` |
| `0e` | вход в матч (49 Б) | **не реализовано** (см. «Мультиплеер») |
| `17`, `2a`, `2b`, `68`, `69`, `67`, `0c`, `a8` | разное | без ответа (так и у настоящего) |

Все кадры клиента пишутся целиком в `serverdata/ah_frames.jsonl`; неизвестные — ещё и в журнал как `unknown frame`.

## Кампания

- `10` старт уровня: `current_mission` (уровень, узел, бусты), энергия.
- `11` результат (`ah.apply_result`): `_inventory.xp += Σ xp.* + 1` (так у настоящего), `statistics.sp.*` суммируются
  (`killstreak.*` — максимум), запись `progress[{level, node, objective2, objective3}]`, `highest_unlocked_mission`, при первой
  победе — режимы (`assault`, `battleroyale`, …). Ответ: `45 _stats_update`, `46 endmission` (режимы, открытые главы), `45` награда
  (`_mission_rewards` из CRM: `pb_credits` + взвешенный выбор), `12 {"sp","xp"}`, CRM, события.
  Результат без запущенной миссии → `12 {"error":-3}` (защита от двойного счёта при повторе после переподключения).
- Не повторено: `distance_run` (отдаётся 0), статистика оружия из двоичного хвоста, повышение уровня (`46 level_up_rewards`
  с `_levels` и `_pending_inv.levelup_N`) — пороги опыта теперь известны (`campaign.json`), выдача не сделана.

### Главы (зоны)

Глава *i* (с 0) закрыта, пока `i > _inventory.unlocked_zones` (у нового игрока 1: Venice и Tokyo). Условия «Zone N» (открывает
главу N+1) — CRM `game._zones_unlock`: `servicestars`, `playerlvl`, `finishmp`, `sqdmember`, `weaptier`+`weapcount`, `openpacks`,
приз `prize_name`×`prize_qty`; обязательное условие — все сюжетные миссии предыдущей главы. Необязательные можно пропустить
покупкой `skip_unlock_zone_N`. Нажатие на замок ничего не отправляет: открывает **сервер** (`liveops.zone_unlocks`) — перед
отправкой профиля, в шаге `endmission` результата и после покупки пропуска:

- сюжетные миссии — `node` из `campaign.json` (`story_nodes` по главам; сняты из памяти клиента) против `progress[].node`;
- звёзды — Σ по `progress` (1 + `objective2` + `objective3`);
- уровень — число порогов `campaign.json.xp_levels` ≤ `_inventory.xp`;
- `finishmp`, `sqdmember`, `weaptier`/`weapcount`, `openpacks` сервер пока не считает — только пропуском.

Открытие: `unlocked_zones = N`, `_inventory_shadow.upd_unlocked_zones = N`, приз (у Zone 1 `AR03_bp`×99999 — заглушка, не выдаётся).

## Экономика (`server/mc5/economy.py`)

Всё — по таблицам CRM (`game._credits`, `_offers`, `_battlepacks_def`, `_battlepacks_configs*`, `offline_store.prices`) и каталогу
Iris `game_object`. Ответ на покупку — **новые итоги** (`{"credits": 63200, …}`), а не приращения.

- **Кредиты и паки** (`43`): пак → взвешенная стадия → предметы, группы `<категория>#<tier>` (любой выпадающий предмет категории и
  уровня), ядра `core#XY`. Уровни оружия для `weapon_bp#N` — данные клиента, сейчас любой чертёж кроме исключений (приближение).
- **Предложения** (`41`): цена из `offline_store`, предметы из `_offers`; автоактивируемые кредиты открываются сразу вторым `46`.
- **Lucky Spin** = предложение `ultimate_battlepack…`: цена по шагу `ud_step` (`ultimate_draw_prices`), предмет выпадает один раз
  (`ultimate_draw.ud_inventory`). `ud_step` клиент читает **из корня профиля** (вложенный не читает). Конец розыгрыша
  `ultimate_draw_end` сервер продлевает по неделям; промо-окно «FREE SPIN!» из CRM убирается после первого спина.
- **Аренда «TRY IT»** — шаблонные предложения: кредит `wp_rent_t<N>` (`is_template`, тир N, срок `validity` 360 мин) клиент раскрывает
  в `<оружие>_rent` для каждого оружия тира N, предложение `rent_weapon_tier_<N>` — в `rent_weapon_tier_<N>_<оружие>_rent`; id в `41` —
  FNV-1a этого имени (`rent_weapon_tier_3_AR03_rent` = `97d90471`). Сервер раскрывает шаблоны по всем оружиям каталога, списывает цену
  и выдаёт буст `{<оружие>: [{expiry = минуты + validity, factor, from_credit, timestamp}]}`. Аренда брони (`body_sets_rent`) — нет.
- **Бусты и отложенные награды** (`24`, `72`), **killsign** (`66`), **тени** (`48`) — см. таблицу кадров.
- **Бандлы за кредиты** — те же предложения; эффекты автоактивируемых `unlock_weapons_<класс>` / `upgrade_skills_<класс>` не известны,
  у нас только счётчики.

## События и Activities (`server/mc5/liveops.py`)

- События (`28`) строятся из шаблонов записи: **каждое повторение — новый экземпляр**, как у настоящего: свой `id` (uuid1 времени
  создания `_created_on`, узел записанного), свои `_milestone_id`, даты сдвинуты на целое число периодов (сутки или неделя).
  Ежедневные варианты одного события (`ACTIVITIES_Upd27_V2`, `_V3`) чередуются по дням. `groupware.events` в CRM переписывается на
  id экземпляров.
- Участие игрока — `tournaments_sem` по `event_id`: на новый экземпляр — новое участие, забранные задачи и вехи не переходят.
  `initial_activities_stats` — **текущие счётчики игрока** (клиент показывает прогресс как «счётчик − начальное»; с нулями ветеран
  сразу «выполнял» все задачи, и клиент сам их забирал). Счётчики: `singleplayer_kills` = `statistics.sp.kill.total`,
  `singleplayer_headshots` = `sp.kill.headshots`, `singleplayer_missions` = `sp.game.campaign.wins`; MP/BR — 0.
- `64` (задача): `46 activity_reward` `{<награда>: итог, "tournaments_sem": участие с claimed_activities}`; повтор не начисляет.
- `7f` (веха по очкам): `46 claim_event_milestone` c полями `_sem_event_id`, `_sem_milestone_id`, `success` (без них клиент вех не
  показывает). Известная ошибка: экран Challenges не снимает CLAIM с забранной вехи (формат поля участия у настоящего не записан).
- CRM (`3f`): `expiry` — следующая полночь UTC; `didomi_type: []` (окно Didomi без сети не грузится; `MC5_DIDOMI=on` — как в записи). Сам SDK выключен в клиенте ([client-patches](client-patches.md#окно-согласий-didomi)).
- Ежедневные предложения (`47`): `expiry` в минутах.

## Магазин кредитов без Google

Покупка за реальные деньги — цепочка нативной IAP-библиотеки клиента и Java-адаптера Google Play Billing. Адаптер заменён
`mc5.Store` ([client-patches](client-patches.md)), проверка подписи ответа отключена (`IAP_NOVERIFY`).

1. Список товаров: `GET /iap/products?ids=` — описания из CRM `iap.prices` (id Google = `billing_methods[googleplay].content_id`, цена).
2. `POST /` `action=pre_transaction` → `{"status":"1"}` + заголовок `X-InApp-Hash`.
3. `mc5.Store` создаёт заказ `POST /iap/order` и отдаёт слою Gameloft «покупку» с подписью `MC5LOCAL`.
4. `POST /` `action=transaction&…&rdata=<заказ>` → `{"status":"delivered","transaction_id":…}`, заказ оплачен.
5. AH `44` (FNV-1a `entry_id` записи CRM) → `46` с итогами (`bundle` из CRM: кредиты, VIP-очки, предметы; автоактивируемые бусты бандлов —
   бусты на `validity`); повтор не выдаёт второй раз. Неизвестный id выдаёт самый старый оплаченный заказ (так работает RESTORE).
6. `action=end_transaction` → `{"status":"1"}`.

`GET /iap/owned` — «купленное» для RESTORE PURCHASES (невыданные заказы). Подписки VIP (`verify_subscription`) не проверены.

## Кланы и чат

- Кланы: AH `76` создаёт/правит клан владельца (`77 {"answer": <группа>}`), Osiris `/groups/…` отдаёт группы, участников, стену
  (`server/mc5/social.py`).
- Чат (`server/mc5/chat.py`, тот же HTTPS-порт): `POST /chat/channels/<имя>/subscribe` → `cmd_url`, `listen_url`, `https_listen_url`;
  `GET /v1/chat/…` — SSE: `room_info` (и каждые 30 с), история (последние 100), новые сообщения; `POST` туда же — отправка, рассылка
  всем слушателям. Сообщения настоящих игроков из записи не переносятся.

## Мультиплеер (не реализован)

Записано (custom-матч с игроками и Team Battle с ботами):

- Anubis `quickplaynewplayer`/`quickplayany` → комната; у нас она указывает на наш контроллер, но матч не начинается.
- Контроллер (тот же протокол AH): `0e` (49 Б, настройки матча) → `4f`, `23`, `0f` (u16 порт UDP боя), `55`, `37`, `3d`. Без UDP
  клиент через ~50 с шлёт `05`, получает `1f` и возвращается в меню.
- UDP боя: датаграмма — цепочка сообщений `u32 длина (вместе с собой) + 9 байт заголовка + u8 тип + данные`. Заголовок похож на
  «надёжный UDP»: байт 0 — флаг надёжного (повтор раз в ~1,2 с до подтверждения), байт 1 — номер/подтверждение, байты 4–8 — маска
  принятых. Рукопожатие `01` ×N → `02` (78 Б: эхо, версия `03 21`, параметры матча) → `03` (165 Б, имя игрока); пульс `15` ~5 раз в с,
  подтверждения `13`; снимки `29`/`2b`/`40` ~12 Гц; `1e` — надёжные (начало матча). Разбор: `tools/udp_decode.py`.

План — [roadmap](roadmap.md#мультиплеер).

## Неизвестно (нужна запись или разбор клиента)

- `participants/me` (Challenges), `ingamenews` — запросы есть, ответы не записаны (сервер отвечает `{}`).
- Пороги VIP-уровней и выдача `vip_booster_lvlN` / `_vip_rewards` при смене уровня.
- Эффекты классовых бандлов; 15 слотов лоадаута и `previous_loadout` у настоящего; формат участия, по которому экран снимает CLAIM вех.
- Что делает настоящий сервер после конца розыгрыша Lucky Spin.
