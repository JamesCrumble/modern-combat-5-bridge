package com.jamescrumble.mc5bridge;

import android.app.Activity;
import android.app.Application;
import android.content.Context;
import android.os.Bundle;

import java.lang.ref.WeakReference;

/**
 * The game's MainActivity runs once per process: its onCreate finishes any later instance that is not the task root while its static
 * self reference (set by the first instance, never cleared) is there, and the game ends its process itself when it quits. In B the
 * process outlives the game (ServerService keeps it), so after the game was closed another way (swiped from recents, destroyed by the
 * system) "Play" only flashed: the new game screen finished itself at once. Hence the bridge watches the first game screen of the process:
 * when it is destroyed, the process ends as the game would end it (progress mirrored first), except with "Доступ из локальной сети", where
 * the server keeps serving the other phones and the next "Play" restarts the process ({@link #ended}).
 */
final class GameWatch implements Application.ActivityLifecycleCallbacks {
    private static boolean installed;
    private static volatile WeakReference<Activity> game;   // the first game screen of this process
    private static volatile boolean ended;                   // it was destroyed: the game cannot start again in this process
    private final Context app;

    private GameWatch(Context app) { this.app = app; }

    static synchronized void install(Context c) {
        if (installed) return;
        Application a = (Application) c.getApplicationContext();
        a.registerActivityLifecycleCallbacks(new GameWatch(a));
        installed = true;
    }

    /** The game screen of this process is alive (bring it to the front instead of starting another one). */
    static boolean running() {
        WeakReference<Activity> g = game;
        Activity a = g == null ? null : g.get();
        return a != null && !ended && !a.isFinishing() && !a.isDestroyed();
    }

    /** The game already ran in this process and was closed: it starts again only in a new process. */
    static boolean ended() { return ended; }

    private static boolean isGame(Activity a) {
        return a.getClass().getName().equals(Storage.GAME_PACKAGE + ".MainActivity");
    }

    @Override public void onActivityCreated(Activity a, Bundle state) {
        if (isGame(a) && game == null) {
            game = new WeakReference<>(a);
            BridgeLog.i(app, "Игра запущена");
        }
    }

    @Override public void onActivityDestroyed(Activity a) {
        WeakReference<Activity> g = game;
        if (g == null || g.get() != a || a.isChangingConfigurations()) return;   // later instances finish themselves: not the game ending
        ended = true;
        if (Settings.load(app).on(Settings.SERVER_LAN)) {
            BridgeLog.i(app, "Игра закрыта; процесс остаётся: сервер нужен локальной сети");
            return;
        }
        BridgeLog.i(app, "Игра закрыта: процесс завершается, как это делает сама игра");
        Backend.flushMirror(app);
        android.os.Process.killProcess(android.os.Process.myPid());
    }

    @Override public void onActivityStarted(Activity a) { }
    @Override public void onActivityResumed(Activity a) { }
    @Override public void onActivityPaused(Activity a) { }
    @Override public void onActivityStopped(Activity a) { }
    @Override public void onActivitySaveInstanceState(Activity a, Bundle out) { }
}
