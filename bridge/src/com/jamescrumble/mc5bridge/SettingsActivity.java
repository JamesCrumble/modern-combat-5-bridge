package com.jamescrumble.mc5bridge;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.graphics.Color;
import android.os.Bundle;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;

/**
 * Launcher screen of the bridge (layout and widgets after the EW3 bridge's SettingsActivity): the state of the game, the server mode, debugging, and
 * "Играть", which starts the backend (embedded server or forwarders) and then the game.
 */
public final class SettingsActivity extends Activity {
    private static final int BG = Color.rgb(18, 22, 26), FG = Color.rgb(230, 235, 238), DIM = Color.rgb(140, 150, 156),
            ACCENT = Color.rgb(128, 203, 196), WARN = Color.rgb(255, 183, 77);

    private Settings settings;
    private float dp;
    private TextView gameInfo, serverInfo, notifyInfo, folderInfo;
    private EditText serverAddr;
    private boolean hadAccess, asked;
    private AlertDialog busy;

    @Override protected void onCreate(Bundle state) {
        // the theme is set here, not in the manifest: in the combined APK the manifest is the game's (no bridge resources)
        setTheme(android.R.style.Theme_Material_NoActionBar);
        super.onCreate(state);
        getWindow().setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(0xFF000000));
        getWindow().setStatusBarColor(0xFF12161A);
        getWindow().setNavigationBarColor(0xFF12161A);
        dp = getResources().getDisplayMetrics().density;
        settings = Settings.load(this);
        GameWatch.install(this);
        BridgeLog.hookCrashes(this);

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(px(20), px(16), px(20), px(24));
        col.addView(text("Modern Combat 5 — мост", 22, FG, true));
        col.addView(text("Сервер и запуск игры на этом телефоне. Настрой и нажми «Играть».", 13, DIM, false));
        folderInfo = text("", 12, DIM, false);
        folderInfo.setPadding(0, px(6), 0, 0);
        col.addView(folderInfo);

        col.addView(section("Игра"));
        gameInfo = text("", 14, FG, false);
        gameInfo.setPadding(0, px(6), 0, 0);
        col.addView(gameInfo);

        col.addView(section("Сервер"));
        notifyInfo = text("Уведомления выключены: Android может остановить сервер, когда игра свёрнута. Нажмите здесь, чтобы разрешить уведомления.",
                13, WARN, false);
        notifyInfo.setPadding(0, px(8), 0, px(2));
        notifyInfo.setOnClickListener(v -> startActivity(new Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, getPackageName())));
        col.addView(notifyInfo);
        col.addView(toggle("Подключаться к другому серверу", Settings.SERVER_CUSTOM,
                "Выкл: игра работает со встроенным сервером (он запускается этим приложением). Вкл: игра подключается к серверу по адресу ниже "
                        + "(например, второй телефон с этим мостом или компьютер с server/mc5server.py), встроенный сервер не запускается. "
                        + "Нужен IPv4-адрес; порты те же, что у встроенного: 18080, 18443, 33508, 33600–33602."));
        serverAddr = new EditText(this);
        serverAddr.setHint("192.168.1.20");
        serverAddr.setText(settings.get(Settings.SERVER_ADDR));
        serverAddr.setTextColor(FG);
        serverAddr.setHintTextColor(DIM);
        serverAddr.setSingleLine();
        // TYPE_NUMBER_FLAG_DECIMAL would allow a single dot; an IPv4 address has three
        serverAddr.setKeyListener(android.text.method.DigitsKeyListener.getInstance("0123456789."));
        serverAddr.setRawInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);   // the keyboard shows the dot
        // the full-screen input of the landscape keyboard applies the type's own filter (one dot at most) to what is typed: keep it off
        serverAddr.setImeOptions(android.view.inputmethod.EditorInfo.IME_FLAG_NO_EXTRACT_UI | android.view.inputmethod.EditorInfo.IME_ACTION_DONE);
        serverAddr.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence c, int a, int b, int d) { }
            @Override public void onTextChanged(CharSequence c, int a, int b, int d) { }
            @Override public void afterTextChanged(Editable e) {
                settings.v.put(Settings.SERVER_ADDR, e.toString().trim());
                showServer();
            }
        });
        col.addView(serverAddr, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        col.addView(toggle("Доступ из локальной сети", Settings.SERVER_LAN,
                "Выкл: встроенный сервер слушает только этот телефон (127.0.0.1). Вкл: сервер виден в домашней сети, и другой телефон с этим мостом "
                        + "может подключиться к нему («Подключаться к другому серверу» на втором телефоне). Работа в фоне держится уведомлением; "
                        + "в этом режиме телефон не засыпает, пока сервер запущен. Применяется после перезапуска моста (приложение перезапустит себя)."));
        serverInfo = text("", 13, FG, false);
        serverInfo.setTextIsSelectable(true);
        serverInfo.setPadding(0, px(6), 0, 0);
        col.addView(serverInfo);
        applyCustomState();

        col.addView(section("Отладка"));
        col.addView(toggle("Подробный журнал сервера", Settings.SERVER_DEBUG,
                "Включает подробный журнал HTTP-сервера (uvicorn debug). Нужен только для поиска ошибок; применяется после перезапуска моста."));
        Button log = button("Показать журнал сервера");
        log.setOnClickListener(v -> showLog());
        col.addView(log);

        ScrollView sv = new ScrollView(this);
        sv.addView(col, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        Button reset = button("Вернуть как было");
        reset.setOnClickListener(v -> {
            settings.v.clear();
            settings.save(this);
            recreate();
        });
        Button saveOnly = button("Сохранить");
        saveOnly.setOnClickListener(v -> { if (save()) Toast.makeText(this, "Сохранено", Toast.LENGTH_SHORT).show(); });
        Button play = button("Играть");
        play.setOnClickListener(v -> { if (save()) play(); });
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setPadding(px(16), px(4), px(16), px(8));
        for (Button bt : new Button[] {reset, saveOnly, play}) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            lp.setMargins(px(4), 0, px(4), 0);
            bar.addView(bt, lp);
        }
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.addView(sv, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        root.addView(bar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        setContentView(root);
        hadAccess = Storage.hasAccess(this);
        refresh();
        ServerService.askNotifications(this);
        if (!hadAccess) askAccess();
    }

    @Override protected void onResume() {
        super.onResume();
        hadAccess = Storage.hasAccess(this);
        refresh();
    }

    @Override public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        refresh();
    }

    private void refresh() {
        if (gameInfo == null) return;
        File shared = Storage.shared(this);
        folderInfo.setText("Папка для файлов игры: " + shared.getPath() + (Storage.hasAccess(this) ? ""
                : "\n(нет доступа ко всем файлам: нажмите «Играть» или откройте настройки приложения и разрешите)"));
        gameInfo.setText(gameState());
        showServer();
    }

    /** Is the game installed, and which one. */
    private String gameState() {
        if (Storage.combined(this)) return "Игра встроена в это приложение.";
        try {
            PackageInfo pi = getPackageManager().getPackageInfo(Storage.GAME_PACKAGE, 0);
            return "Игра установлена: версия " + pi.versionName + " (код " + pi.getLongVersionCode() + ").";
        } catch (Exception e) {
            return "Игра не установлена. Положите оригинальные APK из Google Play (base.apk и split_config.arm64_v8a.apk) в папку выше "
                    + "и установите игру мостом-установщиком (MC5-Bridge-<версия>.apk).";
        }
    }

    private void showServer() {
        if (serverInfo == null) return;
        notifyInfo.setVisibility(ServerService.notificationsAllowed(this) ? View.GONE : View.VISIBLE);
        StringBuilder sb = new StringBuilder();
        if (settings.custom()) {
            String a = settings.get(Settings.SERVER_ADDR);
            sb.append(Settings.validIpv4(a) ? "Игра подключится к серверу " + a + " (встроенный не запускается)" : "Введите IPv4-адрес сервера");
        } else {
            sb.append("Встроенный сервер: 127.0.0.1:18080 (только этот телефон)");
            if (settings.on(Settings.SERVER_LAN)) {
                sb.setLength(0);
                sb.append("Встроенный сервер виден в сети");
                java.util.List<String> ips = ServerService.addresses();
                if (ips.isEmpty()) sb.append("\nПодключитесь к Wi-Fi: адрес появится здесь");
                for (String ip : ips) sb.append("\nНа втором телефоне введите адрес: ").append(ip);
            }
        }
        if (Backend.started()) sb.append("\nСейчас работает: ").append(Backend.key());
        if (!Backend.error().isEmpty()) sb.append("\n").append(Backend.error());
        serverInfo.setText(sb.toString());
    }

    private void applyCustomState() {
        if (serverAddr == null) return;
        boolean on = settings.custom();
        serverAddr.setEnabled(on);
        serverAddr.setAlpha(on ? 1f : 0.4f);
    }

    private boolean save() {
        if (settings.custom() && !Settings.validIpv4(settings.get(Settings.SERVER_ADDR))) {
            Toast.makeText(this, "Введите IPv4-адрес сервера, например 192.168.1.20", Toast.LENGTH_LONG).show();
            return false;
        }
        if (!settings.save(this)) {
            Toast.makeText(this, "Не удалось сохранить настройки", Toast.LENGTH_LONG).show();
            return false;
        }
        return true;
    }

    private void askAccess() {
        if (asked) return;
        asked = true;
        new AlertDialog.Builder(this)
                .setTitle("Доступ ко всем файлам")
                .setMessage("Чтобы брать оригинальные файлы игры и данные из удобной папки\n" + Storage.shared(this).getPath()
                        + "\nприложению нужен доступ ко всем файлам.")
                .setPositiveButton("Разрешить", (d, w) -> Storage.requestAccess(this, 2))
                .setNegativeButton("Позже", null)
                .show();
    }

    private void showLog() {
        startActivity(new Intent(this, LogActivity.class));
    }

    // ------------------------------------------------------------ play

    /** Starts the backend (off the UI thread), waits until it answers, then starts the game. */
    private void play() {
        if (Storage.combined(this) && DataImport.pending(this)) { importData(); return; }
        if (GameWatch.running()) { launchGame(); return; }              // the game is open: back to it, a second one would close itself
        if (GameWatch.ended()) {                                         // the game ran in this process and was closed: only a new process starts it
            new AlertDialog.Builder(this).setMessage("Игра была закрыта, а мост остался работать. Мост перезапустится — если экран не откроется сам, "
                    + "откройте приложение и нажмите «Играть».").setCancelable(false)
                    .setPositiveButton("OK", (d, w) -> Backend.restartProcess(getApplicationContext())).show();
            return;
        }
        busy = new AlertDialog.Builder(this).setTitle(settings.custom() ? "Подключение" : "Запуск")
                .setMessage(settings.custom() ? "Подключаюсь к серверу " + settings.get(Settings.SERVER_ADDR) + "…" : "Запускаю сервер…").setCancelable(false).create();
        busy.show();
        final Settings s = settings;
        new Thread(() -> {
            String err = Backend.start(getApplicationContext(), s);
            if ("restart".equals(err)) {
                runOnUiThread(() -> {
                    busy.setMessage("Настройки сервера изменены, мост перезапускается. Нажмите «Играть» ещё раз.");
                    new android.os.Handler().postDelayed(() -> Backend.restartProcess(getApplicationContext()), 800);
                });
                return;
            }
            if (err != null) {
                BridgeLog.i(getApplicationContext(), "Не запущено: " + err);
                runOnUiThread(() -> { busy.dismiss(); refresh(); showMessage(err); });
                return;
            }
            ServerService.start(getApplicationContext(), s);
            long end = System.currentTimeMillis() + (s.custom() ? 6000 : 180000);
            boolean ok = false;
            while (System.currentTimeMillis() < end && !(ok = Backend.ready(s))) {
                try { Thread.sleep(500); } catch (InterruptedException ignored) { }
                if (!s.custom() && !PyHost.running()) break;
            }
            final boolean ready = ok;
            BridgeLog.i(getApplicationContext(), ready ? "Сервер отвечает, запускаю игру" : "Сервер не ответил" + (s.custom() ? " (" + s.get(Settings.SERVER_ADDR) + ")" : ""));
            runOnUiThread(() -> {
                busy.dismiss();
                refresh();
                if (!ready) {
                    showMessage(s.custom() ? "Сервер " + s.get(Settings.SERVER_ADDR) + " не отвечает на порту 18080. Проверьте адрес и что сервер запущен."
                            : "Встроенный сервер не запустился. Журнал: «Показать журнал сервера».");
                    return;
                }
                launchGame();
            });
        }, "bridge-play").start();
    }

    /** First start: the game data from the BridgeGames folder goes to where the game reads it (DataImport), then the normal start. */
    private void importData() {
        final TextView msg = new TextView(this);
        msg.setPadding(px(24), px(16), px(24), px(8));
        msg.setText("Переношу данные игры (кэш)…");
        busy = new AlertDialog.Builder(this).setTitle("Первый запуск").setView(msg).setCancelable(false).create();
        busy.show();
        new Thread(() -> {
            try {
                BridgeLog.session(getApplicationContext(), "игра, первый запуск");
                BridgeLog.i(getApplicationContext(), "Переношу кэш игры");
                final long[] last = {0};
                DataImport.run(getApplicationContext(), (done, total) -> {
                    long now = System.currentTimeMillis();
                    if (now - last[0] < 300) return;
                    last[0] = now;
                    runOnUiThread(() -> msg.setText("Переношу данные игры: " + done / (1024 * 1024) + " из " + total / (1024 * 1024) + " МБ"));
                });
                BridgeLog.i(getApplicationContext(), "Кэш перенесён");
                // the game's own SharedPreferences were already read when this process started: restart so that it sees the imported files
                runOnUiThread(() -> {
                    busy.dismiss();
                    // Android 14+ does not let a background alarm start the screen again: the player opens the app himself
                    new AlertDialog.Builder(this).setTitle("Данные скопированы")
                            .setMessage("Приложение закроется. Откройте его снова и нажмите «Играть».").setCancelable(false)
                            .setPositiveButton("OK", (d, w) -> android.os.Process.killProcess(android.os.Process.myPid())).show();
                });
            } catch (Exception e) {
                BridgeLog.e(getApplicationContext(), "Не удалось перенести кэш игры", e);
                runOnUiThread(() -> { busy.dismiss(); showMessage("Не удалось скопировать данные игры: " + e.getMessage()); });
            }
        }, "bridge-data").start();
    }

    private void launchGame() {
        Activity open = GameWatch.screen();   // on foldables it is MainActivityMSDuo: bring that one to the front
        Intent i = Storage.combined(this)
                ? new Intent().setClassName(getPackageName(), open != null ? open.getClass().getName() : Storage.GAME_PACKAGE + ".MainActivity")
                : getPackageManager().getLaunchIntentForPackage(Storage.GAME_PACKAGE);
        if (i == null) {
            showMessage("Сервер работает, но игра не установлена.\n" + gameState());
            return;
        }
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);   // a running game comes to the front
        startActivity(i);
    }

    private void showMessage(String m) {
        new AlertDialog.Builder(this).setMessage(m).setPositiveButton("OK", null).show();
    }

    // ------------------------------------------------------------ widgets

    private int px(int v) { return Math.round(v * dp); }

    private TextView text(String s, int sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextColor(color);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        if (bold) t.setTypeface(t.getTypeface(), android.graphics.Typeface.BOLD);
        return t;
    }

    private View section(String title) {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.VERTICAL);
        l.setPadding(0, px(22), 0, px(4));
        l.addView(text(title.toUpperCase(), 12, ACCENT, true));
        return l;
    }

    private Button button(String label) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        return b;
    }

    private View toggle(String title, String key, String hint) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(0, px(10), 0, px(4));
        Switch sw = new Switch(this);
        sw.setText(title);
        sw.setTextColor(FG);
        sw.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        sw.setChecked(settings.on(key));
        sw.setOnCheckedChangeListener((b, on) -> {
            settings.v.put(key, on ? "1" : "0");
            if (key.equals(Settings.SERVER_LAN) && on) ServerService.askNotifications(this);
            if (key.equals(Settings.SERVER_CUSTOM)) applyCustomState();
            showServer();
        });
        row.addView(sw);
        row.addView(text(hint, 12, DIM, false));
        return row;
    }
}
