package com.jamescrumble.mc5bridge;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;

/**
 * The server log (server.log) or the bridge's (mc5.log) ({@link BridgeLog}: BridgeGames/<game>/), refreshed every 2 s while shown. Opened from the bridge screen and from the server
 * notification. It lands on top of the game's task and only finishes itself: the game screen under it stays (see {@link GameWatch}).
 */
public final class LogActivity extends Activity {
    private static final int BG = Color.rgb(18, 22, 26), FG = Color.rgb(230, 235, 238), DIM = Color.rgb(140, 150, 156);
    private static final int LINES = 400;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private TextView log, info;
    private ScrollView scroll;
    private String shown = "";
    private boolean bridge;   // false: server.log, true: mc5.log
    private TextView title;
    private Button which;
    private float dp;

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            refresh();
            ui.postDelayed(this, 2000);
        }
    };

    @Override protected void onCreate(Bundle state) {
        setTheme(android.R.style.Theme_Material_NoActionBar);   // no resources of the bridge in the combined APK
        super.onCreate(state);
        getWindow().setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(BG));
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        dp = getResources().getDisplayMetrics().density;

        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(px(16), px(12), px(16), px(12));

        title = new TextView(this);
        title.setTextColor(FG);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        title.setTypeface(title.getTypeface(), Typeface.BOLD);
        col.addView(title);
        info = new TextView(this);
        info.setTextColor(DIM);
        info.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        col.addView(info);

        log = new TextView(this);
        log.setTextColor(FG);
        log.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        log.setTypeface(Typeface.MONOSPACE);
        log.setTextIsSelectable(true);
        scroll = new ScrollView(this);
        scroll.addView(log);
        col.addView(scroll, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));

        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.END);
        which = button("");
        which.setOnClickListener(v -> { bridge = !bridge; shown = null; refresh(); });
        Button copy = button("Копировать");
        copy.setOnClickListener(v -> {
            getSystemService(ClipboardManager.class).setPrimaryClip(ClipData.newPlainText(bridge ? "mc5.log" : "server.log", shown));
            Toast.makeText(this, "Журнал скопирован", Toast.LENGTH_SHORT).show();
        });
        Button close = button("Закрыть");
        close.setOnClickListener(v -> finish());
        row.addView(which);
        row.addView(copy);
        row.addView(close);
        col.addView(row);
        setContentView(col);
    }

    @Override protected void onResume() {
        super.onResume();
        ui.post(tick);
    }

    @Override protected void onPause() {
        ui.removeCallbacks(tick);
        super.onPause();
    }

    private void refresh() {
        File f = bridge ? BridgeLog.file(this) : BridgeLog.serverFile(this);
        title.setText(bridge ? "Журнал моста (mc5.log)" : "Журнал сервера (server.log)");
        which.setText(bridge ? "Журнал сервера" : "Журнал моста");
        String t = Storage.tail(f, LINES);
        info.setText(f.getPath() + (f.isFile() ? " · " + f.length() / 1024 + " КБ · последние " + LINES + " строк" : ""));
        if (t.equals(shown)) return;
        boolean atEnd = shown == null || shown.isEmpty() || scroll.getScrollY() + scroll.getHeight() >= log.getHeight() - px(48);
        shown = t;
        log.setText(t.isEmpty() ? "Журнал пуст." : t);
        if (atEnd) scroll.post(() -> scroll.fullScroll(ScrollView.FOCUS_DOWN));   // follow new lines unless the player scrolled up
    }

    private Button button(String label) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        return b;
    }

    private int px(int v) { return Math.round(v * dp); }
}
