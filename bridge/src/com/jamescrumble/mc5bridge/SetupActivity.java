package com.jamescrumble.mc5bridge;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import com.jamescrumble.mc5bridge.patch.Keys;
import com.jamescrumble.mc5bridge.patch.Patcher;

import java.io.File;
import java.io.IOException;

/**
 * The installer (A, documentation/architecture.md): takes the original game files from {@code BridgeGames/<package of the game>/} (base.apk, split_config.arm64_v8a.apk),
 * builds the combined APK B on the phone with the same patcher as the PC build, signs it with the key of this device
 * ({@code patched-apk.key} in the same folder), installs it and offers to remove itself. B (package of the game) has its own screen and the server.
 */
public final class SetupActivity extends Activity {
    private static final int BG = 0xFF12161A, FG = 0xFFE6E6E6, DIM = 0xFF9AA4AD, WARN = 0xFFFFB74D;

    private TextView info, steps;
    private Button go;
    private float dp;
    private boolean busy;
    private File builtApk;
    private Runnable afterUninstall;

    @Override protected void onCreate(Bundle state) {
        setTheme(android.R.style.Theme_Material_NoActionBar);
        super.onCreate(state);
        BridgeLog.hookCrashes(this);
        getWindow().setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(0xFF000000));
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        dp = getResources().getDisplayMetrics().density;
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(px(20), px(16), px(20), px(24));
        col.addView(text("Modern Combat 5 — установка", 22, FG, true));
        col.addView(text("Положите в папку ниже два APK игры из Google Play и архив кэша, нажмите «Установить игру». Мост подготовит игру на этом телефоне.", 13, DIM, false));
        info = text("", 14, FG, false);
        info.setPadding(0, px(14), 0, 0);
        info.setTextIsSelectable(true);
        col.addView(info);
        steps = text("", 13, DIM, false);
        steps.setPadding(0, px(14), 0, 0);
        col.addView(steps);
        ScrollView sv = new ScrollView(this);
        sv.addView(col, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        go = new Button(this);
        go.setText("Установить игру");
        go.setOnClickListener(v -> start());
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.addView(sv, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(px(20), px(6), px(20), px(10));
        root.addView(go, lp);
        setContentView(root);
        ServerService.askNotifications(this);
    }

    @Override protected void onResume() {
        super.onResume();
        refresh();
    }

    private int px(int v) { return Math.round(v * dp); }

    private TextView text(String s, int sp, int color, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextColor(color);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        if (bold) t.setTypeface(t.getTypeface(), android.graphics.Typeface.BOLD);
        return t;
    }

    private PackageInfo installed() {
        try {
            return getPackageManager().getPackageInfo(Storage.GAME_PACKAGE, 0);
        } catch (Exception e) {
            return null;
        }
    }

    private void refresh() {
        StringBuilder sb = new StringBuilder();
        File folder = Storage.shared(this);
        sb.append("Папка: ").append(folder.getPath()).append('\n');
        if (!Storage.hasAccess(this)) {
            sb.append("Нет доступа ко всем файлам — он нужен, чтобы брать файлы из этой папки. Нажмите «Установить игру», чтобы разрешить.\n");
        } else {
            folder.mkdirs();                    // the player puts the files here: the folder must exist once access is granted
            File[] apks = Storage.gameApks(folder);
            sb.append(line(apks[0], "base.apk (APK игры)"));
            sb.append(line(apks[1], "split_config.arm64_v8a.apk (библиотеки игры)"));
            File zip = DataImport.cacheZip(folder);
            boolean dirs = new File(folder, "internal").isDirectory() || new File(folder, "external").isDirectory();
            sb.append(zip != null ? "✓ кэш игры: " + zip.getName() + " (" + zip.length() / (1024 * 1024) + " МБ)\n"
                    : dirs ? "✓ данные игры (internal/, external/)\n" : "✗ нет кэша игры (MC5-cache-….zip) — см. INSTALL.txt\n" + DataImport.explain(folder) + "\n");
            if (zip == null && Backend.serverData(folder, null, null) == null) sb.append("✗ нет данных сервера (они в архиве кэша) — см. INSTALL.txt\n");
            sb.append(new File(folder, "patched-apk.key").isFile() ? "✓ ключ подписи (patched-apk.key)\n" : "· ключ подписи будет создан\n");
        }
        PackageInfo pi = installed();
        sb.append(pi == null ? "Игра не установлена." : "Игра установлена: версия " + pi.versionName + ".");
        info.setText(sb.toString());
        go.setEnabled(!busy);
    }

    private static String line(File f, String name) {
        return f != null && f.isFile() ? "✓ " + name + ": " + f.getName() + " (" + f.length() / (1024 * 1024) + " МБ)\n" : "✗ нет " + name + "\n";
    }

    private void log(final String m) {
        BridgeLog.i(getApplicationContext(), "[установка] " + m);
        runOnUiThread(() -> steps.setText(steps.getText() + (steps.length() > 0 ? "\n" : "") + m));
    }

    private void start() {
        if (busy) return;
        if (!Storage.hasAccess(this)) { Storage.requestAccess(this, 2); return; }
        File folder = Storage.shared(this);
        File[] apks = Storage.gameApks(folder);
        final File base = apks[0], arm = apks[1];
        if (base == null || arm == null) {
            new AlertDialog.Builder(this).setMessage("В папке\n" + folder.getPath() + "\nдолжны лежать два APK игры Modern Combat 5 6.0.12a из Google Play: "
                    + "основной (base.apk) и split_config.arm64_v8a.apk. Имена файлов не важны.")
                    .setPositiveButton("OK", null).show();
            return;
        }
        if (!getPackageManager().canRequestPackageInstalls()) {       // asked before the long build, not after it
            new AlertDialog.Builder(this).setTitle("Нужно разрешение")
                    .setMessage("Чтобы поставить подготовленную игру, разрешите этому приложению устанавливать приложения (один раз). "
                            + "Откроется окно настроек; включите переключатель и вернитесь назад.")
                    .setPositiveButton("Открыть настройки", (d, w) -> startActivity(new Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                            Uri.parse("package:" + getPackageName()))))
                    .setNegativeButton("Отмена", null).show();
            return;
        }
        final boolean haveB = installed() != null;
        final File keyFile = new File(folder, "patched-apk.key");
        if (haveB && !keyFile.isFile()) {
            new AlertDialog.Builder(this).setTitle("Ключ подписи не найден")
                    .setMessage("Игра уже установлена, но файла patched-apk.key нет. Новую версию можно поставить только после удаления установленной, "
                            + "и сохранения игры могут не подхватиться.\n\nПродолжить?")
                    .setPositiveButton("Продолжить", (d, w) -> build(base, arm, keyFile, true))
                    .setNegativeButton("Отмена", null).show();
            return;
        }
        build(base, arm, keyFile, false);
    }

    private void build(final File base, final File arm, final File keyFile, final boolean removeOld) {
        busy = true;
        go.setEnabled(false);
        steps.setText("");
        BridgeLog.session(getApplicationContext(), "установщик");
        BridgeLog.i(getApplicationContext(), "[установка] APK игры: " + base.getName() + " (" + base.length() + " Б), " + arm.getName() + " (" + arm.length() + " Б)");
        new Thread(() -> {
            try {
                Keys keys;
                if (keyFile.isFile()) {
                    keys = Keys.load(keyFile);
                } else {
                    log("Создаю ключ подписи");
                    keys = Keys.create("MC5 Bridge");
                    keys.save(keyFile);
                }
                File out = new File(getCacheDir(), "MC5-full.apk");
                Patcher.Options o = new Patcher.Options();
                o.vars = Patcher.defaultVars(Storage.GAME_PACKAGE);
                Patcher.build(base, arm, new File(getApplicationInfo().sourceDir), out, new File(getCacheDir(), "patch"), keys,
                        name -> readAsset("patch/" + name), o, this::log);
                builtApk = out;
                runOnUiThread(() -> { if (removeOld) uninstallOld(); else install(); });
            } catch (Throwable t) {
                BridgeLog.e(getApplicationContext(), "[установка] Ошибка сборки игры", t);
                runOnUiThread(() -> steps.setText(steps.getText() + "\nОшибка: " + t.getMessage()));
                runOnUiThread(() -> { busy = false; refresh(); });
            }
        }, "bridge-patch").start();
    }

    private String readAsset(String name) throws IOException {
        try (java.io.InputStream in = getAssets().open(name)) {
            java.io.ByteArrayOutputStream o = new java.io.ByteArrayOutputStream();
            byte[] b = new byte[8192];
            int n;
            while ((n = in.read(b)) > 0) o.write(b, 0, n);
            return o.toString("UTF-8");
        }
    }

    private void uninstallOld() {
        log("Удаляю установленную игру (подтвердите в окне Android)");
        afterUninstall = this::install;
        Intent i = new Intent(Intent.ACTION_UNINSTALL_PACKAGE, Uri.parse("package:" + Storage.GAME_PACKAGE));
        i.putExtra(Intent.EXTRA_RETURN_RESULT, true);
        startActivityForResult(i, 7);
    }

    @Override protected void onActivityResult(int code, int result, Intent data) {
        super.onActivityResult(code, result, data);
        if (code == 7) {
            if (installed() == null && afterUninstall != null) { Runnable r = afterUninstall; afterUninstall = null; r.run(); }
            else { log("Удаление отменено, установка остановлена."); busy = false; refresh(); }
        }
    }

    private void install() {
        log("Установка (подтвердите в окне Android)");
        try {
            Installer.install(this, builtApk, (ok, msg) -> runOnUiThread(() -> {
                busy = false;
                builtApk.delete();
                refresh();
                if (!ok) { log("Установка не удалась: " + msg); return; }
                log("Готово: игра установлена.");
                new AlertDialog.Builder(this).setTitle("Игра установлена")
                        .setMessage("Теперь у игры свой экран моста и сервер. Это приложение-установщик больше не нужно: удалить его? "
                                + "(Оно понадобится снова только для обновления.)")
                        .setPositiveButton("Удалить", (d, w) -> startActivity(new Intent(Intent.ACTION_DELETE, Uri.parse("package:" + getPackageName()))))
                        .setNegativeButton("Оставить", null).show();
            }));
        } catch (IOException e) {
            log("Ошибка установки: " + e.getMessage());
            busy = false;
            refresh();
        }
    }
}
